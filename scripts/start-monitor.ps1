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
$monitorProcesses = @{}

function Save-MonitorProcesses {
    if ($monitorProcesses.Count -eq 0) {
        Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
        return
    }

    $monitorProcesses |
        ConvertTo-Json |
        Set-Content -LiteralPath $processFile
}

function Stop-RecordedProcess {
    param(
        [object]$ProcessId,
        [string[]]$ExpectedNames
    )

    if (-not $ProcessId) {
        return
    }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -in $ExpectedNames) {
        Stop-Process -Id $process.Id -Force
    }
}

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
    Stop-RecordedProcess $priorProcesses.usbipd_attach_pid @("usbipd")
    Stop-RecordedProcess $priorProcesses.lan_proxy_pid @("python", "pythonw")
    Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
}

# usbipd's auto-attach process keeps WSL active and reconnects the SDR after a
# device reset. The one-time elevated bind is handled by setup-docker-usb.ps1.
& wsl.exe -d $WslDistribution -- true
if ($LASTEXITCODE -ne 0) {
    throw "WSL distribution '$WslDistribution' could not be started."
}

$usbAttach = $null
$lanProxy = $null
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
        $monitorProcesses.usbipd_attach_pid = $usbAttach.Id
    }
    else {
        Write-Host "USB auto-attach was handed off successfully to WSL."
    }

    $lanAddress = Get-PreferredLanAddress
    if ($lanAddress) {
        $lanDashboardUri = "http://${lanAddress}:8080/"
        $lanDashboardAvailable = try {
            (Invoke-RestMethod -Uri "${lanDashboardUri}api/health" -TimeoutSec 2).status -eq "ok"
        }
        catch {
            $false
        }

        if (-not $lanDashboardAvailable) {
            $python = Get-Command pythonw.exe -ErrorAction SilentlyContinue
            if (-not $python) {
                $python = Get-Command python.exe -ErrorAction Stop
            }
            $lanProxyScript = Join-Path $PSScriptRoot "lan_proxy.py"
            $lanProxyLog = Join-Path $dataDirectory "lan-proxy.log"
            $quotedLanProxyScript = '"{0}"' -f $lanProxyScript
            $quotedLanProxyLog = '"{0}"' -f $lanProxyLog
            $lanProxy = Start-Process `
                -FilePath $python.Source `
                -ArgumentList @(
                    $quotedLanProxyScript,
                    "--listen-host", $lanAddress,
                    "--listen-port", "8080",
                    "--target-host", "127.0.0.1",
                    "--target-port", "8080",
                    "--log-file", $quotedLanProxyLog
                ) `
                -WindowStyle Hidden `
                -PassThru
            Start-Sleep -Seconds 1
            $lanProxy.Refresh()
            if ($lanProxy.HasExited) {
                throw "The LAN dashboard relay failed to start. Check data\lan-proxy.log."
            }
            $lanDashboardAvailable = try {
                (Invoke-RestMethod -Uri "${lanDashboardUri}api/health" -TimeoutSec 5).status -eq "ok"
            }
            catch {
                $false
            }
            if (-not $lanDashboardAvailable) {
                throw "The LAN dashboard relay started but did not answer at $lanDashboardUri."
            }
            $monitorProcesses.lan_proxy_pid = $lanProxy.Id
            Write-Host "LAN dashboard relay PID: $($lanProxy.Id)"
        }

        Write-Host "Same-Wi-Fi dashboard: $lanDashboardUri"
    }
    else {
        Write-Warning "No active LAN address with a default gateway was found; same-Wi-Fi access was not started."
    }

    Save-MonitorProcesses

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
            $monitorProcesses.Remove("usbipd_attach_pid") | Out-Null
            Save-MonitorProcesses
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
    if ($lanProxy -and -not $lanProxy.HasExited) {
        Stop-Process -Id $lanProxy.Id -Force
    }
    Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
    throw
}
