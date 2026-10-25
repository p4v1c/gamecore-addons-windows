# PSScriptAnalyzer settings for the addon hooks (run by CI at Warning).
@{
    Severity     = @('Error', 'Warning')
    ExcludeRules = @(
        # The hooks talk to the Addons screen through the CLI's stdout; their
        # output is not data another command pipes on.
        'PSAvoidUsingWriteHost',
        # Install-/Uninstall-GcAddon are the hook itself, run by gamecore-addon:
        # there is no interactive caller to offer -WhatIf to.
        'PSUseShouldProcessForStateChangingFunctions'
    )
}
