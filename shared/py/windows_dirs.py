"""The Windows folders emulators keep their files in, for the addons that look there.

Copied next to an addon by install.ps1 (listed under `shared` in its
addon.json), never imported across the tree. The task runs as the console
user, so these are that user's folders. GAMECORE_HOME, when set, stands for
the user profile and moves every folder below it: the tests point it at a
temp folder so nothing reaches the real profile.
"""
import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

# FOLDERID_Documents: Documents can be moved (OneDrive, another drive), so the
# shell is asked rather than USERPROFILE\Documents assumed.
_FOLDERID_DOCUMENTS = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")


def _sandbox() -> Path | None:
    value = os.environ.get("GAMECORE_HOME")
    return Path(value) if value else None


def home() -> Path:
    return _sandbox() or Path.home()


def appdata() -> Path:
    """%APPDATA% (Roaming): where most emulators keep their user folder."""
    box = _sandbox()
    if box:
        return box / "AppData" / "Roaming"
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def local_appdata() -> Path:
    box = _sandbox()
    if box:
        return box / "AppData" / "Local"
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def documents() -> Path:
    box = _sandbox()
    if box:
        return box / "Documents"
    return _known_folder(_FOLDERID_DOCUMENTS) or Path.home() / "Documents"


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]


def _known_folder(folder_id: uuid.UUID) -> Path | None:
    try:
        shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32
    except AttributeError:      # not Windows
        return None
    guid = _GUID((ctypes.c_ubyte * 16)(*folder_id.bytes_le))
    out = wintypes.LPWSTR()
    if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return Path(out.value)
    finally:
        ole32.CoTaskMemFree(out)


def first_existing(*candidates: Path) -> Path:
    """The first candidate folder that exists, else the first: where a fresh install puts it."""
    return next((c for c in candidates if c.exists()), candidates[0])


def exe_dir(system: dict) -> Path | None:
    """The folder of the emulator a systems.json entry declares, when it names an absolute .exe."""
    path = Path(str(system.get("path") or ""))
    return path.parent if path.is_absolute() and path.suffix.lower() == ".exe" else None
