[CmdletBinding()]
param(
    [string]$RtlTcpPath,
    [string]$WslDistribution = "Ubuntu-Docker"
)

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localRtlTcp = Join-Path $repositoryRoot ".tools\rtl-sdr\v1.3.6\x64\rtl_tcp.exe"
if (-not $RtlTcpPath) {
    $RtlTcpPath = if (Test-Path -LiteralPath $localRtlTcp) {
        $localRtlTcp
    } else {
        "rtl_tcp.exe"
    }
}

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
        Requirement = "rtl_tcp"
        Found = [bool](Get-Command $RtlTcpPath -ErrorAction SilentlyContinue)
        Detail = "Required for Windows USB access"
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
