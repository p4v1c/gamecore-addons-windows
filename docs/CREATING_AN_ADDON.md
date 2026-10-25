# Creating a GameCore addon

Copy `addons/_template/` to `addons/<your-name>/` and adapt. Directories whose
name starts with `_` are ignored by the manager.

## Layout

```
addons/<name>/
  addon.json      metadata — the only file the manager reads
  install.ps1     idempotent setup: dot-sources shared\windows\addon-hooks.ps1, calls Install-GcAddon
  uninstall.ps1   calls Uninstall-GcAddon: stops and unregisters the task
  server.py       your service (python, node, anything)
  web/            static UI (web addons)
  requirements.txt
```

## addon.json

```json
{
  "api": 1,                       // REQUIRED — "this addon writes to GAMECORE_DATA,
                                  // never to GAMECORE_PATH". install/update refuse
                                  // an addon without it. Add it last (see Rules).
  "name": "rom-manager",          // = directory name, [a-z0-9-]
  "label": "ROM Manager",         // shown in nav + Addons screen
  "description": "…",
  "version": "1.0.0",             // bump on every change; `update` re-runs install.ps1
  "type": "web",                  // web | service | tool
  "default": true,                // pre-checked in the GameCore installer
  "service": "user",              // runs as the console user, from a logon task
  "port": 8770,                   // web only — pick a free one in 8770-8799 (loopback only);
                                  // install.ps1 reads it from here, nowhere else
  "path": "/roms",                // web only — URL prefix behind the Caddy proxy; needs a
                                  // matching route in the core's install/system/Caddyfile
  "offline_assets": [],           // files the offline payload must provide when OFFLINE=1
  "shared": ["py/sfo.py"]         // shared/ files copied next to server.py (optional)
}
```

## install.ps1 / uninstall.ps1 contract

The manager runs them with Windows PowerShell 5.1
(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File`), elevated, with
these variables in the environment. Keep the files ASCII: 5.1 reads a
BOM-less script as ANSI.

| var | meaning |
|-----|---------|
| `USER_NAME`     | the console user (`DOMAIN\user`) the task runs as |
| `GAMECORE_PATH` | core install dir (`C:\Program Files\GameCore`) — **read only** |
| `GAMECORE_DATA` | player data dir, chosen at install — writable |
| `ADDON_DATA_DIR` | your writable corner, `$GAMECORE_DATA/addons/<name>`, created before this script runs |
| `GAMECORE_ADDON_API` | api version the manager speaks (`1`) |
| `GAMECORE_BACKEND_PORT` | core API port (default `8765`); `addon.env` passes it to the server |
| `GAMECORE_ADDON_PYTHON` | the interpreter to build the venv on (install only; a copy in the data root) |
| `ADDON_DIR`     | this addon's directory in the checkout (= runtime dir) |
| `OFFLINE`       | `1` when installing without network |
| `PAYLOAD_DIR`   | offline assets dir (when `OFFLINE=1`) |

Rules:

- **Write to `$GAMECORE_DATA` / `$ADDON_DATA_DIR`, never to `$GAMECORE_PATH`.**
  Every GameCore update replaces the install root wholesale, and the console
  user cannot write there. See the code/data section in the repo README for
  how to tell a data path from a code path. `Install-GcAddon` writes both roots
  into `addon.env`; extra variables go through `Install-GcAddon -Extra @{...}`.
- **Declare `"api": 1` in `addon.json`** once the above is true of your addon.
  Without it, `gamecore-addon install` and `update` refuse it by name. Add it
  last, after the paths are right: it states conformance, it does not grant it.
- **Idempotent** — `update` runs `uninstall.ps1` on the old checkout, then
  `install.ps1` on the new one.
- **Never touch the registry** (`$GAMECORE_DATA/config/addons.json`) — the manager owns it.
- **No network when `OFFLINE=1`** — ship everything in the repo or declare it
  in `offline_assets` (provided under `PAYLOAD_DIR`).
- Task name convention: `\GameCore\Addons\<name>` (`Install-GcAddon` does
  it). Logs go to `<DATA>\logs\addons\<name>.log`.
- Buildless by design: plain static `web/`, no npm build step, so the checkout
  is exactly what runs.

## Security model (docs/SECURITY.md)

The LAN reaches everything through the Caddy reverse-proxy on ONE origin
(`https://box:8443`), which enforces the shared login. Consequences for
addons:

- **Bind loopback only**: `uvicorn.run(app, host="127.0.0.1", port=PORT)`.
- **No CORS middleware** — everything is same-origin behind the proxy.
- **No auth code** — Caddy logs the user in before your addon sees the
  request; you only receive the `X-GC-User` header.
- **Path prefix**: `addon.env` gives your server `ADDON_BASE=<addon.json path>`
  and `server.py` passes it as FastAPI's `root_path`. Add a `handle` route
  for it to the core's `install/system/Caddyfile`.
- **Relative client URLs only**: the page is served at `/yourprefix/`, so
  `fetch('api/…')`, `src="api/…"` — never `/api/…`, never a host or port.
  Root-absolute is allowed only for core statics that Caddy routes for you
  (`/assets/…`, `/covers/…`).

## The shared nav (web addons)

`install.ps1` copies `shared/nav/gamecore-nav.{js,css}` into your `web/` and your
page includes them (see the template's `index.html`). The bar fetches
`/gc/addons` (same origin — the only core payload proxied without a session)
and links every installed web addon by its `path` — that's what makes all
addons feel like one site.

## Shared Python (`shared/py/`)

Same contract, server side. An addon runs from its own directory with its own
venv, so it never imports across the tree: `install.ps1` copies the files
`addon.json` lists under `shared` next to `server.py` and the addon just does
`import sfo`. Copies are gitignored, `shared/py/` is the only version to edit.

Currently there: `sfo.py`, a minimal PARAM.SFO reader (title, serial, version,
category — same binary format on PS3, PS4 and PSP), and `windows_dirs.py`
(`%APPDATA%`, Documents as the shell reports it, an emulator's exe folder from
`systems.json`; `GAMECORE_HOME` moves them all into a test sandbox). Adding a
module means dropping it in `shared/py/`, listing it in the `shared` field of
the addons that want it, and gitignoring the copy.

## Tests

`python scripts/run-tests.py <name>` stages the shared files and runs each
`tests/test_*.py` in its own interpreter (pytest, or as a script when the file
has its own `__main__`). Point both roots and `GAMECORE_HOME` at a temp folder:
never the real profile or data root. CI runs the same on `windows-latest`.

## Talking to the core

- Server-side only, over loopback: `http://127.0.0.1:8765/api/…`
- Refresh the TV UI after a change: `POST http://127.0.0.1:8765/api/addons/notify`
  with `{"event": "rom_uploaded", "data": {…}}` — the core broadcasts it on its
  WebSocket to the frontend.
- The core API is NEVER reachable from the LAN: if your browser UI needs a
  core endpoint, relay it through your own server (see rom-manager's
  `/api/roms/{system}/cover`).
