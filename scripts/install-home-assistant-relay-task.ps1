[CmdletBinding()]
param(
    [string]$TaskName = "Fridge Monitor Home Assistant Relay"
)

$ErrorActionPreference = "Stop"
$relayScript = (Resolve-Path (Join-Path $PSScriptRoot "start-home-assistant-relay.ps1")).Path
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$relayScript`""

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Keeps the fridge monitor reachable only on the home LAN for Home Assistant polling." `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'."
Write-Host "Start it now with: Start-ScheduledTask -TaskName '$TaskName'"
