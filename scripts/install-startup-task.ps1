[CmdletBinding()]
param(
    [string]$TaskName = "Fridge Temperature Monitor",
    [string]$WslDistribution = "Ubuntu-Docker"
)

$ErrorActionPreference = "Stop"
$startScript = (Resolve-Path (Join-Path $PSScriptRoot "start-monitor.ps1")).Path
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`" -WslDistribution `"$WslDistribution`""

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
    -Description "Starts the local RTL-SDR refrigerator and freezer temperature monitor at sign-in." `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'. It will start at your next Windows sign-in."
Write-Host "Start it now with: Start-ScheduledTask -TaskName '$TaskName'"
