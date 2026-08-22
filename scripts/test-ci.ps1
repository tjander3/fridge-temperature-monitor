[CmdletBinding()]
param(
    [string]$WslDistribution = "Ubuntu-Docker"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repositoryRoot

try {
    Write-Host "[1/6] Parsing PowerShell scripts and modules"
    Get-ChildItem -LiteralPath $PSScriptRoot -File |
        Where-Object Extension -in ".ps1", ".psm1" |
        ForEach-Object {
            $tokens = $null
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $_.FullName,
                [ref]$tokens,
                [ref]$errors
            ) | Out-Null
            if ($errors.Count -gt 0) {
                throw "PowerShell parse error in $($_.Name): $($errors[0].Message)"
            }
        }

    Write-Host "[2/6] Testing the Windows startup supervisor"
    & (Join-Path $PSScriptRoot "test-startup-supervisor.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Startup supervisor tests failed." }

    Write-Host "[3/6] Compiling Python"
    & python -m py_compile dashboard/app.py dashboard/notifier.py dashboard/test_app.py dashboard/test_notifier.py scripts/sqlite_dump.py scripts/backup_database.py scripts/restore_database.py scripts/setup_backups.py scripts/test_backups.py scripts/lan_proxy.py scripts/test_lan_proxy.py
    if ($LASTEXITCODE -ne 0) { throw "Python compilation failed." }

    Write-Host "[4/6] Running dashboard unit tests"
    & python -m unittest discover -s dashboard -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Python unit tests failed." }
    & python -m unittest discover -s scripts -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Backup unit tests failed." }

    Write-Host "[5/6] Checking dashboard JavaScript syntax"
    $html = Get-Content -Raw -LiteralPath "dashboard/static/index.html"
    $match = [regex]::Match($html, "(?s)<script>(.*?)</script>")
    if (-not $match.Success) { throw "Dashboard inline script was not found." }
    $temporaryJavaScript = Join-Path ([IO.Path]::GetTempPath()) "fridge-dashboard-$PID.js"
    try {
        [IO.File]::WriteAllText($temporaryJavaScript, $match.Groups[1].Value)
        & node --check $temporaryJavaScript
        if ($LASTEXITCODE -ne 0) { throw "Dashboard JavaScript syntax check failed." }
    }
    finally {
        Remove-Item -LiteralPath $temporaryJavaScript -Force -ErrorAction SilentlyContinue
    }

    Write-Host "[6/6] Validating Docker Compose"
    if ($IsWindows) {
        & wsl.exe -d $WslDistribution --cd $repositoryRoot -- docker compose config --quiet
    }
    else {
        & docker compose config --quiet
    }
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose validation failed." }

    Write-Host "All commit-time checks passed."
}
finally {
    Pop-Location
}
