[CmdletBinding()]
param(
    [string]$RtlTcpPath = "rtl_tcp.exe"
)

$checks = @(
    [pscustomobject]@{
        Requirement = "Docker CLI"
        Found = [bool](Get-Command docker -ErrorAction SilentlyContinue)
        Detail = "Required to run rtl_433"
    },
    [pscustomobject]@{
        Requirement = "Docker Compose"
        Found = $false
        Detail = "Required to start the decoder"
    },
    [pscustomobject]@{
        Requirement = "rtl_tcp"
        Found = [bool](Get-Command $RtlTcpPath -ErrorAction SilentlyContinue)
        Detail = "Required for Windows USB access"
    }
)

if ($checks[0].Found) {
    docker compose version *> $null
    $checks[1].Found = ($LASTEXITCODE -eq 0)
}

if (-not $checks[1].Found -and (Get-Command docker-compose -ErrorAction SilentlyContinue)) {
    docker-compose version *> $null
    $checks[1].Found = ($LASTEXITCODE -eq 0)
    if ($checks[1].Found) {
        $checks[1].Detail = "Found legacy docker-compose"
    }
}

$checks | Format-Table -AutoSize

if ($checks.Found -contains $false) {
    Write-Error "One or more prerequisites are missing. See README.md for setup instructions."
    exit 1
}

Write-Host "All prerequisites were found."
