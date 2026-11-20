"""HTTP session handling and ILIAS navigation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

import httpx

from . import parser
from .parser import Item

BASE_URL = os.environ.get("ILIAS_BASE_URL", "https://elearning.hslu.ch/ilias/")
DASHBOARD_URL = BASE_URL + "ilias.php?baseClass=ilmembershipoverviewgui"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ilias-cli"
COOKIE_FILE = CONFIG_DIR / "cookies.json"

USER_AGENT = "ilias-cli/0.1 (+httpx)"


class IliasError(Exception):
    pass


class NotLoggedIn(IliasError):
    pass


# --------------------------------------------------------------------------- cookies

def parse_cookie_input(raw: str) -> dict[str, str]:
    """Accept either a bare PHPSESSID value or a 'name=value; name2=value2' header."""
    raw = raw.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    if "=" not in raw:
        return {"PHPSESSID": raw}
    cookies = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def save_cookies(cookies: dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, indent=2))
    COOKIE_FILE.chmod(0o600)


def load_cookies() -> dict[str, str]:
    if not COOKIE_FILE.exists():
        raise NotLoggedIn("No session stored. Run `ilias login` first.")
    return json.loads(COOKIE_FILE.read_text())


# --------------------------------------------------------------------------- filenames

_UNSAFE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def safe_name(name: str) -> str:
    """Make an ILIAS title / server-supplied filename safe as a single path component."""
    name = _UNSAFE.sub("_", name).strip().strip(".")
    return name[:200] or "unnamed"


def _filename_from_response(resp: httpx.Response) -> str | None:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd) or re.search(r"filename\s*=\s*([^;]+)", cd)
    if m:
        return m.group(1).strip()
    return None


# --------------------------------------------------------------------------- client

class Ilias:
    def __init__(self, cookies: dict[str, str] | None = None):
        self.http = httpx.Client(
            cookies=cookies if cookies is not None else load_cookies(),
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=120.0),
            headers={"User-Agent": USER_AGENT},
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "Ilias":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low level ---------------------------------------------------------

    def get_page(self, url: str) -> tuple[str, str]:
        """Fetch an HTML page, returning (html, final_url). Raises NotLoggedIn on expired session."""
        try:
            resp = self.http.get(url)
        except httpx.HTTPError as e:
            raise IliasError(f"Request failed: {e}") from e
        html = resp.text
        if not str(resp.url).startswith(BASE_URL) or not parser.is_logged_in(html):
            raise NotLoggedIn("Session expired or invalid. Run `ilias login` again.")
        if resp.status_code >= 400:
            raise IliasError(f"HTTP {resp.status_code} for {url}")
        return html, str(resp.url)

    # -- listing -----------------------------------------------------------

    def dashboard(self) -> list[Item]:
        html, url = self.get_page(DASHBOARD_URL)
        return parser.parse_dashboard(html, url)

    def list(self, item: Item) -> list[Item]:
        if not item.is_container:
            raise IliasError(f"'{item.title}' is a {item.type}, not a folder/course.")
        html, url = self.get_page(self.object_url(item))
        return parser.parse_container(html, url)

    @staticmethod
    def object_url(item: Item) -> str:
        if item.ref_id is not None and item.type not in ("?", None):
            return f"{BASE_URL}goto.php/{item.type}/{item.ref_id}"
        return item.url

    def resolve(self, path: str) -> tuple[Item | None, list[Item]]:
        """Resolve a slash-separated path starting at the dashboard.

        Returns (item, children) where item is None for the root. Segments are matched
        case-insensitively: exact title first, then unique prefix, then unique substring.
        A segment may also be a ref id ('7273189' or 'ref:7273189')."""
        segments = [s for s in path.strip("/").split("/") if s]
        current: Item | None = None
        children = self.dashboard()
        for i, seg in enumerate(segments):
            current = self._match(seg, children, segments[:i])
            if i < len(segments) - 1 or current.is_container:
                if not current.is_container:
                    raise IliasError(f"'{current.title}' is a {current.type}, not a folder/course.")
                children = self.list(current)
            else:
                children = []
        return current, children

    @staticmethod
    def _match(seg: str, items: list[Item], parent: list[str]) -> Item:
        ref = seg[4:] if seg.lower().startswith("ref:") else seg
        if ref.isdigit():
            for it in items:
                if it.ref_id == int(ref):
                    return it
        s = seg.lower()
        for pred in (lambda t: t == s, lambda t: t.startswith(s), lambda t: s in t):
            hits = [it for it in items if pred(it.title.lower())]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                names = ", ".join(f"'{h.title}'" for h in hits)
                raise IliasError(f"'{seg}' is ambiguous: {names}")
        where = "/" + "/".join(parent)
        raise IliasError(f"No item matching '{seg}' in {where}")

    def walk(self, item: Item, rel: Path = Path()) -> Iterator[tuple[Path, Item]]:
        """Recursively yield (relative_dir, file_item) for all files below a container."""
        for child in self.list(item):
            if child.is_file:
                yield rel, child
            elif child.type in ("fold", "grp", "crs", "cat"):
                yield from self.walk(child, rel / safe_name(child.title))

    # -- downloading -------------------------------------------------------

    def download_url(self, item: Item) -> str:
        if "download" in item.url or "sendfile" in item.url:
            return item.url
        return f"{BASE_URL}goto.php/file/{item.ref_id}/download"

    def download(self, item: Item, dest_dir: Path, *, overwrite: bool = True,
                 progress=None) -> Path:
        """Download a file item into dest_dir. Returns the written path."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        with self.http.stream("GET", self.download_url(item)) as resp:
            ctype = resp.headers.get("content-type", "")
            if resp.status_code >= 400:
                raise IliasError(f"HTTP {resp.status_code} downloading '{item.title}'")
            if "text/html" in ctype and not _filename_from_response(resp):
                resp.read()
                if not parser.is_logged_in(resp.text):
                    raise NotLoggedIn("Session expired or invalid. Run `ilias login` again.")
                raise IliasError(f"Expected a file for '{item.title}' but got an HTML page "
                                 f"({resp.url}). It may not be downloadable.")
            name = _filename_from_response(resp)
            if not name:
                ext = parser.file_extension(item)
                name = item.title + (f".{ext}" if ext and not item.title.lower().endswith(f".{ext}") else "")
            target = dest_dir / safe_name(name)
            if target.exists() and not overwrite:
                return target
            tmp = target.with_name(target.name + ".part")
            total = int(resp.headers.get("content-length") or 0) or None
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(64 * 1024):
                    fh.write(chunk)
                    if progress:
                        progress(len(chunk), total)
            tmp.replace(target)
            return target
