function Get-UsbAttachLauncherState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [bool]$HasExited,

        [AllowNull()]
        [Nullable[int]]$ExitCode
    )

    if (-not $HasExited) {
        return "running"
    }

    # usbipd-win 5.x can hand --auto-attach off to a WSL helper and then exit
    # successfully. The WSL helper is the long-running process in that case.
    if ($ExitCode -eq 0) {
        return "handed-off"
    }

    return "failed"
}

function Get-PreferredLanAddress {
    [CmdletBinding()]
    param()

    $candidates = foreach ($networkInterface in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
        if ($networkInterface.OperationalStatus -ne [Net.NetworkInformation.OperationalStatus]::Up) {
            continue
        }
        if ($networkInterface.NetworkInterfaceType -in @(
                [Net.NetworkInformation.NetworkInterfaceType]::Loopback,
                [Net.NetworkInformation.NetworkInterfaceType]::Tunnel
            )) {
            continue
        }

        $properties = $networkInterface.GetIPProperties()
        $hasIpv4Gateway = @($properties.GatewayAddresses).Where({
            $_.Address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork
        }).Count -gt 0
        if (-not $hasIpv4Gateway) {
            continue
        }

        foreach ($unicast in $properties.UnicastAddresses) {
            if ($unicast.Address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
                continue
            }
            $address = $unicast.Address.ToString()
            if ($address -like "169.254.*") {
                continue
            }
            [pscustomobject]@{
                Address = $address
                Priority = if ($networkInterface.NetworkInterfaceType -eq [Net.NetworkInformation.NetworkInterfaceType]::Wireless80211) { 0 } else { 1 }
            }
        }
    }

    return $candidates |
        Sort-Object Priority, Address |
        Select-Object -ExpandProperty Address -First 1
}

Export-ModuleMember -Function Get-UsbAttachLauncherState, Get-PreferredLanAddress
