"""Command line interface: ilias login / ls / tree / get / sync."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from . import client as C
from .client import Ilias, IliasError, NotLoggedIn
from .parser import Item

app = typer.Typer(
    help="Browse and download files from HSLU ILIAS.\n\n"
         "Paths start at your courses & groups dashboard, e.g. "
         "'PLAB.H2601/Unterlagen OOP'. Segments match case-insensitively by "
         "exact title, unique prefix or unique substring, or by ref id.",
    no_args_is_help=True,
    add_completion=False,
)

TYPE_LABEL = {
    "crs": "course", "grp": "group", "fold": "folder", "cat": "category",
    "file": "file", "webr": "link", "frm": "forum", "exc": "exercise",
    "tst": "test", "sess": "session", "lm": "module", "wiki": "wiki",
}


def _err(msg: str, code: int = 1) -> None:
    typer.secho(f"error: {msg}", fg="red", err=True)
    raise typer.Exit(code)


def _session() -> Ilias:
    try:
        return Ilias()
    except NotLoggedIn as e:
        _err(str(e))


def _run(fn):
    """Run fn and turn ILIAS errors into clean messages."""
    try:
        return fn()
    except NotLoggedIn as e:
        _err(str(e), 2)
    except IliasError as e:
        _err(str(e))


def _fmt_item(it: Item, long: bool) -> str:
    label = TYPE_LABEL.get(it.type, it.type)
    name = it.title + ("/" if it.is_container else "")
    color = "blue" if it.is_container else ("green" if it.is_file else None)
    line = typer.style(name, fg=color, bold=it.is_container)
    if long:
        extra = " ".join(v for v in [it.properties.get("_", "")] if v)
        line = f"{label:<9} {str(it.ref_id or ''):>8}  {line}" + (f"  [{extra}]" if extra else "")
    return line


# --------------------------------------------------------------------------- auth

@app.command()
def login(
    cookie: Optional[str] = typer.Option(
        None, "--cookie", "-c",
        help="PHPSESSID value or full 'Cookie:' header. Prompted (hidden) if omitted."),
):
    """Store an ILIAS session cookie taken from your browser.

    Log in to https://elearning.hslu.ch/ilias in your browser, open DevTools
    (F12) → Application/Storage → Cookies → elearning.hslu.ch, and copy the
    value of PHPSESSID (copying the whole Cookie header from the Network tab works too).
    """
    if cookie is None:
        cookie = typer.prompt("PHPSESSID (or Cookie header)", hide_input=True)
    cookies = C.parse_cookie_input(cookie)
    with Ilias(cookies) as il:
        try:
            items = il.dashboard()
        except NotLoggedIn:
            _err("That cookie is not a valid logged-in session.")
        except IliasError as e:
            _err(str(e))
    C.save_cookies(cookies)
    typer.secho(f"Logged in. {len(items)} courses/groups found. Session saved to {C.COOKIE_FILE}",
                fg="green")


@app.command()
def logout():
    """Forget the stored session cookie."""
    C.COOKIE_FILE.unlink(missing_ok=True)
    typer.echo("Session removed.")


@app.command()
def status():
    """Check whether the stored session still works."""
    with _session() as il:
        items = _run(il.dashboard)
    typer.secho(f"Session OK – {len(items)} courses/groups on your dashboard.", fg="green")


# --------------------------------------------------------------------------- browsing

@app.command()
def ls(
    path: str = typer.Argument("", help="Path to list (default: dashboard)."),
    long: bool = typer.Option(False, "--long", "-l", help="Show type, ref id and file info."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
):
    """List the contents of a course, group or folder."""
    with _session() as il:
        item, children = _run(lambda: il.resolve(path))
    if item is not None and not item.is_container:
        children = [item]
    if as_json:
        json.dump([{**vars(c), "is_container": c.is_container} for c in children],
                  sys.stdout, ensure_ascii=False, indent=2)
        typer.echo()
        return
    if not children:
        typer.echo("(empty)")
    for c in children:
        typer.echo(_fmt_item(c, long))


@app.command()
def tree(
    path: str = typer.Argument("", help="Start path (default: dashboard)."),
    depth: int = typer.Option(3, "--depth", "-d", help="Maximum depth."),
):
    """Show a tree of containers and files."""
    with _session() as il:
        item, children = _run(lambda: il.resolve(path))
        typer.echo(item.title if item else "ILIAS")

        def show(items: list[Item], prefix: str, level: int):
            for i, c in enumerate(items):
                last = i == len(items) - 1
                typer.echo(prefix + ("└── " if last else "├── ") + _fmt_item(c, False))
                if c.is_container and level < depth:
                    sub = _run(lambda: il.list(c))
                    show(sub, prefix + ("    " if last else "│   "), level + 1)

        show(children, "", 1)


@app.command()
def url(path: str = typer.Argument(..., help="Item path.")):
    """Print the browser URL of an item."""
    with _session() as il:
        item, _ = _run(lambda: il.resolve(path))
    typer.echo(Ilias.object_url(item) if item else C.DASHBOARD_URL)


# --------------------------------------------------------------------------- downloading

class _Progress:
    def __init__(self, name: str):
        self.name, self.done = name, 0

    def __call__(self, n: int, total: int | None):
        self.done += n
        if sys.stderr.isatty():
            pct = f"{self.done * 100 // total:3d}%" if total else f"{self.done // 1024} KiB"
            sys.stderr.write(f"\r  {pct}  {self.name[:60]}")
            sys.stderr.flush()

    def finish(self):
        if sys.stderr.isatty():
            sys.stderr.write("\r\033[K")


def _download_one(il: Ilias, it: Item, dest: Path, overwrite: bool) -> Path:
    p = _Progress(it.title)
    try:
        return _run(lambda: il.download(it, dest, overwrite=overwrite, progress=p))
    finally:
        p.finish()


@app.command()
def get(
    path: str = typer.Argument(..., help="File or folder path."),
    out: Path = typer.Option(Path("."), "--out", "-o", help="Target directory."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files."),
):
    """Download a file, or a whole folder/course recursively."""
    with _session() as il:
        item, _ = _run(lambda: il.resolve(path))
        if item is None:
            _err("Refusing to download your entire dashboard; pick a course or folder.")
        if item.is_file:
            target = _download_one(il, item, out, overwrite=True)
            typer.secho(f"✓ {target}", fg="green")
            return
        if not item.is_container:
            _err(f"'{item.title}' is a {TYPE_LABEL.get(item.type, item.type)} and can't be downloaded.")
        root = out / C.safe_name(item.title)
        count = 0
        for rel, f in _run(lambda: list(il.walk(item))):
            target = _download_one(il, f, root / rel, overwrite=force)
            typer.echo(f"✓ {target}")
            count += 1
        typer.secho(f"{count} file(s) in {root}", fg="green")


MANIFEST = ".ilias-sync.json"


@app.command()
def sync(
    path: str = typer.Argument(..., help="Course or folder path."),
    dest: Path = typer.Argument(..., help="Local directory to mirror into."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Only show what would change."),
):
    """Mirror a course/folder into a local directory, downloading only new or changed files.

    Changes are detected via the version/date info ILIAS shows next to each file;
    state is kept in DEST/.ilias-sync.json. Local files are never deleted."""
    manifest_path = dest / MANIFEST
    manifest: dict = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with _session() as il:
        item, _ = _run(lambda: il.resolve(path))
        if item is None or not item.is_container:
            _err("sync needs a course, group or folder.")
        files = _run(lambda: list(il.walk(item)))
        new = updated = 0
        for rel, f in files:
            key = str(f.ref_id)
            fingerprint = json.dumps(f.properties, sort_keys=True, ensure_ascii=False)
            entry = manifest.get(key)
            if entry and entry["fingerprint"] == fingerprint and (dest / entry["path"]).exists():
                continue
            label = "updated" if entry else "new"
            if dry_run:
                typer.echo(f"{label:>7}  {rel / f.title}")
                continue
            target = _download_one(il, f, dest / rel, overwrite=True)
            manifest[key] = {"path": str(target.relative_to(dest)), "fingerprint": fingerprint,
                             "title": f.title}
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            typer.secho(f"{label:>7}  {target.relative_to(dest)}",
                        fg="green" if label == "new" else "yellow")
            new += label == "new"
            updated += label == "updated"
    if not dry_run:
        typer.echo(f"{len(files)} file(s) checked, {new} new, {updated} updated.")


def main():
    app()


if __name__ == "__main__":
    main()
