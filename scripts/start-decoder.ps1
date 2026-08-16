[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

docker compose version *> $null
if ($LASTEXITCODE -eq 0) {
    docker compose up rtl433
    exit $LASTEXITCODE
}

if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
    docker-compose up rtl433
    exit $LASTEXITCODE
}

throw "Docker Compose was not found. Install or update Docker Desktop, then try again."
