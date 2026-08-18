[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker"
)

$checks = @(
    [pscustomobject]@{
        Requirement = "WSL"
        Found = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
        Detail = "Required to host Docker Engine"
    },
    [pscustomobject]@{
        Requirement = "WSL Docker Engine"
        Found = $false
        Detail = "Expected in $WslDistribution"
    },
    [pscustomobject]@{
        Requirement = "usbipd-win"
        Found = [bool](
            (Get-Command usbipd.exe -ErrorAction SilentlyContinue) -or
            (Test-Path -LiteralPath "C:\Program Files\usbipd-win\usbipd.exe")
        )
        Detail = "Required to attach the RTL-SDR directly to WSL"
    }
)

if ($checks[0].Found) {
    wsl.exe -d $WslDistribution -- docker info *> $null
    $checks[1].Found = ($LASTEXITCODE -eq 0)
}

$checks | Format-Table -AutoSize

if ($checks.Found -contains $false) {
    Write-Error "One or more prerequisites are missing. See README.md for setup instructions."
    exit 1
}

Write-Host "All prerequisites were found."
