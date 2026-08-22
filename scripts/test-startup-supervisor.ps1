$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "monitor-supervisor.psm1"
Import-Module $modulePath -Force

function Assert-Equal {
    param(
        [Parameter(Mandatory)]
        [object]$Expected,

        [Parameter(Mandatory)]
        [object]$Actual,

        [Parameter(Mandatory)]
        [string]$Description
    )

    if ($Expected -ne $Actual) {
        throw "$Description`: expected '$Expected', got '$Actual'."
    }
}

Assert-Equal "running" (Get-UsbAttachLauncherState -HasExited $false) `
    "A running usbipd launcher remains supervised"
Assert-Equal "handed-off" (Get-UsbAttachLauncherState -HasExited $true -ExitCode 0) `
    "A successful usbipd-to-WSL handoff is accepted"
Assert-Equal "failed" (Get-UsbAttachLauncherState -HasExited $true -ExitCode 1) `
    "A nonzero usbipd launcher exit is rejected"

Write-Host "Startup supervisor tests passed."
exit 0
