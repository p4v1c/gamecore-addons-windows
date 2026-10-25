# 1 — The addon model

## Services, not plugins

An addon is **an independent HTTP service with a static web UI**. The core
never imports addon code; an addon never imports core code. They meet over
loopback HTTP and one JSON registry file.

That choice buys three things:

| Property | Because |
|---|---|
| An addon crash cannot take the TV down | separate process, its own scheduled task, restarted by `addon-run.py` |
| An addon can be written in anything | the contract is HTTP + a manifest, not a Python API |
| The checkout is what runs | no build step: what is in `<DATA>\addons\_repo` is what is deployed |

The cost is that everything shared has to be *copied* rather than imported —
see [2](02-lifecycle-and-registry.md#shared-components).

## The file contract

Every addon directory contains exactly:

| File | Role |
|---|---|
| `addon.json` | the manifest |
| `install.ps1` | idempotent: dot-sources `shared\windows\addon-hooks.ps1` and calls `Install-GcAddon` |
| `uninstall.ps1` | calls `Uninstall-GcAddon`: stop and unregister the task, data kept |
| `requirements.txt` | Python deps |
| `server.py` | the FastAPI app |
| `web/index.html` | the whole UI, no build step |

Copy `addons/_template/` to start. Its `server.py` is the minimum that works:

```python
ADDON_DIR = Path(__file__).parent
PORT = int(os.environ.get("ADDON_PORT", 8799))

app = FastAPI(title="GameCore addon — template",
              root_path=os.environ.get("ADDON_BASE", ""))

@app.get("/api/health")
def health():
    return {"ok": True}

app.mount("/", StaticFiles(directory=str(ADDON_DIR / "web"), html=True), name="web")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
```

Four things in there are the contract, not decoration:

1. **`host="127.0.0.1"`** — an addon on `0.0.0.0` is an unauthenticated file
   manager on the LAN.
2. **`root_path=os.environ["ADDON_BASE"]`** — the app is served under `/roms`,
   `/saves`, `/rpcs3`, `/bios` by Caddy. Without it every generated URL is wrong.
3. **`ADDON_PORT` from the environment**, with the manifest's port as default.
4. **`web/` mounted last**, `html=True`, so unknown paths fall back to the SPA
   and `/api/*` still wins.

## `addon.json`

```jsonc
{
  "api": 1,                        // the hook contract it obeys (the core's docs, 12)
  "name": "save-manager",          // directory name, task name, registry key
  "label": "Saves",                // shown in the nav bar and the TV screen
  "description": "Browse, back up, restore & delete every emulator's saves…",
  "version": "3.0.0",
  "type": "web",                   // web | service | tool
  "default": false,                // true → offered checked by the installer
  "service": "user",               // runs as the console user (a logon task)
  "port": 8772,                    // ADDON_PORT, read by install.ps1
  "offline_assets": ["wheels"],    // extra payload for offline installs
  "path": "/saves",                // the prefix Caddy proxies → ADDON_BASE
  "shared": ["py/sfo.py", "py/windows_dirs.py"]   // copied next to server.py
}
```

| `type` | What it is | In the nav bar |
|---|---|---|
| `web` | web UI on its own port + a scheduled task | yes |
| `service` | headless daemon (watcher, bridge…) | no |
| `tool` | one-shot script / system tweak, no service | no |

Every installed addon of any type lands in the registry
(`<DATA>\config\addons.json`) and shows on the TV's Addons screen.
Only `web` addons get a link.

## Ports

8770-8799 are reserved for addons.

| Addon | Port | `path` |
|---|---|---|
| rom-manager | 8770 | `/roms` |
| rpcs3-manager | 8771 | `/rpcs3` |
| save-manager | 8772 | `/saves` |
| bios-manager | 8773 | `/bios` |
| _template | 8799 | `/template` |

The port and the path are written once, in `addon.json`: `install.ps1` reads
them from there (the Linux `install.sh` repeated the port, and nothing checked
that the two agreed). `tests/test_manifests.py` checks they are distinct and
in range. A new `path` also needs its route in the core's
`install/system/Caddyfile`.

## What an addon may and may not do

**May:**

- read the PC's filesystem — ROMs, emulator data, `config\systems.json` to
  learn where things live;
- call the core over loopback: `http://127.0.0.1:8765/api/…`;
- push an event to the TV with
  `POST /api/addons/notify {"event": "...", "data": {...}}`, which the core
  relays on its WebSocket;
- read `/gc/addons` to discover its siblings (same origin, no auth needed).

**May not:**

- import core Python modules — they are not on its path and the core's release
  cycle is independent;
- write auth code — Caddy owns that;
- bind anything but loopback;
- assume a build step exists.

## Runtime environment

The task runs `<ADDON_DATA_DIR>\venv\Scripts\pythonw.exe addon-run.py
<ADDON_DATA_DIR>\addon.env` in the addon's folder. `addon-run.py` (copied from
`shared\windows\`) puts `addon.env` in the environment, sends stdout and stderr
to `<DATA>\logs\addons\<name>.log`, and runs `server.py`, again after a crash
(5 s, 60 s after a burst). `addon.env`, written by `install.ps1`, holds:

| Variable | Meaning |
|---|---|
| `GAMECORE_PATH` | the installation (`C:\Program Files\GameCore`). **Read only.** |
| `GAMECORE_DATA` | the player's data — `config\`, `emu\`. Writable. |
| `ADDON_DATA_DIR` | the addon's own corner, `<DATA>\addons\<name>` (its venv is there too) |
| `ADDON_NAME` | the addon's name (the log file) |
| `ADDON_PORT` | the port to bind |
| `ADDON_BASE` | the path prefix → `root_path` |
| `GAMECORE_BACKEND_PORT` | where the core listens |
| `PYTHONUTF8` | `1`: files are read as UTF-8, as the core reads them |

The working directory is the addon's folder, which is why `import sfo`
resolves to the copy sitting next to `server.py`.
