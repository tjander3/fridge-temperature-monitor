[CmdletBinding()]
param(
    [string]$DisplayName = "Fridge Temperature Monitor (LAN)",
    [ValidateRange(1, 65535)]
    [int]$ListenPort = 8080
)

$ErrorActionPreference = "Stop"
$principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an Administrator PowerShell window."
}

$rule = Get-NetFirewallRule -DisplayName $DisplayName -ErrorAction SilentlyContinue
if (-not $rule) {
    $rule = New-NetFirewallRule `
        -DisplayName $DisplayName `
        -Description "Allow the dashboard from the local subnet on TCP $ListenPort." `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $ListenPort `
        -LocalAddress Any `
        -RemoteAddress LocalSubnet `
        -Profile Any
}
else {
    $rule | Set-NetFirewallRule `
        -Enabled True `
        -Direction Inbound `
        -Action Allow `
        -Profile Any | Out-Null
    $rule | Get-NetFirewallAddressFilter |
        Set-NetFirewallAddressFilter -LocalAddress Any -RemoteAddress LocalSubnet |
        Out-Null
    $rule | Get-NetFirewallPortFilter |
        Set-NetFirewallPortFilter -Protocol TCP -LocalPort $ListenPort |
        Out-Null
}

Write-Host "Same-LAN access is allowed on TCP $ListenPort from LocalSubnet."
Write-Host "The rule follows DHCP address and Ethernet/Wi-Fi interface changes."
