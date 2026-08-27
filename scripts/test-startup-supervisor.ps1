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

Assert-Equal "wait" (Get-MonitorSupervisorAction `
    -StopRequested $false `
    -UsbAttachState "handed-off" `
    -LanRelayStarted $true `
    -LanRelayExited $false) `
    "The supervisor remains alive after USB handoff while the LAN relay runs"
Assert-Equal "lan-failed" (Get-MonitorSupervisorAction `
    -StopRequested $false `
    -UsbAttachState "handed-off" `
    -LanRelayStarted $true `
    -LanRelayExited $true) `
    "A stopped LAN relay makes the scheduled task fail so Task Scheduler can restart it"
Assert-Equal "complete" (Get-MonitorSupervisorAction `
    -StopRequested $false `
    -UsbAttachState "handed-off" `
    -LanRelayStarted $false `
    -LanRelayExited $false) `
    "The supervisor can finish when neither Windows helper needs supervision"
Assert-Equal "stop" (Get-MonitorSupervisorAction `
    -StopRequested $true `
    -UsbAttachState "failed" `
    -LanRelayStarted $true `
    -LanRelayExited $true) `
    "An intentional stop takes precedence over child-process failures"

Write-Host "Startup supervisor tests passed."
exit 0
