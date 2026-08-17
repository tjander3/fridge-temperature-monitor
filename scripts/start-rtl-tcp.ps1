[CmdletBinding()]
param(
    [string]$RtlTcpPath,
    [string]$ListenAddress,
    [string]$WslDistribution = "Ubuntu-Docker",
    [ValidateRange(1, 65535)]
    [int]$Port = 1234
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localRtlTcp = Join-Path $repositoryRoot ".tools\rtl-sdr\v1.3.6\x64\rtl_tcp.exe"

if (-not $RtlTcpPath) {
    $RtlTcpPath = if (Test-Path -LiteralPath $localRtlTcp) {
        $localRtlTcp
    } else {
        "rtl_tcp.exe"
    }
}

$rtlTcp = Get-Command -Name $RtlTcpPath -ErrorAction SilentlyContinue
if (-not $rtlTcp) {
    throw @"
rtl_tcp.exe was not found.

Install the RTL-SDR Blog Windows driver and command-line tools, then either:
  1. add their folder to PATH, or
  2. run this script with -RtlTcpPath C:\path\to\rtl_tcp.exe
"@
}

if (-not $ListenAddress) {
    $defaultRoute = & wsl.exe -d $WslDistribution -- ip route show default
    if ($LASTEXITCODE -ne 0 -or $defaultRoute -notmatch 'default via (\d{1,3}(?:\.\d{1,3}){3})') {
        throw "Could not determine the Windows-side WSL address from '$WslDistribution'."
    }

    $ListenAddress = $Matches[1]
}

Write-Host "Starting rtl_tcp on ${ListenAddress}:${Port} at 433.92 MHz..."
Write-Warning "rtl_tcp is unencrypted. Stop it with Ctrl+C after testing and do not expose port $Port to the internet."

& $rtlTcp.Source `
    -a $ListenAddress `
    -p $Port `
    -f 433920000 `
    -s 250000 `
    -g 0
