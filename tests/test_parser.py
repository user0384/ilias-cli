from pathlib import Path

import pytest

from ilias_cli import client, parser

BASE = "https://elearning.hslu.ch/ilias/ilias.php"

DASHBOARD = """
<a href="ilias.php?baseClass=ilstartupgui&amp;cmd=doLogout&amp;rtoken=x">Logout</a>
<div class="il-item il-std-item"><div class="media">
  <div class="media-left"><img class="icon" src="icon_crs.svg" alt="Kurs"></div>
  <div class="media-body">
    <h4 class="il-item-title"><a href="https://elearning.hslu.ch/ilias/goto.php/crs/100">I.BA_PLAB.H2601</a></h4>
    <div class="il-item-description">Programmier-Labor</div>
    <span class="il-item-property-name">Anmeldung</span><span class="il-item-property-value">Keine</span>
  </div></div></div>
<div class="il-item il-std-item"><div class="media"><div class="media-body">
    <h4 class="il-item-title"><a href="https://elearning.hslu.ch/ilias/goto.php/grp/101">I.BA_PLAB.H2601 Gruppe</a></h4>
</div></div></div>
"""

CONTAINER = """
<a href="ilias.php?baseClass=ilstartupgui&amp;cmd=doLogout">Logout</a>
<div class="ilContainerListItemOuter" id="lg_div_200_pref_-1">
  <div class="ilContainerListItemIcon"><img alt="Ordner" src="icon_fold.svg" class="ilListItemIcon"></div>
  <h3 class="il_ContainerItemTitle"><a href="https://elearning.hslu.ch/ilias/goto.php/fold/200" class="il_ContainerItemTitle">Unterlagen OOP</a></h3>
</div>
<div class="ilContainerListItemOuter" id="lg_div_201_pref_-1">
  <div class="ilContainerListItemIcon"><img alt="Datei" src="icon_file.svg" class="ilListItemIcon"></div>
  <h3 class="il_ContainerItemTitle"><a href="https://elearning.hslu.ch/ilias/goto.php/file/201/download" class="il_ContainerItemTitle">SW01 Slides</a></h3>
  <div class="ilListItemSection il_ItemProperties">
    <span class="il_ItemProperty">pdf&nbsp;&nbsp;</span>
    <span class="il_ItemProperty">1,2 MB&nbsp;&nbsp;</span>
    <span class="il_ItemProperty">Version: 2&nbsp;&nbsp;</span>
    <span class="il_ItemProperty">12. Sep 2026, 16:44&nbsp;&nbsp;</span>
  </div>
</div>
<div class="ilContainerListItemOuter" id="lg_div_202_pref_-1">
  <div class="ilContainerListItemIcon"><img alt="Weblink" src="icon_webr.svg" class="ilListItemIcon"></div>
  <h3 class="il_ContainerItemTitle"><a href="https://elearning.hslu.ch/ilias/ilias.php?baseClass=ilLinkResourceHandlerGUI&amp;ref_id=202&amp;cmd=calldirectlink" class="il_ContainerItemTitle">Zoom</a></h3>
</div>
<div class="ilContainerListItemOuter" id="lg_div_201_pref_-2">
  <h3 class="il_ContainerItemTitle"><a href="https://elearning.hslu.ch/ilias/goto.php/file/201/download" class="il_ContainerItemTitle">SW01 Slides</a></h3>
</div>
"""


def test_dashboard():
    items = parser.parse_dashboard(DASHBOARD, BASE)
    assert [(i.type, i.ref_id, i.title) for i in items] == [
        ("crs", 100, "I.BA_PLAB.H2601"), ("grp", 101, "I.BA_PLAB.H2601 Gruppe")]
    assert items[0].description == "Programmier-Labor"
    assert items[0].properties == {"Anmeldung": "Keine"}


def test_container_types_and_dedup():
    items = parser.parse_container(CONTAINER, BASE)
    assert [(i.type, i.ref_id) for i in items] == [("fold", 200), ("file", 201), ("webr", 202)]
    f = items[1]
    assert f.is_file and parser.file_extension(f) == "pdf"
    assert f.properties["Version"] == "2"
    assert f.properties["_"] == "pdf 1,2 MB 12. Sep 2026, 16:44"


def test_login_detection():
    assert parser.is_logged_in(CONTAINER)
    assert not parser.is_logged_in("<form action='saml'>Login</form>")


@pytest.mark.parametrize("url,expected", [
    ("https://x/ilias/goto.php/crs/7206324", ("crs", 7206324)),
    ("https://x/ilias/goto.php?target=fold_123", ("fold", 123)),
    ("https://x/ilias/goto.php?target=file_55_download", ("file", 55)),
    ("https://x/ilias/ilias.php?baseClass=ilrepositorygui&cmd=sendfile&ref_id=9", ("file", 9)),
])
def test_classify_url(url, expected):
    assert parser.classify_url(url) == expected


def test_match_order_and_ambiguity():
    items = parser.parse_dashboard(DASHBOARD, BASE)
    m = client.Ilias._match
    assert m("i.ba_plab.h2601", items, []).ref_id == 100   # exact beats prefix
    assert m("101", items, []).ref_id == 101                 # ref id
    assert m("gruppe", items, []).ref_id == 101              # unique substring
    with pytest.raises(client.IliasError, match="ambiguous"):
        m("PLAB", items, [])


@pytest.mark.parametrize("raw,expected", [
    ("abc123", {"PHPSESSID": "abc123"}),
    ("Cookie: PHPSESSID=abc; ilClientId=hslu", {"PHPSESSID": "abc", "ilClientId": "hslu"}),
])
def test_cookie_input(raw, expected):
    assert client.parse_cookie_input(raw) == expected


def test_safe_name_blocks_traversal():
    assert "/" not in client.safe_name("../../etc/passwd")
    assert client.safe_name("..") == "unnamed"
    assert client.safe_name('a:b?"c') == "a_b__c"
