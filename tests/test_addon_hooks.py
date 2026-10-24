"""shared/windows/addon-hooks.ps1: what every addon's install.ps1 and uninstall.ps1 do.

The scheduled-task cmdlets are faked (tests/ps_harness.py); the venv is real
where it is cheap (an empty requirements.txt), faked where it would need PyPI.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from ps_harness import REPO, addon_env, calls, needs_powershell, run_ps

pytestmark = needs_powershell

# The native calls a full install makes, faked: no venv, no pip, no network.
FAKE_NATIVE = r"""
function Invoke-GcAddonNative {
    param($FilePath, [string[]]$ArgumentList)
    Note 'native' (@($FilePath) + $ArgumentList -join ' ')
    if ($ArgumentList -contains 'platform; print(platform.python_version())' -or $ArgumentList[1] -like '*python_version*') { return '3.12.10' }
    if ($ArgumentList -contains 'venv') {
        New-Item -ItemType Directory -Force -Path (Join-Path $ArgumentList[-1] 'Scripts') | Out-Null
        Set-Content -LiteralPath (Join-Path $ArgumentList[-1] 'Scripts\python.exe') -Value ''
        Set-Content -LiteralPath (Join-Path $ArgumentList[-1] 'pyvenv.cfg') -Value 'version = 3.12.10'
    }
    return @()
}
"""


def _addon(tmp_path: Path, meta: dict, requirements: str = "fastapi\n") -> Path:
    """A checkout with the real shared/ next to one synthetic addon."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "shared", repo / "shared")
    d = repo / "addons" / meta["name"]
    (d / "web").mkdir(parents=True)
    (d / "addon.json").write_text(json.dumps(meta), encoding="utf-8-sig")
    (d / "requirements.txt").write_text(requirements, encoding="utf-8")
    (repo / "shared" / "py").mkdir(exist_ok=True)
    return d


WEB = {"name": "demo", "type": "web", "port": 8790, "path": "/demo", "api": 1, "shared": ["py/sfo.py"]}


def test_install_registers_a_logon_task_for_the_console_user_elevated(tmp_path):
    d = _addon(tmp_path, WEB)
    r = run_ps(tmp_path, FAKE_NATIVE + "Install-GcAddon", addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON="py.exe"))
    (task,) = calls(r, "register")
    venv = tmp_path / "data" / "addons" / "demo" / "venv"
    assert task["path"] == "\\GameCore\\Addons\\demo"
    assert task["action"]["execute"] == str(venv / "Scripts" / "pythonw.exe")
    assert task["action"]["cwd"] == str(d)
    assert task["action"]["argument"] == f'"{d / "addon-run.py"}" "{tmp_path / "data" / "addons" / "demo" / "addon.env"}"'
    assert task["trigger"] == {"logon": True, "user": "BOX\\player"}
    assert task["principal"] == {"user": "BOX\\player", "logon": "Interactive", "level": "Highest"}
    assert calls(r, "start") == ["\\GameCore\\Addons\\demo"]


def test_the_venv_lives_in_the_addon_data_dir_on_the_python_the_cli_handed_over(tmp_path):
    """Not in the checkout (an update replaces it) and not on the code root's Python."""
    d = _addon(tmp_path, WEB)
    r = run_ps(tmp_path, FAKE_NATIVE + "Install-GcAddon", addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON="C:\\data\\_python\\python.exe"))
    native = calls(r, "native")
    venv = tmp_path / "data" / "addons" / "demo" / "venv"
    assert f"C:\\data\\_python\\python.exe -m venv --clear {venv}" in native
    assert any(c.startswith(str(venv / "Scripts" / "python.exe") + " -m pip install") for c in native)


def test_a_second_install_with_the_same_requirements_skips_pip_and_stops_the_old_server_first(tmp_path):
    d = _addon(tmp_path, WEB)
    env = addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON="py.exe")
    run_ps(tmp_path, FAKE_NATIVE + "Install-GcAddon", env)
    r = run_ps(tmp_path, FAKE_NATIVE + "$GcTest.task = [pscustomobject]@{ State = 'Running' }\nInstall-GcAddon", env)
    assert not any("pip install" in c for c in calls(r, "native")), "nothing changed: no pip"
    names = [c["name"] for c in r["calls"] if c["name"] in ("stop", "register", "start")]
    assert names == ["stop", "register", "start"], "the running server holds the venv: stop it first"


def test_offline_installs_take_the_wheels_from_the_payload(tmp_path):
    d = _addon(tmp_path, WEB)
    env = addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON="py.exe", OFFLINE="1", PAYLOAD_DIR="E:\\payload")
    r = run_ps(tmp_path, FAKE_NATIVE + "Install-GcAddon", env)
    pip = [c for c in calls(r, "native") if "pip install" in c]
    assert pip and pip[0].endswith("--no-index --find-links E:\\payload\\wheels")


def test_the_server_environment_carries_both_roots_the_port_and_the_base(tmp_path):
    d = _addon(tmp_path, WEB)
    run_ps(tmp_path, FAKE_NATIVE + "Install-GcAddon", addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON="py.exe"))
    text = (tmp_path / "data" / "addons" / "demo" / "addon.env").read_bytes().decode("utf-8")
    assert "\r" not in text
    values = dict(line.split("=", 1) for line in text.splitlines() if not line.startswith("#"))
    assert values == {
        "GAMECORE_PATH": str(tmp_path / "code"), "GAMECORE_DATA": str(tmp_path / "data"),
        "ADDON_DATA_DIR": str(tmp_path / "data" / "addons" / "demo"), "ADDON_NAME": "demo",
        "ADDON_PORT": "8790", "ADDON_BASE": "/demo", "GAMECORE_BACKEND_PORT": "8765", "PYTHONUTF8": "1"}


def test_shared_files_are_copied_next_to_the_addon(tmp_path):
    d = _addon(tmp_path, WEB)
    run_ps(tmp_path, FAKE_NATIVE + "Install-GcAddon", addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON="py.exe"))
    for rel in ("addon-run.py", "sfo.py", "web/gamecore-nav.js", "web/gamecore-nav.css",
                "web/gamecore-ui.css", "web/gamecore-icons.js", "web/fonts/SourceSans3-var.woff2"):
        assert (d / rel).is_file(), rel


def test_install_refuses_without_elevation_before_touching_anything(tmp_path):
    d = _addon(tmp_path, WEB)
    body = FAKE_NATIVE + "function Test-GcAddonElevated { $false }\ntry { Install-GcAddon } catch { Note 'error' \"$_\" }"
    r = run_ps(tmp_path, body, addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON="py.exe"))
    assert "elevated" in calls(r, "error")[0]
    assert calls(r, "native") == [] and calls(r, "register") == []


def test_a_hook_run_by_hand_says_what_is_missing(tmp_path):
    d = _addon(tmp_path, WEB)
    env = addon_env(tmp_path, d)
    del env["USER_NAME"]
    r = run_ps(tmp_path, "try { Install-GcAddon } catch { Note 'error' \"$_\" }", env)
    assert "USER_NAME is not set" in calls(r, "error")[0]


def test_uninstall_stops_and_unregisters_and_keeps_the_data(tmp_path):
    d = _addon(tmp_path, WEB)
    own = tmp_path / "data" / "addons" / "demo"
    env = addon_env(tmp_path, d)
    (own / "state.json").write_text("{}", encoding="utf-8")
    r = run_ps(tmp_path, "$GcTest.task = [pscustomobject]@{ State = 'Running' }\nUninstall-GcAddon", env)
    assert [c["name"] for c in r["calls"] if c["name"] != "say"] == ["stop", "unregister"]
    assert (own / "state.json").exists()


def test_uninstall_of_an_addon_with_no_task_is_not_an_error(tmp_path):
    d = _addon(tmp_path, WEB)
    r = run_ps(tmp_path, "Uninstall-GcAddon", addon_env(tmp_path, d))
    assert calls(r, "unregister") == []


def test_the_venv_is_real_and_rebuilt_when_the_interpreter_changes(tmp_path):
    """The one real venv: an empty requirements.txt keeps pip offline."""
    d = _addon(tmp_path, WEB, requirements="")
    env = addon_env(tmp_path, d, GAMECORE_ADDON_PYTHON=sys.executable)
    run_ps(tmp_path, "Install-GcAddonVenv (Get-GcAddonContext)", env)
    venv = tmp_path / "data" / "addons" / "demo" / "venv"
    assert (venv / "Scripts" / "pythonw.exe").is_file()
    cfg = venv / "pyvenv.cfg"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("version", "version = 3.0.0\nold_version"), encoding="utf-8")
    run_ps(tmp_path, "Install-GcAddonVenv (Get-GcAddonContext)", env)
    assert "3.0.0" not in cfg.read_text(encoding="utf-8")


@pytest.mark.parametrize("addon", sorted(p.parent.name for p in (REPO / "addons").glob("*/addon.json")))
def test_every_addon_hook_loads_the_shared_steps(tmp_path, addon):
    """Each install.ps1 / uninstall.ps1 dot-sources the shared file by a path that exists."""
    for script in ("install.ps1", "uninstall.ps1"):
        text = (REPO / "addons" / addon / script).read_text(encoding="ascii")
        assert "'..\\..\\shared\\windows\\addon-hooks.ps1'" in text
        assert ("Install-GcAddon" if script == "install.ps1" else "Uninstall-GcAddon") in text
