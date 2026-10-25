"""Where RPCS3 for Windows keeps things, found from the player's systems.json.

RPCS3 on Windows is portable: one folder holds rpcs3.exe, dev_hdd0\\ and
patches\\, and its YAML files sit in config\\ (recent builds) or next to the
exe (older ones). The folder comes from the rpcs3 entry of systems.json, which
is the player's file and so is read from GAMECORE_DATA: a decoy under
GAMECORE_PATH fails the test if the addon reads the wrong root.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def roots(tmp_path, monkeypatch):
    code, data, rpcs3 = tmp_path / "GameCore", tmp_path / "data", tmp_path / "Emulators" / "RPCS3"
    for d in (code / "config", data / "config", rpcs3):
        d.mkdir(parents=True)
    (rpcs3 / "rpcs3.exe").write_bytes(b"MZ")
    (data / "config" / "systems.json").write_text(json.dumps(
        [{"id": "rpcs3", "path": str(rpcs3 / "rpcs3.exe")}]), encoding="utf-8")
    (code / "config" / "systems.json").write_text(json.dumps(
        [{"id": "rpcs3", "path": str(tmp_path / "decoy" / "rpcs3.exe")}]), encoding="utf-8")
    monkeypatch.setenv("GAMECORE_PATH", str(code))
    monkeypatch.setenv("GAMECORE_DATA", str(data))
    for var in ("RPCS3_DIR", "RPCS3_BIN"):
        monkeypatch.delenv(var, raising=False)
    import server
    importlib.reload(server)
    return server, code, data, rpcs3


def test_the_folder_comes_from_the_data_roots_systems_json(roots):
    server, _, _, rpcs3 = roots
    assert server.find_rpcs3() == rpcs3
    assert server.rpcs3_cmd() == [str(rpcs3 / "rpcs3.exe")]


def test_yaml_files_are_in_config_when_the_build_keeps_them_there(roots):
    server, _, _, rpcs3 = roots
    assert server.config_dir() == rpcs3, "an older build keeps config.yml next to the exe"
    (rpcs3 / "config").mkdir()
    (rpcs3 / "config" / "config.yml").write_text("Core: {}\n", encoding="utf-8")
    assert server.config_dir() == rpcs3 / "config"
    assert server.rpcs3_dir() == rpcs3, "dev_hdd0 and patches stay next to the exe"


def test_rpcs3_dir_overrides_systems_json(roots, monkeypatch, tmp_path):
    server, *_ = roots
    other = tmp_path / "portable"
    other.mkdir()
    monkeypatch.setenv("RPCS3_DIR", str(other))
    assert server.rpcs3_dir() == other


def test_a_pc_without_rpcs3_answers_503_and_a_health_that_says_so(roots):
    server, _, data, _ = roots
    (data / "config" / "systems.json").write_text("[]", encoding="utf-8")
    with pytest.raises(HTTPException) as e:
        server.rpcs3_dir()
    assert e.value.status_code == 503
    assert server.health()["exists"] is False
    assert server.rpcs3_cmd() is None


def test_a_relative_folder_is_relative_to_the_data_root(roots):
    server, _, data, _ = roots
    (data / "config" / "systems.json").write_text(json.dumps(
        [{"id": "rpcs3", "path": "emu\\rpcs3\\rpcs3.exe"}]), encoding="utf-8")
    assert server.find_rpcs3() == data / "emu" / "rpcs3"


def test_without_gamecore_data_the_data_root_is_the_code_root(roots, monkeypatch):
    server, code, _, _ = roots
    monkeypatch.delenv("GAMECORE_DATA")
    importlib.reload(server)
    assert server.GAMECORE_DATA == code
    monkeypatch.setenv("GAMECORE_DATA", "")
    importlib.reload(server)
    assert server.GAMECORE_DATA == code
