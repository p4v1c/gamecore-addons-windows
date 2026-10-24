"""shared/py/windows_dirs.py: the user folders emulators keep their files in."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "shared" / "py"))

import windows_dirs  # noqa: E402


def test_the_sandbox_moves_every_folder_under_it(monkeypatch, tmp_path):
    monkeypatch.setenv("GAMECORE_HOME", str(tmp_path))
    assert windows_dirs.home() == tmp_path
    assert windows_dirs.appdata() == tmp_path / "AppData" / "Roaming"
    assert windows_dirs.local_appdata() == tmp_path / "AppData" / "Local"
    assert windows_dirs.documents() == tmp_path / "Documents"


@pytest.mark.skipif(sys.platform != "win32", reason="asks the Windows shell")
def test_documents_comes_from_the_shell_and_exists(monkeypatch):
    """Read only: the real profile's Documents, wherever OneDrive or a policy moved it."""
    monkeypatch.delenv("GAMECORE_HOME", raising=False)
    docs = windows_dirs.documents()
    assert docs.is_absolute() and docs.is_dir()


def test_first_existing_falls_back_to_the_fresh_install_folder(tmp_path):
    new, old = tmp_path / "new", tmp_path / "old"
    assert windows_dirs.first_existing(new, old) == new
    old.mkdir()
    assert windows_dirs.first_existing(new, old) == old


@pytest.mark.parametrize("path,want", [
    ("C:\\Emulators\\Dolphin\\Dolphin.exe", Path("C:\\Emulators\\Dolphin")),
    ("C:\\Emulators\\Dolphin\\DOLPHIN.EXE", Path("C:\\Emulators\\Dolphin")),
    ("emu\\dolphin\\Dolphin.exe", None),
    ("C:\\Emulators\\Dolphin", None),
    ("", None),
])
def test_exe_dir_needs_an_absolute_exe(path, want):
    assert windows_dirs.exe_dir({"path": path}) == want
