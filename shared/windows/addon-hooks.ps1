# What every addon's install.ps1 and uninstall.ps1 do, dot-sourced from the
# repo checkout (the hooks run from it, so nothing needs copying first).
#
# An addon runs as a scheduled task \GameCore\Addons\<name>: at the console
# user's logon, elevated like the backend, on its own venv in ADDON_DATA_DIR
# built from the interpreter the CLI hands over (GAMECORE_ADDON_PYTHON, a copy
# in the data root). The contract: docs/architecture/02-lifecycle-and-registry.md.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:GcAddonTaskPath = '\GameCore\Addons\'
# What every web addon gets in web\: the nav bar and the shared look.
$script:GcAddonWebFiles = @('nav\gamecore-nav.js', 'nav\gamecore-nav.css', 'ui\gamecore-ui.css', 'ui\gamecore-icons.js')
$script:GcAddonStopTimeoutS = 30
$script:GcAddonRunner = 'addon-run.py'

function Write-GcAddonInfo {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host "[$env:GCA_HOOK_ADDON] $Message"
}

function Get-GcAddonEnv {
    param([Parameter(Mandatory)][string]$Name)
    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not $value) { throw "$Name is not set: run this through gamecore-addon, not by hand" }
    return $value
}

function Get-GcAddonContext {
    <# Every path a hook needs, from the CLI's environment and the addon's addon.json. #>
    $dir = (Resolve-Path -LiteralPath (Get-GcAddonEnv 'ADDON_DIR')).Path
    # ConvertFrom-Json on text read as UTF-8: a BOM from Notepad is dropped.
    $meta = [IO.File]::ReadAllText((Join-Path $dir 'addon.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
    $dataDir = Get-GcAddonEnv 'ADDON_DATA_DIR'
    $venv = Join-Path $dataDir 'venv'
    $env:GCA_HOOK_ADDON = $meta.name
    return [pscustomobject]@{
        Name        = [string]$meta.name
        Type        = [string]$meta.type
        Port        = if ($meta.PSObject.Properties['port']) { [int]$meta.port } else { 0 }
        Base        = if ($meta.PSObject.Properties['path']) { [string]$meta.path } else { '' }
        Shared      = if ($meta.PSObject.Properties['shared']) { @($meta.shared) } else { @() }
        Dir         = $dir
        SharedRoot  = Join-Path $dir '..\..\shared'
        DataDir     = $dataDir
        Data        = Get-GcAddonEnv 'GAMECORE_DATA'
        Code        = Get-GcAddonEnv 'GAMECORE_PATH'
        User        = Get-GcAddonEnv 'USER_NAME'
        BackendPort = if ($env:GAMECORE_BACKEND_PORT) { $env:GAMECORE_BACKEND_PORT } else { '8765' }
        Offline     = $env:OFFLINE -eq '1'
        Payload     = [string]$env:PAYLOAD_DIR
        Venv        = $venv
        EnvFile     = Join-Path $dataDir 'addon.env'
        TaskName    = [string]$meta.name
    }
}

function Invoke-GcAddonNative {
    <# Run a native program; a non-zero exit code throws with its output. #>
    param([Parameter(Mandatory)][string]$FilePath, [string[]]$ArgumentList = @())
    # Windows PowerShell turns each stderr line into an error record, and under
    # 'Stop' the first one (a pip warning) throws although the program succeeded.
    $ErrorActionPreference = 'Continue'
    $output = @(& $FilePath @ArgumentList 2>&1)
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($ArgumentList -join ' ') exited with $LASTEXITCODE`: $(($output | ForEach-Object { "$_" }) -join ' ')"
    }
    return @($output | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
}

function Test-GcAddonElevated {
    $principal = New-Object Security.Principal.WindowsPrincipal ([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-GcVenvVersion {
    <# The Python version a venv was made with (pyvenv.cfg), or $null. #>
    param([Parameter(Mandatory)][string]$Venv)
    $cfg = Join-Path $Venv 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $cfg)) { return $null }
    foreach ($line in [IO.File]::ReadAllLines($cfg)) {
        if ($line -match '^\s*version\s*=\s*(\S+)') { return $Matches[1] }
    }
    return $null
}

function Get-GcRequirementsStamp {
    <# Changes when requirements.txt or the interpreter does: the cue to run pip again. #>
    param([Parameter(Mandatory)]$Context, [Parameter(Mandatory)][string]$PythonVersion)
    $requirements = Join-Path $Context.Dir 'requirements.txt'
    $bytes = [IO.File]::ReadAllBytes($requirements)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join '' } finally { $sha.Dispose() }
    return "$PythonVersion $hash"
}

function Install-GcAddonVenv {
    <# The addon's venv in ADDON_DATA_DIR, rebuilt when the interpreter changed; pip only when needed. #>
    param([Parameter(Mandatory)]$Context)
    $python = Get-GcAddonEnv 'GAMECORE_ADDON_PYTHON'
    $version = (Invoke-GcAddonNative $python @('-c', 'import platform; print(platform.python_version())') |
            Select-Object -Last 1).Trim()
    $venvPython = Join-Path $Context.Venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython) -or (Get-GcVenvVersion $Context.Venv) -ne $version) {
        Write-GcAddonInfo "Python $version venv in $($Context.Venv)"
        Invoke-GcAddonNative $python @('-m', 'venv', '--clear', $Context.Venv) | Out-Null
    }
    $stampFile = Join-Path $Context.Venv 'gamecore-requirements.txt'
    $wanted = Get-GcRequirementsStamp $Context $version
    $have = if (Test-Path -LiteralPath $stampFile) { [IO.File]::ReadAllText($stampFile).Trim() } else { '' }
    if ($have -eq $wanted) { return }
    Write-GcAddonInfo 'Python packages'
    $pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-q',
        '-r', (Join-Path $Context.Dir 'requirements.txt'))
    if ($Context.Offline) { $pipArgs += @('--no-index', '--find-links', ([IO.Path]::Combine($Context.Payload, 'wheels'))) }
    Invoke-GcAddonNative $venvPython $pipArgs | Out-Null
    [IO.File]::WriteAllText($stampFile, $wanted)
}

function Copy-GcAddonShared {
    <# shared\ is copied next to the addon, never imported across the tree. #>
    param([Parameter(Mandatory)]$Context)
    $shared = $Context.SharedRoot
    Copy-Item -LiteralPath (Join-Path $shared "windows\$script:GcAddonRunner") -Destination $Context.Dir -Force
    foreach ($rel in $Context.Shared) {
        Copy-Item -LiteralPath (Join-Path $shared $rel) -Destination $Context.Dir -Force
    }
    $web = Join-Path $Context.Dir 'web'
    if ($Context.Type -ne 'web' -or -not (Test-Path -LiteralPath $web)) { return }
    foreach ($rel in $script:GcAddonWebFiles) {
        Copy-Item -LiteralPath (Join-Path $shared $rel) -Destination $web -Force
    }
    $fonts = Join-Path $web 'fonts'
    New-Item -ItemType Directory -Force -Path $fonts | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $shared 'ui\fonts') -File | Copy-Item -Destination $fonts -Force
}

function Get-GcAddonEnvText {
    <# addon.env: what the launcher puts in the server's environment (a task has no Environment=). #>
    param([Parameter(Mandatory)]$Context, [hashtable]$Extra = @{})
    $values = [ordered]@{
        GAMECORE_PATH         = $Context.Code
        GAMECORE_DATA         = $Context.Data
        ADDON_DATA_DIR        = $Context.DataDir
        ADDON_NAME            = $Context.Name
        ADDON_PORT            = [string]$Context.Port
        ADDON_BASE            = $Context.Base
        GAMECORE_BACKEND_PORT = $Context.BackendPort
        PYTHONUTF8            = '1'
    }
    foreach ($key in ($Extra.Keys | Sort-Object)) { $values[$key] = [string]$Extra[$key] }
    $lines = @("# Written by $($Context.Name)\install.ps1; read by $script:GcAddonRunner.")
    foreach ($key in $values.Keys) {
        if ($values[$key] -match "[`r`n]") { throw "$key holds a line break" }
        $lines += "$key=$($values[$key])"
    }
    return ($lines -join "`n") + "`n"
}

function Get-GcAddonTask {
    param([Parameter(Mandatory)]$Context)
    return Get-ScheduledTask -TaskPath $script:GcAddonTaskPath -TaskName $Context.TaskName -ErrorAction SilentlyContinue
}

function Stop-GcAddonTask {
    <# Stop the running server: pip and the CLI's repo swap cannot replace files it holds. #>
    param([Parameter(Mandatory)]$Context)
    $task = Get-GcAddonTask $Context
    if (-not $task) { return }
    if ($task.State -eq 'Running') {
        Write-GcAddonInfo 'Stopping the running server'
        Stop-ScheduledTask -TaskPath $script:GcAddonTaskPath -TaskName $Context.TaskName
    }
    $deadline = (Get-Date).AddSeconds($script:GcAddonStopTimeoutS)
    while (($task = Get-GcAddonTask $Context) -and $task.State -eq 'Running') {
        if ((Get-Date) -gt $deadline) { throw "$($Context.Name) still running after $script:GcAddonStopTimeoutS s" }
        Start-Sleep -Milliseconds 250
    }
}

function Register-GcAddonTask {
    <# At the console user's logon, elevated like the backend, restarted if it dies. #>
    param([Parameter(Mandatory)]$Context)
    $pythonw = Join-Path $Context.Venv 'Scripts\pythonw.exe'
    $runner = Join-Path $Context.Dir $script:GcAddonRunner
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$runner`" `"$($Context.EnvFile)`"" `
        -WorkingDirectory $Context.Dir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $Context.User
    $principal = New-ScheduledTaskPrincipal -UserId $Context.User -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew -StartWhenAvailable
    Register-ScheduledTask -TaskPath $script:GcAddonTaskPath -TaskName $Context.TaskName -Action $action `
        -Trigger $trigger -Principal $principal -Settings $settings `
        -Description "GameCore addon $($Context.Name)" -Force | Out-Null
}

function Install-GcAddon {
    <# Idempotent: update runs it again. Extra goes into the server's environment. #>
    param([hashtable]$Extra = @{})
    $context = Get-GcAddonContext
    if (-not (Test-GcAddonElevated)) {
        throw 'registering the addon task needs an elevated prompt (the GameCore backend runs elevated)'
    }
    Stop-GcAddonTask $context
    Install-GcAddonVenv $context
    Write-GcAddonInfo 'Shared files'
    Copy-GcAddonShared $context
    [IO.File]::WriteAllText($context.EnvFile, (Get-GcAddonEnvText $context $Extra), (New-Object Text.UTF8Encoding $false))
    Write-GcAddonInfo "Task $script:GcAddonTaskPath$($context.TaskName)"
    Register-GcAddonTask $context
    Start-ScheduledTask -TaskPath $script:GcAddonTaskPath -TaskName $context.TaskName
    $where = if ($context.Port) { " on 127.0.0.1:$($context.Port)" } else { '' }
    Write-GcAddonInfo "Installed and started$where"
}

function Uninstall-GcAddon {
    <# Stop and unregister. The addon's data, venv included, stays: the player owns it. #>
    $context = Get-GcAddonContext
    if (-not (Get-GcAddonTask $context)) {
        Write-GcAddonInfo 'No task registered'
        return
    }
    Stop-GcAddonTask $context
    Unregister-ScheduledTask -TaskPath $script:GcAddonTaskPath -TaskName $context.TaskName -Confirm:$false
    Write-GcAddonInfo 'Task removed'
}
