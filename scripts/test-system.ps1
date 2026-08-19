[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker",
    [int[]]$SensorIds,
    [int]$FreshMinutes = 10,
    [int]$SensorWaitSeconds = 180,
    [switch]$SkipLiveSensors
)

$ErrorActionPreference = "Continue"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$results = [Collections.Generic.List[object]]::new()
if (-not $SensorIds) {
    $sensorConfiguration = Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot "dashboard\sensors.json") |
        ConvertFrom-Json
    $SensorIds = @($sensorConfiguration.PSObject.Properties.Name | ForEach-Object { [int]$_ })
}

function Add-Check {
    param([string]$Area, [string]$Check, [bool]$Passed, [string]$Detail)
    $script:results.Add([pscustomobject]@{
        Area = $Area
        Check = $Check
        Result = if ($Passed) { "PASS" } else { "FAIL" }
        Detail = $Detail
    })
}

function Invoke-Wsl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & wsl.exe -d $WslDistribution --cd $repositoryRoot -- @Arguments 2>&1
    [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($output -join "`n") }
}

Write-Host "Checking the live fridge-monitor system..."

$usbipdCommand = Get-Command usbipd.exe -ErrorAction SilentlyContinue
$usbipdPath = if ($usbipdCommand) { $usbipdCommand.Source } else { "C:\Program Files\usbipd-win\usbipd.exe" }
$usbipdInstalled = Test-Path -LiteralPath $usbipdPath
Add-Check "USB" "usbipd-win installed" $usbipdInstalled $(if ($usbipdInstalled) { $usbipdPath } else { "Run: winget install --interactive --exact dorssel.usbipd-win" })

if ($usbipdInstalled) {
    $usbList = & $usbipdPath list 2>&1 | Out-String
    $listed = $usbList -match "(?i)0bda:2838"
    $attached = $listed -and $usbList -match "(?im)^.*0bda:2838.*Attached.*$"
    Add-Check "USB" "RTL-SDR listed by Windows" $listed $(if ($listed) { "Hardware ID 0bda:2838 found" } else { "Unplug/replug the RTL-SDR and rerun" })
    Add-Check "USB" "RTL-SDR attached to WSL" $attached $(if ($attached) { "usbipd reports Attached" } else { "Run scripts/start-monitor.ps1 after one-time USB setup" })
}
else {
    Add-Check "USB" "RTL-SDR listed by Windows" $false "Cannot query without usbipd-win"
    Add-Check "USB" "RTL-SDR attached to WSL" $false "Cannot query without usbipd-win"
}

$wsl = Invoke-Wsl true
Add-Check "Runtime" "WSL distribution responds" ($wsl.ExitCode -eq 0) $(if ($wsl.ExitCode -eq 0) { $WslDistribution } else { $wsl.Output })

$usbInWsl = Invoke-Wsl udevadm info --export-db
$rtlUsbRecord = $usbInWsl.Output -split "(?:\r?\n){2,}" |
    Where-Object {
        $_ -match "(?m)^E: ID_VENDOR_ID=0bda$" -and
        $_ -match "(?m)^E: ID_MODEL_ID=2838$"
    } |
    Select-Object -First 1
$wslSeesUsb = $usbInWsl.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($rtlUsbRecord)
Add-Check "USB" "WSL sees RTL-SDR" $wslSeesUsb $(if ($wslSeesUsb) { "0bda:2838 found in WSL udev database" } else { "0bda:2838 absent from WSL udev database" })

$docker = Invoke-Wsl docker info --format '{{.ServerVersion}}'
Add-Check "Runtime" "Docker Engine responds" ($docker.ExitCode -eq 0) $(if ($docker.ExitCode -eq 0) { "Server $($docker.Output)" } else { $docker.Output })

$services = Invoke-Wsl docker compose ps --services --status running
$dashboardRunning = $services.Output -split "\s+" -contains "dashboard"
$decoderRunning = $services.Output -split "\s+" -contains "rtl433"
$notifierRunning = $services.Output -split "\s+" -contains "notifier"
Add-Check "Docker" "Dashboard container running" $dashboardRunning $services.Output
Add-Check "Docker" "Decoder container running" $decoderRunning $services.Output
Add-Check "Docker" "Notifier container running" $notifierRunning $services.Output

$notifierContainer = Invoke-Wsl docker compose ps -q notifier
$notifierHealth = if ($notifierContainer.ExitCode -eq 0 -and $notifierContainer.Output) {
    Invoke-Wsl docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' $notifierContainer.Output
} else {
    [pscustomobject]@{ ExitCode = 1; Output = "notifier container not found" }
}
Add-Check "Docker" "Notifier health check passes" ($notifierHealth.ExitCode -eq 0 -and $notifierHealth.Output -eq "healthy") $notifierHealth.Output

try {
    $health = Invoke-RestMethod "http://localhost:8080/api/health" -TimeoutSec 5
    Add-Check "Web" "Health API responds" ($health.status -eq "ok") "status=$($health.status)"
}
catch {
    Add-Check "Web" "Health API responds" $false $_.Exception.Message
}

try {
    $page = Invoke-WebRequest "http://localhost:8080/" -TimeoutSec 5
    $validPage = $page.StatusCode -eq 200 -and
        $page.Content -match "Cold Storage Monitor" -and
        $page.Content -match "Temperature history"
    Add-Check "Web" "Dashboard UI loads" $validPage "HTTP $($page.StatusCode); expected page landmarks present=$validPage"
}
catch {
    Add-Check "Web" "Dashboard UI loads" $false $_.Exception.Message
}

$sqlCode = @'
import sqlite3
connection = sqlite3.connect('/data/fridge-monitor.db')
assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
before = connection.total_changes
connection.execute('BEGIN')
connection.execute('CREATE TABLE IF NOT EXISTS _system_test(value TEXT)')
connection.execute("INSERT INTO _system_test VALUES ('probe')")
assert connection.total_changes > before
connection.rollback()
print('integrity=ok write=ok rollback=ok')
'@
$sql = Invoke-Wsl docker compose exec -T dashboard python -c $sqlCode
Add-Check "SQL" "SQLite integrity/write/rollback" ($sql.ExitCode -eq 0 -and $sql.Output -match "integrity=ok") $sql.Output

$decoderLogs = Invoke-Wsl docker compose logs --no-color --tail 150 rtl433
$radioOpened = $decoderLogs.Output -match "(?i)(Found 1 device|Using device 0|Rafael Micro|R820T)"
$radioDecoded = $decoderLogs.Output -match '"model"\s*:\s*"Acurite-986"'
$radioHealthy = $decoderLogs.ExitCode -eq 0 -and ($radioOpened -or $radioDecoded)
$radioDetail = if ($radioOpened) {
    "Receiver initialization found in rtl_433 logs"
}
elseif ($radioDecoded) {
    "Recent decoded AcuRite event found in rtl_433 logs"
}
else {
    $decoderLogs.Output
}
Add-Check "Radio" "rtl_433 receiver is active" $radioHealthy $radioDetail

if (-not $SkipLiveSensors) {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($SensorWaitSeconds)
    $sensorDetails = @{}
    do {
        try {
            $data = Invoke-RestMethod "http://localhost:8080/api/readings?hours=24" -TimeoutSec 5
            foreach ($sensorId in $SensorIds) {
                $sensor = $data.sensors | Where-Object { $_.id -eq $sensorId } | Select-Object -First 1
                if ($sensor -and $sensor.latest) {
                    $observedValue = $sensor.latest.observed_at
                    $observed = if ($observedValue -is [DateTime]) {
                        [DateTimeOffset]::new($observedValue)
                    }
                    else {
                        [DateTimeOffset]::Parse(
                            [string]$observedValue,
                            [Globalization.CultureInfo]::InvariantCulture,
                            [Globalization.DateTimeStyles]::AssumeUniversal -bor
                                [Globalization.DateTimeStyles]::AdjustToUniversal
                        )
                    }
                    $age = [DateTimeOffset]::UtcNow - $observed
                    if ($age.TotalMinutes -ge -1 -and $age.TotalMinutes -le $FreshMinutes) {
                        $sensorDetails[$sensorId] = "$($sensor.name): $($sensor.latest.temperature_f) F, age $([math]::Round($age.TotalMinutes, 1)) min"
                    }
                }
            }
        }
        catch { }
        if ($sensorDetails.Count -lt $SensorIds.Count) { Start-Sleep -Seconds 5 }
    } while ($sensorDetails.Count -lt $SensorIds.Count -and [DateTimeOffset]::UtcNow -lt $deadline)

    foreach ($sensorId in $SensorIds) {
        $fresh = $sensorDetails.ContainsKey($sensorId)
        Add-Check "Sensors" "Sensor $sensorId has a fresh reading" $fresh $(if ($fresh) { $sensorDetails[$sensorId] } else { "No reading within $FreshMinutes minutes after waiting up to $SensorWaitSeconds seconds" })
    }
}

Write-Host ""
$results | Format-Table -AutoSize -Wrap
$failed = @($results | Where-Object Result -eq "FAIL")
Write-Host "$($results.Count - $failed.Count)/$($results.Count) checks passed."
if ($failed.Count -gt 0) { exit 1 }
