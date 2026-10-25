r"""GameCore addon — ROM Manager.

Browser drag & drop ROM uploads, per system. Extracted from the core's
backend/routers/roms.py: same endpoints, same UX, own port. Reads the
systems catalogue from $GAMECORE_DATA/config/systems.json and writes ROMs
under $GAMECORE_DATA; after an upload it notifies the core
(POST /api/addons/notify → WebSocket rom_uploaded) so the TV UI refreshes.

Two roots, mirroring the core's backend/services/paths.py:

  GAMECORE_PATH  the installation — code shipped by the release, read-only.
  GAMECORE_DATA  the player's data — systems.json and the ROMs themselves.

This addon touches only the data side. Every path it resolves is something
the player owns, so nothing here may be joined onto GAMECORE_PATH: an update
replaces that root wholesale, and the console user cannot write there.

Bezels are not managed here: the Windows edition has no overlay window.
"""
import fnmatch
import json
import logging
import os
import re
import shutil
from urllib.parse import quote
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

ADDON_DIR = Path(__file__).parent
GAMECORE_PATH = Path(os.environ.get("GAMECORE_PATH", r"C:\Program Files\GameCore"))
# The CLI always passes both; the fallback is the core's own default (paths.py).
GAMECORE_DATA = Path(os.environ.get("GAMECORE_DATA") or GAMECORE_PATH)
SYSTEMS_FILE = GAMECORE_DATA / "config" / "systems.json"
PORT = int(os.environ.get("ADDON_PORT", 8770))
CORE_PORT = int(os.environ.get("GAMECORE_BACKEND_PORT", 8765))
CORE_NOTIFY = f"http://127.0.0.1:{CORE_PORT}/api/addons/notify"

log = logging.getLogger("rom-manager")

app = FastAPI(title="GameCore addon — ROM Manager", root_path=os.environ.get("ADDON_BASE", ""))


# ── helpers (mirrored from the core so the addon stays self-contained) ────────

def fmt_size(n: float) -> str:
    # 1024-based, labelled so (KiB, not KB) — the deliberate mirror of the
    # core's backend/utils.fmt_size, moved in step with it.
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if x < 1024:
            return f"{x:.1f} {unit}" if unit != "B" else f"{int(x)} B"
        x /= 1024
    return f"{x:.1f} TiB"


TAG_RE = re.compile(r"[\(\[].*?[\)\]]")  # same rule as the core's backend/utils.py


def clean_name(filename: str) -> str:
    """Strip extension and bracketed tags (e.g. '[!]', '(Europe)') for display —
    mirrors the core's rom_scanner.clean_name so both UIs show the same title."""
    return " ".join(TAG_RE.sub("", Path(filename).stem).split()) or filename


def matches_ext(filename: str, extensions: list[str]) -> bool:
    name = filename.lower()
    return any(fnmatch.fnmatch(name, p.lower()) for p in extensions)


def iter_rom_files(roms_path: Path, extensions: list[str], scan_dirs: bool = False):
    """Yield ROM entries. Most systems = files matching `extensions`; systems
    with scanDirs (PS3 disc games…) = folders. Mirrors the core rom_scanner."""
    if not roms_path.exists():
        return
    for f in sorted(roms_path.iterdir(), key=lambda x: x.name.lower()):
        if f.name.startswith(".") or "example" in f.name.lower():
            continue
        if scan_dirs:
            if f.is_dir():
                yield f
        else:
            if not f.is_file():
                continue
            if extensions and not matches_ext(f.name, extensions):
                continue
            yield f


def entry_size(p: Path) -> int:
    """File size, or the recursive size of a game folder."""
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size


# Characters NTFS refuses in a name, and the device names Windows reserves
# whatever the extension ("CON.zip" opens the console, not a file).
_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(filename: str) -> str:
    """A name NTFS accepts, as close to the upload as possible.

    Only what Windows refuses is replaced (by `_`), so a ROM keeps the exact
    name its saves and playtime are keyed by. Trailing dots and spaces go:
    Windows drops them silently and the file would not be found again.
    """
    filename = re.split(r"[/\\]", filename)[-1]
    filename = _FORBIDDEN_CHARS.sub("_", filename).strip(". ")
    if filename.split(".", 1)[0].upper() in _RESERVED_NAMES:
        filename = "_" + filename
    return filename or "unknown"


def systems() -> list[dict]:
    try:
        return json.loads(SYSTEMS_FILE.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise HTTPException(503, f"systems.json unreadable: {e}")


def get_system(system_id: str) -> dict:
    s = next((x for x in systems() if x["id"].lower() == system_id.lower()), None)
    if not s:
        raise HTTPException(404, "System not found")
    return s


def roms_path_of(system: dict) -> Path | None:
    raw = system.get("romsPath", "")
    if not raw:
        return None
    p = Path(raw)
    # `romsPath` is relative in systems.json ("emu/duckstation/"), and this is
    # the one place that decides what it is relative TO. It is the DATA root:
    # same call the core makes in paths.resolve_data_path(). Resolving it under
    # GAMECORE_PATH would drop uploads into the installation, which the
    # scanner never reads: the player would upload into nothing, with no
    # error to show for it.
    return p if p.is_absolute() else GAMECORE_DATA / p


async def notify_core(event: str, data: dict) -> None:
    """Best effort — an unreachable core must never fail an upload."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(CORE_NOTIFY, json={"event": event, "data": data})
    except Exception as e:
        log.warning("core notify failed: %s", e)


# ── API (same shape as the former core endpoints) ─────────────────────────────

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/emulators")
def list_emulators():
    result = []
    for s in systems():
        if s.get("type") != "emulator":
            continue
        roms_path = roms_path_of(s)
        extensions = s.get("extensions", [])
        scan_dirs = s.get("scanDirs", False)
        rom_count = 0
        total_size = 0
        if roms_path and roms_path.exists():
            for f in iter_rom_files(roms_path, extensions, scan_dirs):
                rom_count += 1
                total_size += entry_size(f)
        result.append({
            "id":         s["id"],
            "platform":   s.get("label", s["id"]),
            "iconPath":   s.get("iconPath", ""),
            "color":      s.get("color", "#5c7cfa"),
            "type":       "emulator",
            "extensions": extensions,
            "scanDirs":   scan_dirs,
            "romCount":   rom_count,
            "totalSize":  fmt_size(total_size) if total_size else None,
        })
    return result


def core_cover_url(system_id: str, name: str) -> str:
    """The core's own cover route for this ROM: it finds, scrapes and caches."""
    return f"http://127.0.0.1:{CORE_PORT}/api/covers/{quote(system_id, safe='')}/{quote(name, safe='')}"


@app.get("/api/roms/{system_id}/cover")
async def rom_cover(system_id: str, name: str):
    """The box art the core shows, asked from the core itself.

    The core names its cache files in its own way (everything after the last
    dot of a title is dropped) and fetches a missing cover on first request;
    reading emu/covers here missed both. Its /api is not exposed to the LAN,
    so the browser cannot ask it directly.
    """
    system = get_system(system_id)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(core_cover_url(system["id"], name))
    except httpx.RequestError:
        raise HTTPException(503, "The GameCore backend is not answering")
    if r.status_code != 200:
        raise HTTPException(404)
    return Response(content=r.content, media_type=r.headers.get("content-type"),
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/api/roms/{system_id}")
def list_roms(system_id: str):
    system = get_system(system_id)
    roms_path = roms_path_of(system)
    if not roms_path or not roms_path.exists():
        return []
    files = []
    for f in iter_rom_files(roms_path, system.get("extensions", []), system.get("scanDirs", False)):
        size = entry_size(f)
        files.append({
            "name":        f.name,
            "displayName": clean_name(f.name),
            "size":        size,
            "sizeHuman":   fmt_size(size),
            "ext":         "DISC" if f.is_dir() else f.suffix.lstrip(".").upper(),
        })
    return files


@app.post("/api/roms/{system_id}/upload")
async def upload_rom(system_id: str, file: UploadFile = File(...)):
    system = get_system(system_id)
    if system.get("scanDirs"):
        raise HTTPException(400, "This system stores games as folders (disc games). "
                                 "Drop the whole game folder instead — single-file "
                                 "upload does not apply here.")
    roms_path = roms_path_of(system)
    if not roms_path:
        raise HTTPException(400, "No ROM path configured")

    filename = safe_filename(file.filename or "")
    if not filename:
        raise HTTPException(400, "Invalid filename")

    exts = system.get("extensions", [])
    if exts and not matches_ext(filename, exts):
        raise HTTPException(415, f"Extension not allowed. Accepted: {', '.join(exts)}")

    roms_path.mkdir(parents=True, exist_ok=True)
    dest = roms_path / filename

    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1 << 20)  # 1 MB chunks — avoids loading large ROMs into RAM
            if not chunk:
                break
            out.write(chunk)
            size += len(chunk)

    await notify_core("rom_uploaded", {"system_id": system_id, "filename": filename})
    return {"name": filename, "size": size, "sizeHuman": fmt_size(size)}


def safe_relpath(relpath: str) -> list[str]:
    """Sanitize a client-supplied path inside a game folder into safe
    components. Rejects traversal; needs at least <game folder>/<file>."""
    parts = [p for p in re.split(r"[/\\]+", relpath) if p not in ("", ".", "..")]
    parts = [safe_filename(p) for p in parts]
    if len(parts) < 2:
        raise HTTPException(400, "relpath must be <game folder>/…/<file>")
    return parts


@app.post("/api/roms/{system_id}/upload-entry")
async def upload_folder_entry(system_id: str, file: UploadFile = File(...),
                              relpath: str = Form(...), last: str = Form("0")):
    """One file of a disc-game folder (PS3…), at its relative path inside the
    game. The frontend traverses the dropped folder and posts every file here,
    flagging the final one with last=1 so the core is notified once."""
    system = get_system(system_id)
    if not system.get("scanDirs"):
        raise HTTPException(400, "This system takes single-file ROMs — use the regular upload")
    roms_path = roms_path_of(system)
    if not roms_path:
        raise HTTPException(400, "No ROM path configured")

    parts = safe_relpath(relpath)
    dest = roms_path.joinpath(*parts)
    roms_path.mkdir(parents=True, exist_ok=True)
    try:
        dest.resolve().relative_to(roms_path.resolve())
    except ValueError:
        raise HTTPException(403, "path escapes the ROMs directory")

    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
            size += len(chunk)

    if last == "1":
        await notify_core("rom_uploaded", {"system_id": system_id, "filename": parts[0]})
    return {"name": "/".join(parts), "size": size, "sizeHuman": fmt_size(size)}


@app.delete("/api/roms/{system_id}/{filename}")
async def delete_rom(system_id: str, filename: str):
    system = get_system(system_id)
    roms_path = roms_path_of(system)
    if not roms_path:
        raise HTTPException(404)

    safe = safe_filename(filename)
    target = roms_path / safe
    try:
        target.resolve().relative_to(roms_path.resolve())
    except ValueError:
        raise HTTPException(403)

    if target.is_dir() and system.get("scanDirs"):
        shutil.rmtree(target)          # disc-game folder
    elif target.is_file():
        target.unlink()
    else:
        raise HTTPException(404)
    # keep the TV UI in sync after a deletion too (same event family as upload)
    await notify_core("rom_deleted", {"system_id": system_id, "filename": safe})
    return {"ok": True}


class _FreshStatic(StaticFiles):
    """The addon's page, never served from the browser's cache.

    `web/index.html` is a single file that changes with every addon update,
    and it was served with no Cache-Control at all — so the browser applied
    its heuristic freshness and kept the OLD page for a while after
    `gamecore-addon update`: the new page was on disk and on the wire, the
    browser just never asked.
    Same rule the core applies to its theme files (`_NoCacheStatic`): small,
    local, and a stale copy costs more than a fetch.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp


app.mount("/", _FreshStatic(directory=str(ADDON_DIR / "web"), html=True), name="web")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
