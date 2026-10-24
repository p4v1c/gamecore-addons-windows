"""shared/windows/addon-run.py: the launcher a scheduled task starts instead of a systemd unit."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "shared" / "windows" / "addon-run.py"


def _load():
    loader = importlib.machinery.SourceFileLoader("addon_run", str(RUNNER))
    spec = importlib.util.spec_from_loader("addon_run", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


run = _load()


def test_env_file_lines_become_variables_and_comments_do_not():
    text = "# written by install.ps1\nADDON_PORT=8770\n\nADDON_BASE=/roms\nGAMECORE_DATA=D:\\Game Core\n"
    assert run.parse_env_file(text) == {"ADDON_PORT": "8770", "ADDON_BASE": "/roms", "GAMECORE_DATA": "D:\\Game Core"}


def test_a_crash_restarts_the_server_and_a_clean_exit_ends_the_launcher(tmp_path):
    server = tmp_path / "server.py"
    count = tmp_path / "count.txt"
    server.write_text(
        "from pathlib import Path\n"
        f"p = Path(r'{count}')\n"
        "n = int(p.read_text()) + 1 if p.exists() else 1\n"
        "p.write_text(str(n))\n"
        "if n < 3:\n    raise RuntimeError('boom')\n", encoding="utf-8")
    slept = []
    assert run.run_forever(server, sleep=slept.append, clock=lambda: 0.0) == 0
    assert count.read_text() == "3"
    assert slept == [run.RESTART_DELAY_S, run.RESTART_DELAY_S]


def test_a_burst_of_crashes_slows_the_restarts_down():
    crashes: list[float] = []
    delays = [run.restart_delay(crashes, float(t)) for t in range(run.CRASH_BURST)]
    assert delays[-1] == run.SLOW_RESTART_DELAY_S and delays[0] == run.RESTART_DELAY_S
    assert run.restart_delay(crashes, 10_000.0) == run.RESTART_DELAY_S, "old crashes are forgotten"


def test_a_server_that_exits_with_an_error_code_is_restarted(tmp_path):
    server = tmp_path / "server.py"
    marker = tmp_path / "ran"
    server.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"p = Path(r'{marker}')\n"
        "first = not p.exists()\np.write_text('x')\n"
        "sys.exit(1 if first else 0)\n", encoding="utf-8")
    slept = []
    assert run.run_forever(server, sleep=slept.append, clock=lambda: 0.0) == 0
    assert len(slept) == 1


def test_the_launcher_applies_the_env_file_and_logs_under_the_data_root(tmp_path):
    """Run for real, as the task runs it: a copy next to a server.py, the env file as argument."""
    addon = tmp_path / "addons" / "demo"
    addon.mkdir(parents=True)
    (addon / "addon-run.py").write_bytes(RUNNER.read_bytes())
    (addon / "server.py").write_text(
        "import os\nprint('port', os.environ['ADDON_PORT'], 'cwd', os.getcwd())\n", encoding="utf-8")
    data = tmp_path / "data"
    env_file = tmp_path / "addon.env"
    env_file.write_text(f"# test\nGAMECORE_DATA={data}\nADDON_NAME=demo\nADDON_PORT=8790\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(addon / "addon-run.py"), str(env_file)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    log = (data / "logs" / "addons" / "demo.log").read_text(encoding="utf-8")
    assert "starting demo" in log
    assert f"port 8790 cwd {addon}" in log
