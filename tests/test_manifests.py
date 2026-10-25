"""Every addon's addon.json and hooks, checked against the contract (api 1) and each other."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ADDONS = sorted(p.parent for p in (REPO / "addons").glob("*/addon.json"))
PORTS = range(8770, 8800)


def _meta(addon: Path) -> dict:
    return json.loads((addon / "addon.json").read_text(encoding="utf-8-sig"))


@pytest.mark.parametrize("addon", ADDONS, ids=lambda p: p.name)
def test_the_manifest_speaks_api_1_under_its_folder_name(addon):
    meta = _meta(addon)
    assert meta["api"] == 1
    assert meta["name"] == addon.name
    assert meta["type"] in ("web", "service", "tool")
    for rel in meta.get("shared", []):
        assert (REPO / "shared" / rel).is_file(), rel


@pytest.mark.parametrize("addon", ADDONS, ids=lambda p: p.name)
def test_hooks_are_powershell_in_ascii_and_no_shell_script_is_left(addon):
    """Windows PowerShell 5.1 reads a BOM-less script as ANSI: ASCII reads the same either way."""
    for script in ("install.ps1", "uninstall.ps1"):
        (addon / script).read_text(encoding="ascii")
    assert not list(addon.glob("*.sh"))


def test_web_addons_have_distinct_ports_and_paths_in_the_addon_range():
    web = [_meta(a) for a in ADDONS if _meta(a)["type"] == "web"]
    ports = [m["port"] for m in web]
    paths = [m["path"] for m in web]
    assert all(p in PORTS for p in ports), ports
    assert len(set(ports)) == len(ports) and len(set(paths)) == len(paths)
    assert all(p.startswith("/") and not p.endswith("/") for p in paths)
