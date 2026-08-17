[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker"
)

$ErrorActionPreference = "Stop"

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
    throw "WSL was not found. Install WSL2 and the Ubuntu-Docker distribution first."
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

& $wsl.Source -d $WslDistribution -u root -- systemctl start docker
if ($LASTEXITCODE -ne 0) {
    throw "Docker could not be started in the WSL distribution '$WslDistribution'."
}

& $wsl.Source -d $WslDistribution -- docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is not running in the WSL distribution '$WslDistribution'."
}

& $wsl.Source -d $WslDistribution --cd $repositoryRoot -- bash ./scripts/start-decoder.sh
exit $LASTEXITCODE
