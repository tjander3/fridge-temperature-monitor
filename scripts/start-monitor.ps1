[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker",
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dataDirectory = Join-Path $repositoryRoot "data"
$processFile = Join-Path $dataDirectory "monitor-processes.json"
$stopFile = Join-Path $dataDirectory "monitor.stop"
$hardwareId = "0bda:2838"
$supervisorModule = Join-Path $PSScriptRoot "monitor-supervisor.psm1"
Import-Module $supervisorModule -Force

$usbipd = Get-Command usbipd.exe -ErrorAction SilentlyContinue
$usbipdPath = if ($usbipd) {
    $usbipd.Source
} else {
    $installedUsbipd = "C:\Program Files\usbipd-win\usbipd.exe"
    if (Test-Path -LiteralPath $installedUsbipd) {
        $installedUsbipd
    } else {
        throw "usbipd-win is required for direct Docker USB access. See README.md."
    }
}

New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $processFile) {
    $priorProcesses = Get-Content -Raw -LiteralPath $processFile | ConvertFrom-Json
    if ($priorProcesses.usbipd_attach_pid) {
        Get-Process -Id $priorProcesses.usbipd_attach_pid -ErrorAction SilentlyContinue |
            Stop-Process -Force
    }
}

# usbipd's auto-attach process keeps WSL active and reconnects the SDR after a
# device reset. The one-time elevated bind is handled by setup-docker-usb.ps1.
& wsl.exe -d $WslDistribution -- true
if ($LASTEXITCODE -ne 0) {
    throw "WSL distribution '$WslDistribution' could not be started."
}

$usbAttach = $null
try {
    $usbAttach = Start-Process `
        -FilePath $usbipdPath `
        -ArgumentList @(
            "attach",
            "--wsl",
            "--auto-attach",
            "--hardware-id", $hardwareId
        ) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $dataDirectory "usbipd.stdout.log") `
        -RedirectStandardError (Join-Path $dataDirectory "usbipd.stderr.log") `
        -PassThru

    Start-Sleep -Seconds 3
    $usbAttach.Refresh()
    $attachExitCode = if ($usbAttach.HasExited) { $usbAttach.ExitCode } else { $null }
    $attachState = Get-UsbAttachLauncherState `
        -HasExited $usbAttach.HasExited `
        -ExitCode $attachExitCode
    if ($attachState -eq "failed") {
        throw "USB attachment failed. Check data\usbipd.stderr.log and run setup-docker-usb.ps1 if needed."
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
    Write-Host "Cold Storage Monitor is running entirely in Docker: http://localhost:8080"
    if ($attachState -eq "running") {
        Write-Host "USB auto-attach PID: $($usbAttach.Id)"
        @{ usbipd_attach_pid = $usbAttach.Id } |
            ConvertTo-Json |
            Set-Content -LiteralPath $processFile
    }
    else {
        Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
        Write-Host "USB auto-attach was handed off successfully to WSL."
    }

    if (-not $NoWait -and $attachState -eq "running") {
        Write-Host "Leave this process running. Press Ctrl+C to stop monitoring."
        while (-not $usbAttach.HasExited) {
            Start-Sleep -Seconds 5
            $usbAttach.Refresh()
        }
        if (Test-Path -LiteralPath $stopFile) {
            Remove-Item -LiteralPath $stopFile, $processFile -Force -ErrorAction SilentlyContinue
            Write-Host "Cold Storage Monitor stopped normally."
            return
        }
        if ($usbAttach.ExitCode -eq 0) {
            Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
            Write-Host "USB auto-attach was handed off successfully to WSL."
            return
        }
        throw "USB auto-attach stopped unexpectedly. Restart this script to resume monitoring."
    }
}
catch {
    if ($usbAttach -and -not $usbAttach.HasExited) {
        Stop-Process -Id $usbAttach.Id -Force
    }
    Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
    throw
}
