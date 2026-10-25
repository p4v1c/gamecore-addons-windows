# bios-manager: install or update, idempotent (gamecore-addon runs it again on update).
# The steps live in shared\windows\addon-hooks.ps1; this file only names what differs.
. (Join-Path $PSScriptRoot '..\..\shared\windows\addon-hooks.ps1')
Install-GcAddon
