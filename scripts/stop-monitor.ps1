[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$processFile = Join-Path $repositoryRoot "data\monitor-processes.json"
$stopFile = Join-Path $repositoryRoot "data\monitor.stop"

New-Item -ItemType File -Path $stopFile -Force | Out-Null

& wsl.exe -d $WslDistribution --cd $repositoryRoot -- docker compose down
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose could not stop the monitor stack."
}

if (Test-Path -LiteralPath $processFile) {
    $monitorProcesses = Get-Content -Raw -LiteralPath $processFile | ConvertFrom-Json
    if ($monitorProcesses.usbipd_attach_pid) {
        $process = Get-Process -Id $monitorProcesses.usbipd_attach_pid -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -eq "usbipd") {
            Stop-Process -Id $process.Id -Force
        }
    }
    Remove-Item -LiteralPath $processFile -Force
}

Write-Host "Cold Storage Monitor stopped. Docker retained the SQL database volume."
