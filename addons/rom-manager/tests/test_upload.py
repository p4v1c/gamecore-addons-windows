"""Uploads and deletes through the API, on NTFS, with two distinct roots.

The core is pointed at a port nothing listens on: its notification is best
effort, and an upload must succeed without it.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def api(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "config").mkdir(parents=True)
    (data / "config" / "systems.json").write_text(json.dumps([
        {"id": "switch", "type": "emulator", "label": "Switch", "romsPath": "emu/switch",
         "extensions": ["*.nsp", "*.xci"]},
        {"id": "ps3", "type": "emulator", "label": "PS3", "romsPath": "emu/ps3", "scanDirs": True},
    ]), encoding="utf-8")
    monkeypatch.setenv("GAMECORE_PATH", str(tmp_path / "code"))
    monkeypatch.setenv("GAMECORE_DATA", str(data))
    monkeypatch.setenv("GAMECORE_BACKEND_PORT", "9")
    import server
    importlib.reload(server)
    return TestClient(server.app), data


def test_a_name_ntfs_refuses_is_stored_under_a_name_it_accepts(api):
    client, data = api
    r = client.post("/api/roms/switch/upload", files={"file": ("Mario: Odyssey?.nsp", b"rom")})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Mario_ Odyssey_.nsp"
    assert (data / "emu" / "switch" / "Mario_ Odyssey_.nsp").read_bytes() == b"rom"
    assert [f["name"] for f in client.get("/api/roms/switch").json()] == ["Mario_ Odyssey_.nsp"]


def test_a_reserved_device_name_does_not_open_the_device(api):
    client, data = api
    r = client.post("/api/roms/switch/upload", files={"file": ("CON.nsp", b"rom")})
    assert r.status_code == 200
    assert (data / "emu" / "switch" / "_CON.nsp").read_bytes() == b"rom"


def test_a_folder_entry_with_backslashes_stays_inside_the_roms_folder(api):
    client, data = api
    r = client.post("/api/roms/ps3/upload-entry", files={"file": ("EBOOT.BIN", b"x")},
                    data={"relpath": "..\\..\\BLES0001\\PS3_GAME\\USRDIR\\EBOOT.BIN", "last": "1"})
    assert r.status_code == 200, r.text
    assert (data / "emu" / "ps3" / "BLES0001" / "PS3_GAME" / "USRDIR" / "EBOOT.BIN").exists()
    assert not (data / "BLES0001").exists()


def test_delete_removes_the_file_and_refuses_what_is_not_there(api):
    client, data = api
    client.post("/api/roms/switch/upload", files={"file": ("game.xci", b"rom")})
    assert client.delete("/api/roms/switch/game.xci").status_code == 200
    assert not (data / "emu" / "switch" / "game.xci").exists()
    assert client.delete("/api/roms/switch/game.xci").status_code == 404


def test_an_extension_the_system_does_not_take_is_refused(api):
    client, _ = api
    assert client.post("/api/roms/switch/upload", files={"file": ("x.iso", b"")}).status_code == 415


def test_nothing_is_written_under_the_installation(api, tmp_path):
    client, _ = api
    client.post("/api/roms/switch/upload", files={"file": ("game.nsp", b"rom")})
    assert not (tmp_path / "code").exists()
