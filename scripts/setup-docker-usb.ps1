[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker"
)

$ErrorActionPreference = "Stop"
$hardwareId = "0bda:2838"
$usbipd = Get-Command usbipd.exe -ErrorAction SilentlyContinue
$usbipdPath = if ($usbipd) {
    $usbipd.Source
} else {
    $installedUsbipd = "C:\Program Files\usbipd-win\usbipd.exe"
    if (Test-Path -LiteralPath $installedUsbipd) {
        $installedUsbipd
    } else {
        throw "usbipd-win is not installed. Install it before running this setup."
    }
}

& wsl.exe -d $WslDistribution -- true
if ($LASTEXITCODE -ne 0) {
    throw "WSL distribution '$WslDistribution' could not be started."
}

Write-Host "Sharing RTL-SDR $hardwareId with WSL. Approve the Administrator prompt."
$bind = Start-Process `
    -FilePath $usbipdPath `
    -ArgumentList @("bind", "--hardware-id", $hardwareId) `
    -Verb RunAs `
    -Wait `
    -PassThru
if ($bind.ExitCode -ne 0) {
    throw "usbipd could not bind the RTL-SDR (exit code $($bind.ExitCode))."
}

Write-Host "RTL-SDR sharing is configured. This bind persists across reboots."
Write-Host "Run .\scripts\start-monitor.ps1 to attach it and start Docker."
