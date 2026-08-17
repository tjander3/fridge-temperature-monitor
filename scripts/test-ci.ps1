[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repositoryRoot

try {
    Write-Host "[1/5] Parsing PowerShell scripts"
    Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.ps1" | ForEach-Object {
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

    Write-Host "[2/5] Compiling Python"
    & python -m py_compile dashboard/app.py dashboard/test_app.py
    if ($LASTEXITCODE -ne 0) { throw "Python compilation failed." }

    Write-Host "[3/5] Running dashboard unit tests"
    & python -m unittest discover -s dashboard -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Python unit tests failed." }

    Write-Host "[4/5] Checking dashboard JavaScript syntax"
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

    Write-Host "[5/5] Validating Docker Compose"
    if ($IsWindows) {
        & wsl.exe -d Ubuntu-Docker --cd $repositoryRoot -- docker compose config --quiet
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
