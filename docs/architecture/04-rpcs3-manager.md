# 4 — rpcs3-manager (:8771, `/rpcs3`)

Configure PS3 games remotely, in RPCS3's own vocabulary: per-game config,
patches, and `.pkg` installation. `server.py`, plus `ryaml.py` and `schema.py`.

## Finding RPCS3

RPCS3 for Windows is portable: one folder holds `rpcs3.exe`, `dev_hdd0\` and
`patches\`, and its YAML files (`config.yml`, `games.yml`, `custom_configs\`,
`patch_config.yml`) sit in `config\` on recent builds, next to the exe on
older ones. The addon must edit **the install the box actually launches**.

| Function | Role |
|---|---|
| `_declared_path()` | the `path` of the `rpcs3` entry in the player's `systems.json` (`GAMECORE_DATA`) |
| `find_rpcs3()` | `RPCS3_DIR`, else the folder of that exe (relative = under `GAMECORE_DATA`); `None` when neither |
| `rpcs3_dir()` | that folder, or a 503 `NOT_INSTALLED` ("RPCS3 is not installed on this PC") |
| `config_dir()` | `config\` when it holds `config.yml` or `games.yml`, else the exe's folder |
| `rpcs3_cmd()` | `RPCS3_BIN`, else `rpcs3.exe` in that folder, or `None` |
| `read_text(path)` / `write_text(path, text)` | UTF-8, and **LF** on write: Windows newline translation would rewrite every line of RPCS3's files |
| `backup(path)` | timestamped `.bak` before touching an existing file |
| `yload(path)` | read a YAML file through `ryaml` |

## `ryaml.py` — string-preserving YAML

**The single most important module in this addon.** RPCS3 config and patch
files are full of scalars that YAML 1.1 silently reinterprets:

| In the file | What PyYAML makes of it | What RPCS3 needs |
|---|---|---|
| `On` / `Off` | `True` / `False` | the strings `On` / `Off` |
| `1.10` | float `1.1` | the string `1.10` |
| `No` | `False` | `No` |

Round-tripping a config through stock PyYAML therefore **corrupts it**, and
RPCS3 answers by silently ignoring the file. `_StrLoader` overrides
`compose_node` so every scalar stays a string; `_StrDumper` writes them back
unquoted the way RPCS3 does. `load(text)` / `dump(data)` are the only entry
points.

> Do not "simplify" this to `yaml.safe_load`. It has been tried; it breaks
> every custom config on the box.

Belt and braces on top of it: `_edit_config_text(text, section, key, value)`
does a **surgical line edit** — change or insert one key inside one section,
touching nothing else. `_fmt_value(value)` formats a scalar the way RPCS3
writes it (with `"Null"` as the documented exception).

## `schema.py` — the curated config surface

`f(section, key, type_, **kw)` builds one field; the module is a list of them
mirroring the RPCS3 UI tabs. The enum strings are the **exact** serializations
RPCS3 expects — a typo produces a config the emulator ignores without an error.
`GET /api/schema` hands it to the UI, which renders the form generically.

## Routes

### Games

| Route | Function | Notes |
|---|---|---|
| `GET /api/health` | `health()` | |
| `GET /api/games` | `list_games()` | scans `emu/rpcs3/`, reads title/serial from `PARAM.SFO` via `shared/py/sfo.py` |
| `GET /api/games/{serial}/icon` | `game_icon(serial)` | `PS3_GAME/ICON0.PNG` |
| `DELETE /api/games/{serial}` | `remove_game(serial, data)` | drops the game's line from RPCS3's `games.yml` |

Helpers: `_disc_sfo(game_path)`, `_check_serial(serial)` (validates the path
segment), and `_game_versions(cfg, serial, base_ver)` — the effective app
versions, disc `APP_VER` plus any installed update.

### Per-game config

| Route | Function |
|---|---|
| `GET /api/games/{serial}/config` | `get_game_config(serial)` |
| `PUT /api/games/{serial}/config` | `put_game_config(serial, body)` — `ConfigBody` |
| `DELETE /api/games/{serial}/config` | `reset_game_config(serial)` |

`_custom_path(serial)` locates the per-game YAML in RPCS3's custom-config
directory. `_get_path(tree, segments)` / `_set_path(tree, segments, value)`
walk the nested tree; `_schema_values(tree)` projects it onto the schema for
the UI.

> Per-game configs live under RPCS3's own config directory, the same one the
> emulator reads at launch: `config\` or the exe's folder depending on the
> build, hence `config_dir()`. `dev_hdd0\` and `patches\` are always by the exe
> (`rpcs3_dir()`).

### Patches

| Route | Function |
|---|---|
| `GET /api/games/{serial}/patches` | `game_patches(serial)` |
| `POST /api/games/{serial}/patches/toggle` | `toggle_patch(serial, body)` — `ToggleBody` |
| `POST /api/patches/download-official` | `download_official_patches()` |
| `POST /api/patches/upload` | `upload_patch(file)` |

- `_patch_files(serial)` — which patch files apply to a serial.
- `_enabled_key(tree)` — **version drift**: the box's RPCS3 writes `Enabled`,
  newer sources say `enabled`. This picks whichever the file uses instead of
  guessing.
- `_validate_patch_yaml(tree)` — counts real patch entries (a `Patch` list plus
  a `Games` map) before accepting an upload, so a stray YAML file cannot be
  merged in as a patch.
- `upload_patch()` validates then merges into `imported_patch.yml`.

### `.pkg` installation

Updates and DLC ship as `.pkg` files, and RPCS3 installs them only with its
window open (`--installpkg` refuses `--no-gui`). The addon's task runs in the
console user's session, so the window opens on the TV with nothing to
discover:

| Function | Role |
|---|---|
| `_hdd_snapshot()` | listing of `dev_hdd0/game` before the install |
| `_watch_install(proc, dest, before)` | detects the install landing, then closes RPCS3 |
| `_finish_job(proc, dest, before)` | job completion bookkeeping |
| `GET /api/pkg/status` → `pkg_status()` | poll from the UI |
| `POST /api/pkg/install` → `install_pkg(file)` | start the job |

The snapshot-diff approach exists because RPCS3 gives no machine-readable
signal that a `.pkg` finished: the addon watches the directory instead, then
terminates the emulator itself.
