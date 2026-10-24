"""The API against a portable RPCS3 folder laid out as on Windows."""
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ADDON = Path(__file__).parent.parent
sys.path.insert(0, str(ADDON))

GLOBAL = "Core:\n  PPU Decoder: Recompiler (LLVM)\nVideo:\n  Aspect ratio: \"16:9\"\n"


@pytest.fixture
def rpcs3(tmp_path, monkeypatch):
    folder = tmp_path / "RPCS3"
    cfg = folder / "config"
    disc = tmp_path / "games" / "Demo Game"
    for d in (cfg, folder / "dev_hdd0" / "game" / "BLES00001", folder / "patches", disc / "PS3_GAME"):
        d.mkdir(parents=True)
    (folder / "rpcs3.exe").write_bytes(b"MZ")
    (cfg / "config.yml").write_bytes(GLOBAL.encode())
    (cfg / "games.yml").write_bytes(f"BLUS00002: {disc.as_posix()}/\n".encode())
    monkeypatch.setenv("RPCS3_DIR", str(folder))
    monkeypatch.setenv("GAMECORE_DATA", str(tmp_path / "data"))
    import server
    importlib.reload(server)
    return TestClient(server.app), folder


def test_games_come_from_games_yml(rpcs3):
    client, _ = rpcs3
    games = client.get("/api/games").json()
    assert [(g["serial"], g["source"], g["missing"]) for g in games] == [("BLUS00002", "disc", False)]


def test_a_custom_config_is_made_from_the_global_one_and_keeps_lf(rpcs3):
    client, folder = rpcs3
    r = client.put("/api/games/BLUS00002/config", json={"values": {}})
    assert r.status_code == 200 and r.json()["created"]
    raw = (folder / "config" / "custom_configs" / "config_BLUS00002.yml").read_bytes()
    assert b"\r" not in raw, "RPCS3's files stay LF on Windows"
    assert b'Aspect ratio: "16:9"' in raw


def test_removing_a_game_rewrites_games_yml_in_lf_with_a_backup(rpcs3):
    client, folder = rpcs3
    assert client.delete("/api/games/BLUS00002").json()["removed_entry"]
    assert (folder / "config" / "games.yml").read_bytes() == b""
    assert list((folder / "config").glob("games.yml.bak-*"))


def test_patches_are_written_next_to_the_exe(rpcs3):
    client, folder = rpcs3
    patch = ("Version: 1.2\nPPU-0123:\n  Fix:\n    Games:\n      Demo:\n        BLUS00002: [ 01.00 ]\n"
             "    Author: x\n    Patch Version: 1.0\n    Patch:\n      - [ be32, 0x10, 0x60000000 ]\n")
    r = client.post("/api/patches/upload", files={"file": ("p.yml", patch.encode())})
    assert r.status_code == 200, r.text
    assert b"\r" not in (folder / "patches" / "imported_patch.yml").read_bytes()


def test_health_names_the_folder(rpcs3):
    client, folder = rpcs3
    body = client.get("/api/health").json()
    assert body["exists"] and body["rpcs3_dir"] == str(folder)
    assert body["config_dir"] == str(folder / "config")


def test_a_pkg_without_rpcs3_is_refused_before_the_upload_is_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("RPCS3_DIR", str(tmp_path / "missing"))
    import server
    importlib.reload(server)
    r = TestClient(server.app).post("/api/pkg/install", files={"file": ("u.pkg", b"x")})
    assert r.status_code == 503
    assert json.loads(r.text)["detail"] == server.NOT_INSTALLED
