"""Run shared/windows/addon-hooks.ps1 under pytest, with the machine faked.

A test hands a PowerShell snippet. It runs after the hooks file is dot-sourced
and after fake functions that shadow the scheduled-task cmdlets (PowerShell
resolves a function before a cmdlet of the same name), so no task is ever
registered on the PC running the tests. `$GcTest.calls` records each fake call;
the snippet's result is printed as JSON between markers for the test to read.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "shared" / "windows" / "addon-hooks.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is a Windows tool")

PRELUDE = r"""
$GcTest = @{ calls = New-Object System.Collections.Generic.List[object]; task = $null }
function Note { param([string]$Name, $Value) $GcTest.calls.Add(@{ name = $Name; value = $Value }) }
function Write-Host { param([Parameter(ValueFromRemainingArguments)]$Text) Note 'say' ([string]$Text) }
function Test-GcAddonElevated { return $true }
function Get-ScheduledTask { param($TaskPath, $TaskName, $ErrorAction) return $GcTest.task }
function Stop-ScheduledTask { param($TaskPath, $TaskName) Note 'stop' "$TaskPath$TaskName"; $GcTest.task = [pscustomobject]@{ State = 'Ready' } }
function Start-ScheduledTask { param($TaskPath, $TaskName) Note 'start' "$TaskPath$TaskName" }
function Unregister-ScheduledTask { param($TaskPath, $TaskName, $Confirm) Note 'unregister' "$TaskPath$TaskName"; $GcTest.task = $null }
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory) return @{ execute = $Execute; argument = $Argument; cwd = $WorkingDirectory } }
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User) return @{ logon = [bool]$AtLogOn; user = $User } }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) return @{ user = $UserId; logon = "$LogonType"; level = "$RunLevel" } }
function New-ScheduledTaskSettingsSet { param([Parameter(ValueFromRemainingArguments)]$Rest) return @{} }
function Register-ScheduledTask {
    param($TaskPath, $TaskName, $Action, $Trigger, $Principal, $Settings, $Description, [switch]$Force)
    Note 'register' @{ path = "$TaskPath$TaskName"; action = $Action; trigger = $Trigger; principal = $Principal }
    $GcTest.task = [pscustomobject]@{ State = 'Ready' }
}
function Out-GcResult { '<<<RESULT' + ($GcTest | ConvertTo-Json -Depth 8 -Compress) + 'RESULT>>>' }
"""


def addon_env(tmp_path: Path, addon_dir: Path, **extra: str) -> dict[str, str]:
    """The environment gamecore-addon hands a hook, rooted in tmp_path."""
    data = tmp_path / "data"
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    env.update({
        "ADDON_DIR": str(addon_dir), "ADDON_DATA_DIR": str(data / "addons" / addon_dir.name),
        "GAMECORE_DATA": str(data), "GAMECORE_PATH": str(tmp_path / "code"),
        "USER_NAME": "BOX\\player", "GAMECORE_ADDON_API": "1", "GAMECORE_BACKEND_PORT": "8765",
        "OFFLINE": "0", "PAYLOAD_DIR": "",
    })
    env.update(extra)
    (data / "addons" / addon_dir.name).mkdir(parents=True, exist_ok=True)
    return env


def run_ps(tmp_path: Path, body: str, env: dict[str, str], timeout: int = 180) -> dict:
    """Run `body` with the hooks loaded and the task cmdlets faked; return $GcTest."""
    script = tmp_path / f"case-{len(list(tmp_path.glob('case-*.ps1')))}.ps1"
    text = f". '{HOOKS}'\n" + PRELUDE + body + "\nOut-GcResult\n"
    # A BOM: Windows PowerShell reads a BOM-less script as ANSI.
    script.write_text(text, encoding="utf-8-sig", newline="\n")
    out = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-File", str(script)], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, timeout=timeout)
    if "<<<RESULT" not in out.stdout:
        raise AssertionError(f"PowerShell failed ({out.returncode}):\n{out.stdout}\n{out.stderr}")
    return json.loads(out.stdout.split("<<<RESULT", 1)[1].split("RESULT>>>", 1)[0])


def calls(result: dict, name: str) -> list:
    return [c["value"] for c in result["calls"] if c["name"] == name]
