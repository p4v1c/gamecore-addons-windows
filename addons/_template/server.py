r"""Template addon: a minimal FastAPI service serving a static web UI.

Runs from the repo checkout, started by its scheduled task through
addon-run.py, which puts ADDON_PORT, ADDON_BASE and the two GameCore roots in
the environment (from ADDON_DATA_DIR\addon.env). Keep addons buildless
(plain static web/) so the checkout is exactly what runs.

── Where you may write (api 1) ───────────────────────────────────────────────

GameCore separates code from data, and an addon must know which is which:

  GAMECORE_PATH   the installation (C:\Program Files\GameCore). Code shipped by
                  the release. READ ONLY: every update replaces it wholesale,
                  and the console user cannot write there anyway.
  GAMECORE_DATA   everything the player owns: config\systems.json, the ROMs
                  under emu\, covers, saves. Read and write freely.
  ADDON_DATA_DIR  your own writable corner (GAMECORE_DATA\addons\<name>),
                  created for you before install.ps1 runs. Put your caches,
                  indexes and state here, never under GAMECORE_PATH.

The question to ask for each path you touch, one at a time:

    Can the player modify this file, or does it arrive with the release?

Data goes under GAMECORE_DATA, code under GAMECORE_PATH. If you are unsure,
the core's backend/services/paths.py has already decided.

Declare `"api": 1` in addon.json only once this is true of your addon: the
manager refuses an addon without it. It is a statement of conformance, not a
switch.
"""
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

ADDON_DIR = Path(__file__).parent
GAMECORE_PATH = Path(os.environ.get("GAMECORE_PATH", r"C:\Program Files\GameCore"))
# The CLI always passes both; the fallback is the core's own default (paths.py),
# which only a checkout ever uses.
GAMECORE_DATA = Path(os.environ.get("GAMECORE_DATA") or GAMECORE_PATH)
# Your own state goes here, never under GAMECORE_PATH.
ADDON_DATA_DIR = Path(os.environ.get("ADDON_DATA_DIR")
                      or GAMECORE_DATA / "addons" / ADDON_DIR.name)
PORT = int(os.environ.get("ADDON_PORT", 8799))

app = FastAPI(title="GameCore addon — template", root_path=os.environ.get("ADDON_BASE", ""))

# The core UI and sibling addons live on other ports of the same host.


@app.get("/api/health")
def health():
    return {"ok": True}



class _FreshStatic(StaticFiles):
    """The addon's page, never served from the browser's cache.

    `web/index.html` is a single file that changes with every addon update,
    and it was served with no Cache-Control at all — so the browser applied
    its heuristic freshness and kept the OLD page for a while after
    `gamecore-addon update`. On the reference box that meant a ROM Manager
    that still showed one overlay slot per system the evening the core had
    grown one per console, and "No overlay set" for a file that was there:
    the new page was on disk and on the wire, the browser just never asked.
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
