"""HTML parsing for ILIAS 9 pages (dashboard + container content views)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

# Object types that contain other objects and can be listed.
CONTAINER_TYPES = {"crs", "grp", "fold", "cat", "root"}

# baseClass -> type, for links that don't use goto.php.
_BASECLASS_TYPES = {
    "illinkresourcehandlergui": "webr",
    "ilobjfilegui": "file",
    "ilrepositorygui": None,  # generic, needs other hints
}

_GOTO_PATH = re.compile(r"goto\.php/(?P<type>[a-z]+)/(?P<ref>\d+)(?P<rest>/[^?#]*)?")
_GOTO_TARGET = re.compile(r"^(?P<type>[a-z]+)_(?P<ref>\d+)(?:_(?P<rest>\w+))?$")


@dataclass
class Item:
    title: str
    type: str          # crs, grp, fold, file, webr, frm, ...
    ref_id: int | None
    url: str
    description: str = ""
    properties: dict[str, str] = field(default_factory=dict)

    @property
    def is_container(self) -> bool:
        return self.type in CONTAINER_TYPES

    @property
    def is_file(self) -> bool:
        return self.type == "file"


def classify_url(url: str) -> tuple[str | None, int | None]:
    """Return (type, ref_id) for an ILIAS link, as far as it can be determined."""
    m = _GOTO_PATH.search(url)
    if m:
        return m["type"], int(m["ref"])
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "target" in qs:
        m = _GOTO_TARGET.match(qs["target"][0])
        if m:
            return m["type"], int(m["ref"])
    ref = qs.get("ref_id", [None])[0]
    ref_id = int(ref) if ref and ref.isdigit() else None
    base = qs.get("baseClass", [""])[0].lower()
    typ = _BASECLASS_TYPES.get(base)
    if qs.get("cmd", [""])[0] == "sendfile":
        typ = "file"
    return typ, ref_id


# Icon alt texts (German + English UI) -> type, used as fallback.
_ICON_TYPES = {
    "kurs": "crs", "course": "crs",
    "gruppe": "grp", "group": "grp",
    "ordner": "fold", "folder": "fold",
    "kategorie": "cat", "category": "cat",
    "datei": "file", "file": "file",
    "weblink": "webr", "weblinks": "webr",
    "forum": "frm",
    "übung": "exc", "exercise": "exc",
    "test": "tst",
    "lernmodul": "lm",
    "sitzung": "sess", "session": "sess",
}


def _icon_type(scope: Tag) -> str | None:
    img = scope.select_one("img.ilListItemIcon, .media-left img")
    if img is None:
        return None
    alt = (img.get("alt") or img.get("title") or "").strip().lower()
    if alt in _ICON_TYPES:
        return _ICON_TYPES[alt]
    m = re.search(r"icon_([a-z]+)", img.get("src", ""))
    return m.group(1) if m else None


def _text(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def is_logged_in(html: str) -> bool:
    return "cmd=doLogout" in html


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return _text(soup.title)


def parse_dashboard(html: str, base_url: str) -> list[Item]:
    """Parse the 'Meine Kurse und Gruppen' / favourites page (UI-framework items)."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[Item] = []
    seen: set[int | None] = set()
    for item_div in soup.select("div.il-item.il-std-item"):
        a = item_div.select_one(".il-item-title a[href]")
        if a is None:
            continue
        url = urljoin(base_url, a["href"])
        typ, ref = classify_url(url)
        typ = typ or _icon_type(item_div) or "?"
        if ref in seen and ref is not None:
            continue
        seen.add(ref)
        props: dict[str, str] = {}
        for name in item_div.select(".il-item-property-name"):
            value = name.find_next_sibling(class_="il-item-property-value")
            key, val = _text(name), _text(value)
            if key and val:
                props[key] = val
        items.append(Item(
            title=_text(a), type=typ, ref_id=ref, url=url,
            description=_text(item_div.select_one(".il-item-description")),
            properties=props,
        ))
    return items


def parse_container(html: str, base_url: str) -> list[Item]:
    """Parse the content listing of a course / group / folder / category."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[Item] = []
    seen: set[int | None] = set()
    for outer in soup.select("div.ilContainerListItemOuter"):
        a = outer.select_one("a.il_ContainerItemTitle[href]")
        if a is None:
            continue
        url = urljoin(base_url, a["href"])
        typ, ref = classify_url(url)
        if ref is None:
            m = re.match(r"lg_div_(\d+)_", outer.get("id", ""))
            ref = int(m.group(1)) if m else None
        typ = typ or _icon_type(outer) or "?"
        # The same object can appear in several item groups / blocks.
        if ref is not None and ref in seen:
            continue
        seen.add(ref)
        props: dict[str, str] = {}
        for prop in outer.select(".il_ItemProperty"):
            txt = _text(prop)
            # 'Version: 2' is a labelled property; '12. Sep 2026, 16:44' is not.
            m = re.match(r"^([^:\d][^:]*?):(?:\s+(.*))?$", txt)
            if m:
                props[m.group(1).strip()] = (m.group(2) or "").strip()
            elif txt:
                props.setdefault("_", "")
                props["_"] = (props["_"] + " " + txt).strip()
        items.append(Item(
            title=_text(a), type=typ, ref_id=ref, url=url,
            description=_text(outer.select_one(".il_Description")),
            properties=props,
        ))
    return items


def file_extension(item: Item) -> str | None:
    """ILIAS shows the extension as the first unnamed property, e.g. 'pdf'."""
    first = item.properties.get("_", "").split()
    if first and re.fullmatch(r"[A-Za-z0-9]{1,8}", first[0]):
        return first[0].lower()
    return None
