"""Run an addon's server.py from its scheduled task, and keep it running.

    pythonw.exe addon-run.py <ADDON_DATA_DIR>\\addon.env

Copied next to each addon's server.py by install.ps1 (shared/windows/addon-hooks.ps1).
What a systemd unit gave the Linux addon, a scheduled task does not:
Environment= lines (read from addon.env here), a log (pythonw has no console:
stdout and stderr go to <DATA>\\logs\\addons\\<name>.log) and Restart=on-failure
(a crash restarts server.py after RESTART_DELAY_S, slower after a burst).
Stdlib only: it starts before anything is imported from the venv.
"""
from __future__ import annotations

import os
import runpy
import sys
import time
import traceback
from pathlib import Path

RESTART_DELAY_S = 5.0
CRASH_BURST = 5
CRASH_WINDOW_S = 120.0
SLOW_RESTART_DELAY_S = 60.0
LOG_CAP_BYTES = 2_000_000


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=value` lines; comments and blanks skipped; values raw."""
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def open_log(data: Path, name: str):
    """The addon's log, started afresh once it passes LOG_CAP_BYTES (one old copy kept)."""
    folder = data / "logs" / "addons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.log"
    if path.exists() and path.stat().st_size > LOG_CAP_BYTES:
        os.replace(path, path.with_suffix(".log.1"))
    return path.open("a", encoding="utf-8", errors="replace", buffering=1)


def restart_delay(crashes: list[float], now: float) -> float:
    """Seconds before the next start; `crashes` keeps the recent crash times."""
    crashes[:] = [t for t in crashes if now - t < CRASH_WINDOW_S] + [now]
    return SLOW_RESTART_DELAY_S if len(crashes) >= CRASH_BURST else RESTART_DELAY_S


def run_forever(server: Path, sleep=time.sleep, clock=time.monotonic) -> int:
    """Run server.py as __main__ until it returns cleanly; restart it when it raises."""
    crashes: list[float] = []
    while True:
        try:
            runpy.run_path(str(server), run_name="__main__")
            return 0
        except SystemExit as e:
            if e.code in (0, None):
                return 0
            print(f"[addon-run] server.py exited with {e.code}", flush=True)
        except Exception:
            traceback.print_exc()
        delay = restart_delay(crashes, clock())
        print(f"[addon-run] restarting in {delay:.0f} s", flush=True)
        sleep(delay)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: addon-run.py <addon.env>", file=sys.stderr)
        return 2
    os.environ.update(parse_env_file(Path(argv[1]).read_text(encoding="utf-8-sig")))
    addon_dir = Path(__file__).resolve().parent
    log = open_log(Path(os.environ["GAMECORE_DATA"]), os.environ.get("ADDON_NAME") or addon_dir.name)
    sys.stdout = sys.stderr = log
    print(f"[addon-run] {time.strftime('%Y-%m-%d %H:%M:%S')} starting {addon_dir.name}", flush=True)
    os.chdir(addon_dir)
    sys.path.insert(0, str(addon_dir))
    return run_forever(addon_dir / "server.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
