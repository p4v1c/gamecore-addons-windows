"""The two roots as catalog.py resolves them, including the pre-P3 fallback.

tests/test_api.py drives the whole API with the roots already split; this file
covers what it cannot, because the roots are read at import: the fallback that
keeps a box which has not taken the P3 OTA working unchanged.

Run with:  python tests/test_paths.py
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_TMP = tempfile.TemporaryDirectory()
ROOT = Path(_TMP.name)
CODE = ROOT / "GameCore"
DATA = ROOT / "userdata"
HOME = ROOT / "home"
for d in (CODE, DATA, HOME):
    d.mkdir(parents=True)

os.environ["GAMECORE_HOME"] = str(HOME)
os.environ["GAMECORE_PATH"] = str(CODE)
os.environ["GAMECORE_DATA"] = str(DATA)

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared" / "py"))
import catalog  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


print("Roots apart")
check("roots really differ", CODE.resolve() != DATA.resolve(),
      "the rest of this file proves nothing otherwise")
check("GAMECORE_DATA honoured", catalog.GC_DATA == DATA, str(catalog.GC_DATA))
check("covers under DATA", catalog.COVERS == DATA / "emu" / "covers", str(catalog.COVERS))
check("covers NOT under PATH", CODE.resolve() not in catalog.COVERS.resolve().parents,
      str(catalog.COVERS))
check("roms under DATA", catalog.ROMS == DATA / "emu", str(catalog.ROMS))
check("mgba base under DATA", catalog.CATALOG["mgba"]["bases"][0] == DATA / "emu/mgba",
      str(catalog.CATALOG["mgba"]["bases"][0]))
check("gba base under DATA", catalog.CATALOG["gba"]["bases"][0] == DATA / "emu/gba",
      str(catalog.CATALOG["gba"]["bases"][0]))
check("melonds base under DATA", catalog.CATALOG["melonds"]["bases"][0] == DATA / "emu/melonds",
      str(catalog.CATALOG["melonds"]["bases"][0]))
check("nothing scanned under PATH", all(CODE not in b.parents for e in catalog.CATALOG
                                        for b in catalog.bases(e)))

print("Portable installs, found from the exe systems.json declares")
import json  # noqa: E402
EMU = ROOT / "Emulators"
(EMU / "Dolphin").mkdir(parents=True)
(DATA / "config").mkdir()
(DATA / "config" / "systems.json").write_text(json.dumps([
    {"id": "gamecube", "path": str(EMU / "Dolphin" / "Dolphin.exe")},
    {"id": "rpcs3", "path": str(EMU / "RPCS3" / "rpcs3.exe")},
    {"id": "pcsx2", "path": "emu\pcsx2\pcsx2-qt.exe"},
]), encoding="utf-8")
check("no portable.txt: Dolphin's user folder only",
      catalog.portable_bases("dolphin") == [], str(catalog.portable_bases("dolphin")))
(EMU / "Dolphin" / "portable.txt").write_text("")
check("portable.txt: User next to Dolphin.exe first",
      catalog.bases("dolphin")[0] == EMU / "Dolphin" / "User", str(catalog.bases("dolphin")))
check("rpcs3 has its exe's folder only", catalog.bases("rpcs3") == [EMU / "RPCS3"],
      str(catalog.bases("rpcs3")))
check("a relative exe path is not a portable install", catalog.portable_bases("pcsx2") == [])
check("Documents moved by the sandbox", catalog.CATALOG["pcsx2"]["bases"] == [HOME / "Documents" / "PCSX2"],
      str(catalog.CATALOG["pcsx2"]["bases"]))

print("Fallback when only GAMECORE_PATH is set (a checkout)")
del os.environ["GAMECORE_DATA"]
importlib.reload(catalog)
check("DATA falls back to PATH", catalog.GC_DATA == CODE, str(catalog.GC_DATA))
check("covers back under PATH", catalog.COVERS == CODE / "emu" / "covers", str(catalog.COVERS))
check("roms back under PATH", catalog.ROMS == CODE / "emu", str(catalog.ROMS))

# An empty GAMECORE_DATA must not resolve every path to the cwd: `or`, not `get`.
os.environ["GAMECORE_DATA"] = ""
importlib.reload(catalog)
check("empty GAMECORE_DATA falls back too", catalog.GC_DATA == CODE, str(catalog.GC_DATA))

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("All path tests passed.")
