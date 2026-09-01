[CmdletBinding()]
param(
    [int]$ListenPort = 8080,
    [int]$TargetPort = 8080
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dataDirectory = Join-Path $repositoryRoot "data"
$supervisorModule = Join-Path $PSScriptRoot "monitor-supervisor.psm1"
Import-Module $supervisorModule -Force

$lanAddress = Get-PreferredLanAddress
if (-not $lanAddress) {
    throw "No active LAN address with a default gateway was found."
}

$existing = try {
    (Invoke-RestMethod -Uri "http://${lanAddress}:$ListenPort/api/health" -TimeoutSec 2).status -eq "ok"
}
catch {
    $false
}
if ($existing) {
    Write-Host "The fridge LAN relay is already available at http://${lanAddress}:$ListenPort/."
    exit 0
}

New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$python = Get-Command python.exe -ErrorAction Stop
$relayScript = Join-Path $PSScriptRoot "lan_proxy.py"
$logFile = Join-Path $dataDirectory "lan-proxy.log"

Write-Host "Relaying http://${lanAddress}:$ListenPort/ to the local fridge monitor for Home Assistant."
& $python.Source $relayScript `
    --listen-host $lanAddress `
    --listen-port $ListenPort `
    --target-host 127.0.0.1 `
    --target-port $TargetPort `
    --log-file $logFile
exit $LASTEXITCODE
