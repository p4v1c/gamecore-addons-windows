"""Run every addon's tests, each file in its own process, as CI does.

    python scripts/run-tests.py            every addon
    python scripts/run-tests.py save-manager bios-manager

An addon's tests import its `server` module by name, and the script-style
ones set GAMECORE_PATH / GAMECORE_DATA at import: two addons in one pytest
session would share both. So each file gets a fresh interpreter, with the
addon folder as working directory, after the shared files are staged the way
`install.ps1` stages them (`shared/windows/addon-hooks.ps1`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "shared"
TEST_TIMEOUT_S = 600
PYTEST_STYLE = re.compile(r"^def test_", re.M)
# A file with its own __main__ runs its checks in order (python tests/test_x.py).
SCRIPT_STYLE = re.compile(r"^if __name__ == .__main__.:", re.M)
# What every web addon gets in web/ (the nav bar and the shared look).
WEB_FILES = ("nav/gamecore-nav.js", "nav/gamecore-nav.css", "ui/gamecore-ui.css", "ui/gamecore-icons.js")


def stage_shared(addon: Path) -> None:
    """Copy what the addon's manifest asks for from shared/, as install.ps1 does."""
    meta = json.loads((addon / "addon.json").read_text(encoding="utf-8-sig"))
    for rel in meta.get("shared", []):
        shutil.copy2(SHARED / rel, addon / Path(rel).name)
    if meta.get("type") == "web" and (addon / "web").is_dir():
        for rel in WEB_FILES:
            shutil.copy2(SHARED / rel, addon / "web" / Path(rel).name)
        shutil.copytree(SHARED / "ui" / "fonts", addon / "web" / "fonts", dirs_exist_ok=True)


def run_file(addon: Path, test: Path) -> bool:
    text = test.read_text(encoding="utf-8")
    is_pytest = bool(PYTEST_STYLE.search(text)) and not SCRIPT_STYLE.search(text)
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test)] if is_pytest \
        else [sys.executable, str(test)]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    started = time.monotonic()
    result = subprocess.run(argv, cwd=addon, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=TEST_TIMEOUT_S)
    ok = result.returncode == 0
    tail = (result.stdout.strip().splitlines() or [""])[-1]
    print(f"{'ok  ' if ok else 'FAIL'} {addon.name}/tests/{test.name}  {tail}  ({time.monotonic() - started:.1f} s)")
    if not ok:
        print(result.stdout[-6000:])
        print(result.stderr[-4000:])
    return ok


def main(names: list[str]) -> int:
    addons = [REPO / "addons" / n for n in names] if names else sorted(
        p.parent for p in (REPO / "addons").glob("*/addon.json"))
    failed = []
    for addon in addons:
        tests = sorted((addon / "tests").glob("test_*.py"))
        if not tests:
            continue
        stage_shared(addon)
        failed += [f"{addon.name}/{t.name}" for t in tests if not run_file(addon, t)]
    print(f"\n{len(failed)} failed" + (": " + ", ".join(failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
