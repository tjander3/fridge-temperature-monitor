function Get-UsbAttachLauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [bool]$HasExited,

        [AllowNull()]
        [Nullable[int]]$ExitCode
    )

    if (-not $HasExited) {
        return "running"
    }

    # usbipd-win 5.x can hand --auto-attach off to a WSL helper and then exit
    # successfully. The WSL helper is the long-running process in that case.
    if ($ExitCode -eq 0) {
        return "handed-off"
    }

    return "failed"
}

Export-ModuleMember -Function Get-UsbAttachLauncherState
