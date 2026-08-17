[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker",
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$rtlTcpPath = Join-Path $repositoryRoot ".tools\rtl-sdr\v1.3.6\x64\rtl_tcp.exe"
$dataDirectory = Join-Path $repositoryRoot "data"
$processFile = Join-Path $dataDirectory "monitor-processes.json"
$stopFile = Join-Path $dataDirectory "monitor.stop"

if (-not (Test-Path -LiteralPath $rtlTcpPath)) {
    throw "rtl_tcp.exe was not found at '$rtlTcpPath'. See README.md for setup instructions."
}

$defaultRoute = & wsl.exe -d $WslDistribution -- ip route show default
if ($LASTEXITCODE -ne 0 -or $defaultRoute -notmatch 'default via (\d{1,3}(?:\.\d{1,3}){3})') {
    throw "Could not determine the Windows-side WSL address from '$WslDistribution'."
}
$listenAddress = $Matches[1]

# The Windows rtl_tcp build cannot accept a second client after a disconnect.
# Always replace any prior instance when starting the complete monitor.
Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $processFile) {
    $priorProcesses = Get-Content -Raw -LiteralPath $processFile | ConvertFrom-Json
    foreach ($prior in @($priorProcesses.rtl_tcp_pid, $priorProcesses.wsl_keepalive_pid)) {
        if ($prior) {
            Get-Process -Id $prior -ErrorAction SilentlyContinue | Stop-Process -Force
        }
    }
}

# A live wsl.exe client keeps the distribution and its systemd services alive.
$wslKeepAlive = Start-Process `
    -FilePath "wsl.exe" `
    -ArgumentList @("-d", $WslDistribution, "--", "sleep", "infinity") `
    -WindowStyle Hidden `
    -PassThru

$rtlProcess = $null
try {
    $rtlProcess = Start-Process `
        -FilePath $rtlTcpPath `
        -ArgumentList @(
            "-a", $listenAddress,
            "-p", "1234",
            "-f", "433920000",
            "-s", "250000",
            "-g", "0"
        ) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $dataDirectory "rtl_tcp.stdout.log") `
        -RedirectStandardError (Join-Path $dataDirectory "rtl_tcp.stderr.log") `
        -PassThru

    Start-Sleep -Seconds 2
    if ($rtlProcess.HasExited) {
        throw "rtl_tcp exited during startup. Check data\rtl_tcp.stderr.log."
    }
    if ($wslKeepAlive.HasExited) {
        throw "The WSL keepalive process exited during startup."
    }

    & wsl.exe -d $WslDistribution -u root -- systemctl start docker
    if ($LASTEXITCODE -ne 0) {
        throw "Docker could not be started in '$WslDistribution'."
    }

    & wsl.exe -d $WslDistribution --cd $repositoryRoot -- bash ./scripts/start-decoder.sh
    if ($LASTEXITCODE -ne 0) {
        throw "The Docker monitor stack did not start."
    }

    Write-Host ""
    Write-Host "Cold Storage Monitor is running: http://localhost:8080"
    Write-Host "Windows radio bridge PID: $($rtlProcess.Id)"
    Write-Host "WSL keepalive PID: $($wslKeepAlive.Id)"

    @{
        rtl_tcp_pid = $rtlProcess.Id
        wsl_keepalive_pid = $wslKeepAlive.Id
    } | ConvertTo-Json | Set-Content -LiteralPath $processFile

    if (-not $NoWait) {
        Write-Host "Leave this process running. Press Ctrl+C to stop the radio bridge."
        while (-not $rtlProcess.HasExited -and -not $wslKeepAlive.HasExited) {
            Start-Sleep -Seconds 5
            $rtlProcess.Refresh()
            $wslKeepAlive.Refresh()
        }
        if (Test-Path -LiteralPath $stopFile) {
            Remove-Item -LiteralPath $stopFile, $processFile -Force -ErrorAction SilentlyContinue
            Write-Host "Cold Storage Monitor stopped normally."
            return
        }
        throw "A required monitor process stopped. Restart this script to resume monitoring."
    }
}
catch {
    if ($rtlProcess -and -not $rtlProcess.HasExited) {
        Stop-Process -Id $rtlProcess.Id -Force
    }
    if (-not $wslKeepAlive.HasExited) {
        Stop-Process -Id $wslKeepAlive.Id -Force
    }
    Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
    throw
}
