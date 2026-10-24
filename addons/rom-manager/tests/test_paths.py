"""Path resolution with two distinct roots — the whole point of api 1.

rom-manager is the only addon that *writes* the player's files, and what it
writes are ROMs. If it resolves `romsPath` under GAMECORE_PATH once the data
lives elsewhere, uploads land in a directory the core's scanner no longer
reads: the upload reports success and the game never appears.

GAMECORE_DATA defaults to GAMECORE_PATH (as in the core's paths.py), so a test
that lets them default cannot see the mistake. These tests therefore set two
genuinely different directories.

Run with:  python tests/test_paths.py     (needs the addon's requirements)
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
CODE = ROOT / "GameCore"          # the installation — read-only in production
DATA = ROOT / "userdata"          # the player's data — writable
(CODE / "config").mkdir(parents=True)
(DATA / "config").mkdir(parents=True)

os.environ["GAMECORE_PATH"] = str(CODE)
os.environ["GAMECORE_DATA"] = str(DATA)

sys.path.insert(0, str(Path(__file__).parent.parent))
import server  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


def under(path: Path, root: Path) -> bool:
    return root.resolve() in path.resolve().parents or path.resolve() == root.resolve()


print("Two distinct roots")
check("code and data really differ", CODE.resolve() != DATA.resolve(),
      "the rest of this file proves nothing otherwise")
check("systems.json read from DATA", under(server.SYSTEMS_FILE, DATA), str(server.SYSTEMS_FILE))
check("systems.json NOT under PATH", not under(server.SYSTEMS_FILE, CODE), str(server.SYSTEMS_FILE))

print("romsPath resolution")
rel = server.roms_path_of({"romsPath": "emu/duckstation"})
check("relative romsPath lands under DATA", under(rel, DATA), str(rel))
check("relative romsPath NOT under PATH", not under(rel, CODE), str(rel))
check("relative romsPath keeps its subpath", rel == DATA / "emu" / "duckstation", str(rel))

absolute = server.roms_path_of({"romsPath": "E:\\Roms\\psx"})
check("absolute romsPath left alone", absolute == Path("E:\\Roms\\psx"), str(absolute))

check("empty romsPath → None", server.roms_path_of({"romsPath": ""}) is None)
check("missing romsPath → None", server.roms_path_of({}) is None)

print("Fallback when only GAMECORE_PATH is set (a checkout)")
del os.environ["GAMECORE_DATA"]
importlib.reload(server)
check("DATA falls back to PATH", server.GAMECORE_DATA == CODE, str(server.GAMECORE_DATA))
check("systems.json back under PATH", under(server.SYSTEMS_FILE, CODE), str(server.SYSTEMS_FILE))
legacy = server.roms_path_of({"romsPath": "emu/duckstation"})
check("relative romsPath back under PATH", legacy == CODE / "emu" / "duckstation", str(legacy))

# An empty GAMECORE_DATA must not resolve every path to the cwd: `or`, not `get`.
os.environ["GAMECORE_DATA"] = ""
importlib.reload(server)
check("empty GAMECORE_DATA falls back too", server.GAMECORE_DATA == CODE, str(server.GAMECORE_DATA))

print("Upload names NTFS accepts")
# Only what Windows refuses changes: saves and playtime are keyed by the exact name.
cases = {
    "Zelda (USA) [!].z64": "Zelda (USA) [!].z64",
    "Mario: Odyssey?.nsp": "Mario_ Odyssey_.nsp",
    'a<b>c"d|e*f.iso': "a_b_c_d_e_f.iso",
    "..\\..\\evil.zip": "evil.zip",
    "../../evil.zip": "evil.zip",
    "CON.zip": "_CON.zip",
    "nul": "_nul",
    "Console.zip": "Console.zip",
    "game. ": "game",
    "Pokémon Émeraude.gba": "Pokémon Émeraude.gba",
    "": "unknown",
}
for raw, want in cases.items():
    got = server.safe_filename(raw)
    check(f"safe_filename({raw!r})", got == want, f"{got!r} != {want!r}")

print("cover proxy")
url = server.core_cover_url("gamecube", "Zelda #2: A/B?.iso")
check("asks the core's cover route", url.startswith(f"http://127.0.0.1:{server.CORE_PORT}/api/covers/gamecube/"), url)
check("the name stays one path segment", "/" not in url.rsplit("/covers/gamecube/", 1)[1]
      and "#" not in url and "?" not in url, url)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("All path tests passed.")
