# GameCore Addons for Windows

Optional, individually installable modules for
[GameCore for Windows](https://github.com/p4v1c/GamecoreWindows): the Windows
port of [p4v1c/gamecore-addons](https://github.com/p4v1c/gamecore-addons),
history included.

An addon is a versioned directory under `addons/`. The repo **is** the runtime:
`gamecore-addon` downloads GitHub's archive of `main` to
`<DATA>\addons\_repo` (there is no git on the box) and each addon runs straight
from it, as a scheduled task `\GameCore\Addons\<name>` started at the console
user's logon. Its venv and its own files live in `<DATA>\addons\<name>`, so a
GameCore update never touches an addon, and an addon update never touches the
player's files.

## Install

From the TV's Addons screen, or from an elevated prompt:

```powershell
gamecore-addon install rom-manager     # one command, nothing else
gamecore-addon list                    # available vs installed
gamecore-addon remove <name>
gamecore-addon update                  # fresh archive + reinstall every installed addon
```

The `gamecore-addon` CLI ships with the core (`install\bin\gamecore-addon`,
with `gamecore-addon.cmd` for a prompt). It needs elevation, like the backend
that runs it for the Addons screen: registering an elevated task does, and the
data root is read from the installer's `%ProgramData%\GameCore\session.env`,
which is administrators only.

## Addon types

| type      | what it is                              | in the shared nav |
|-----------|-----------------------------------------|-------------------|
| `web`     | web UI on its own port + scheduled task | yes               |
| `service` | headless daemon (watcher, bridge…)       | no                |
| `tool`    | one-shot script / system tweak, no service | no              |

Every installed addon (any type) appears in GameCore's Addons screen and in the
registry (`<DATA>\config\addons.json`). Only `web` addons get a link.

## Code and data are separate — write to `GAMECORE_DATA`, never to `GAMECORE_PATH`

| var | what it holds | may an addon write? |
|-----|---------------|---------------------|
| `GAMECORE_PATH` | the installation (`C:\Program Files\GameCore`): backend, venv, frontend | **no** |
| `GAMECORE_DATA` | what the player owns — `config\systems.json`, ROMs under `emu\`, covers, saves | yes |
| `ADDON_DATA_DIR` | your addon's own corner, `<DATA>\addons\<name>` — venv, caches, state | yes |

Every GameCore update replaces `GAMECORE_PATH` wholesale, and the console user
cannot write there. The question to ask for each path, one at a time:

> **Can the player modify this file, or does it arrive with the release?**

Data (`config\systems.json`, ROMs, saves, uploads) → `GAMECORE_DATA`.
Code → `GAMECORE_PATH`. The core's `backend/services/paths.py` has already
drawn this line — consult it rather than reinventing it. Emulators are not in
either root: their own folders (`%APPDATA%`, Documents, a portable install by
the exe `systems.json` names) are found through `shared/py/windows_dirs.py`.

Read both roots the same way in every addon:

```python
GAMECORE_PATH = Path(os.environ.get("GAMECORE_PATH", r"C:\Program Files\GameCore"))
GAMECORE_DATA = Path(os.environ.get("GAMECORE_DATA") or GAMECORE_PATH)
```

`GAMECORE_DATA` defaults to `GAMECORE_PATH` (as in the core), so **test with
the two pointing at different directories** — the only configuration in which
a test of the split proves anything. Each addon's `tests/test_paths.py` does
exactly that; copy the pattern.

An addon must declare `"api": 1` in its `addon.json` to say it obeys the above.
`gamecore-addon` refuses to install or update one that doesn't, by name.

Web addons include the shared nav bar (`shared/nav/`) so all UIs feel like one
site with sections — users never see ports. Anything under `shared/` is copied
into the addon by its `install.ps1`, never imported across the tree; the
copies are gitignored, `shared/` is the only version to edit.

## Available addons

| addon | type | port | description |
|-------|------|------|-------------|
| [rom-manager](addons/rom-manager) | web | 8770 | Upload ROMs from the browser (drag & drop per system), with names NTFS accepts |
| [rpcs3-manager](addons/rpcs3-manager) | web | 8771 | Configure PS3 games remotely — per-game config & patches, RPCS3-style |
| [save-manager](addons/save-manager) | web | 8772 | Back up / restore / delete emulator saves & save states (all systems), incl. inside PS1/PS2 memory cards, per GameCore profile |
| [bios-manager](addons/bios-manager) | web | 8773 | Drop BIOS, firmware and keys (files, folders, zips): each is recognised and filed where its emulator reads it, with what each system still lacks |

Ports 8770–8799 are reserved for addons; each addon declares its own in
`addon.json`, and nothing else repeats it.

## Creating an addon

Copy `addons/_template/` and read [docs/CREATING_AN_ADDON.md](docs/CREATING_AN_ADDON.md).
For how the whole thing fits together — the model, the registry, the install
contract, what each addon does internally and the traps — see
[docs/architecture/](docs/architecture/).

## Tests

```powershell
python -m pytest tests            # shared hooks, launcher, manifests, windows_dirs
python scripts/run-tests.py       # every addon's tests, one interpreter per file
```

CI runs both on `windows-latest`, with ruff and PSScriptAnalyzer
(`.github/workflows/ci.yml`).

## Windows port — dev notes (step 9)

Status, decisions and what was checked, kept here rather than in the core's
dev log (`p4v1c/GamecoreWindows`, `docs/dev-log/windows-port.md`, which points
here).

| Linux | Windows |
|---|---|
| `install.sh` / `uninstall.sh`, systemd user units | `install.ps1` / `uninstall.ps1` on `shared/windows/addon-hooks.ps1`; task `\GameCore\Addons\<name>` at logon, elevated |
| unit `Environment=`, journal, `Restart=on-failure` | `addon.env` + `shared/windows/addon-run.py` (log `<DATA>\logs\addons\<name>.log`, restart 5 s / 60 s after a burst) |
| venv in the checkout, system `python3` | venv in `ADDON_DATA_DIR` on a copy of the core's Python in `<DATA>\addons\_python` (the updater kills processes running from the code root) |
| `git clone` / `git pull` of the repo | GitHub archive of `main`, swapped in by `update` after every addon is stopped |
| Flatpak / XDG folders | `%APPDATA%`, `%LOCALAPPDATA%`, Documents (shell), portable folders by the exe `systems.json` names |
| profile swap by symlink | directory junction (the core's), seen by `profiles.is_link()` |
| rom-manager bezels via `/api/overlays` | removed: no overlay window on Windows |

Tested on the Windows PC (24-25/10/2026): every addon's tests and the hook tests
(scheduled-task cmdlets faked, one real venv), CI green; a venv's
`pythonw.exe` killed takes the base interpreter with it (so stopping the task
stops the server); the core's CLI against real PowerShell hooks in a temp root.

Not tested: a real install (no task registered, no Caddy, nothing under
`%ProgramData%` or Program Files on this PC), an addon reached through Caddy
`:8443`, a real emulator's folders (no Windows packs yet: the Windows paths
come from each emulator's documentation and the PC export tool), the offline
payload.

Open questions for the owner (conservative choice made):

- The tasks run **elevated**, like the backend. They could run unelevated
  (they only need the console user's folders and the data root).
- RPCS3's folder on Windows: `config\` (recent builds) or next to the exe, both
  handled; to confirm with the RPCS3 pack.
- `install` does not refresh the repo while other addons run from it; a newly
  added addon needs `update` first.
- The core's `uninstall.ps1` does not yet remove the addons' tasks (they point
  into the data root it keeps): run `gamecore-addon remove` for each first.

Next: step 10 (data import script, README and website of the Windows edition).
