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
    $expectedProcesses = @(
        @{ Id = $monitorProcesses.rtl_tcp_pid; Name = "rtl_tcp" },
        @{ Id = $monitorProcesses.wsl_keepalive_pid; Name = "wsl" }
    )
    foreach ($expected in $expectedProcesses) {
        $process = Get-Process -Id $expected.Id -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -eq $expected.Name) {
            Stop-Process -Id $process.Id -Force
        }
    }
    Remove-Item -LiteralPath $processFile -Force
} else {
    Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
}
Write-Host "Cold Storage Monitor stopped. Stored readings remain in data\fridge-monitor.db."
