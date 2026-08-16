[CmdletBinding()]
param(
    [string]$RtlTcpPath = "rtl_tcp.exe",
    [string]$ListenAddress = "0.0.0.0",
    [ValidateRange(1, 65535)]
    [int]$Port = 1234
)

$ErrorActionPreference = "Stop"

$rtlTcp = Get-Command -Name $RtlTcpPath -ErrorAction SilentlyContinue
if (-not $rtlTcp) {
    throw @"
rtl_tcp.exe was not found.

Install the RTL-SDR Blog Windows driver and command-line tools, then either:
  1. add their folder to PATH, or
  2. run this script with -RtlTcpPath C:\path\to\rtl_tcp.exe
"@
}

Write-Host "Starting rtl_tcp on ${ListenAddress}:${Port} at 433.92 MHz..."
Write-Warning "rtl_tcp is unencrypted. Stop it with Ctrl+C after testing and do not expose port $Port to the internet."

& $rtlTcp.Source `
    -a $ListenAddress `
    -p $Port `
    -f 433920000 `
    -s 250000
