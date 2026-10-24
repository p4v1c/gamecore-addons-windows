# bios-manager: stop and unregister its task. Its data stays (ADDON_DATA_DIR).
. (Join-Path $PSScriptRoot '..\..\shared\windows\addon-hooks.ps1')
Uninstall-GcAddon
