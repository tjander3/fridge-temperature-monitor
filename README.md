# Fridge Temperature Monitor

Local refrigerator and freezer temperature history using an RTL-SDR Blog V3, two AcuRite 00986M sensors, Docker, SQLite, and a small web dashboard.

The receiver was proven with both sensors on August 17, 2026. The current milestone stores readings and plots them at [http://localhost:8080](http://localhost:8080).

## Architecture

Docker Engine runs inside the `Ubuntu-Docker` WSL2 distribution without Docker Desktop. The USB receiver remains attached to Windows:

```text
AcuRite sensors
      |
      | 433.92 MHz
      v
RTL-SDR USB -> rtl_tcp on Windows -> rtl_433 container
                                           |
                                           | JSON over private UDP
                                           v
                                  dashboard container
                                  SQLite + local website
```

`rtl_433` enables only protocol 41 for the AcuRite 00986M. It sends events to the dashboard using its syslog-compatible UDP output, which its upstream documentation recommends over a process pipe for a stable integration. Repeated RF packets are deduplicated before storage.

## Sensors

| Sensor ID | Channel | Role | Initial reading | Monitoring |
| --- | --- | --- | ---: | --- |
| `41880` | `2F` | Mini fridge; temporarily on the desk | 71°F | Setup mode |
| `52572` | `1R` | Basement freezer | -11°F | Active |

The freezer is considered in range at 0°F or below. The mini fridge will use a 32–40°F range after it is installed. These limits follow FDA cold-storage guidance, but this hobby monitor is not a substitute for checking food safety after an outage or prolonged warm period.

## Start and stop

Open PowerShell in this repository and run:

```powershell
.\scripts\start-monitor.ps1
```

The script:

1. Detects the current Windows/WSL bridge address.
2. Starts `rtl_tcp` on Windows for USB access.
3. Keeps one lightweight WSL session alive so its services do not suspend.
4. Starts Docker Engine and the Compose services inside WSL.
5. Supervises both the Windows radio bridge and WSL session.

Leave the PowerShell process running, then open [http://localhost:8080](http://localhost:8080). The page refreshes every 30 seconds, while each sensor normally transmits about every two minutes.

To stop everything from another PowerShell window:

```powershell
.\scripts\stop-monitor.ps1
```

Readings remain in `data\fridge-monitor.db` when the monitor stops.

## Start automatically with Windows

The monitor can start at sign-in through a Windows Scheduled Task. Install it once from PowerShell:

```powershell
.\scripts\install-startup-task.ps1
```

This only installs the task; it does not change Windows power settings. The task starts at the next sign-in and restarts the supervisor up to three times if it fails. To start it immediately:

```powershell
Start-ScheduledTask -TaskName "Fridge Temperature Monitor"
```

To remove it later:

```powershell
Unregister-ScheduledTask -TaskName "Fridge Temperature Monitor"
```

Windows must stay awake for continuous monitoring. Sleeping, shutting down, or signing out stops the Windows radio bridge. Configure the desktop not to sleep while plugged in if continuous history is important.

## Dashboard and data

The local dashboard provides:

- latest temperature, battery state, and last contact;
- 6-hour, 24-hour, 7-day, and 30-day charts;
- stale-sensor detection after 10 minutes;
- warm, cold, and low-battery status;
- SQLite persistence across container restarts.

The dashboard listens only on `127.0.0.1`, so it is available on this computer but not exposed to the home network. `rtl_tcp` is unencrypted and must never be port-forwarded through the router.

When sensor `41880` moves into the mini fridge, change its `monitoring` value to `true` in `dashboard/sensors.json`, then rerun `start-monitor.ps1`.

To back up the history, stop the monitor briefly and copy:

```text
data\fridge-monitor.db
```

At one reading every two minutes per sensor, plan on roughly 100–250 MB of SQLite growth per year. A retention or downsampling job can be added later if long-term size becomes important.

## Power strategy

Using the 2026 EIA U.S. residential average of 18.2 cents per kWh, one continuous watt costs about $1.59 per year:

```text
annual cost = watts / 1000 × 8760 hours × electricity price per kWh
```

| Scenario | Estimated continuous power | Estimated annual cost |
| --- | ---: | ---: |
| Incremental SDR + monitoring load on an already-on desktop | 5–15 W | $8–$24 |
| Desktop kept on only for this project | 40–100 W | $64–$159 |
| Future Raspberry Pi or low-power mini PC | 5–10 W | $8–$16 |

These are planning ranges, not measurements. A plug-in power meter is the best way to measure this desktop both before and after starting the monitor. If the desktop would otherwise sleep, prototype here and later move the same containers and SDR to a Raspberry Pi or low-power mini PC.

## Manual radio test

For troubleshooting, run the two halves separately in two PowerShell windows:

```powershell
.\scripts\start-rtl-tcp.ps1
```

```powershell
.\scripts\start-decoder.ps1
```

The first process owns the Windows USB receiver. The second builds and starts the Docker stack. The included antenna should have both arms extended to roughly 17 cm and oriented vertically; leave the bias tee off.

## Development checks

The dashboard uses only the Python standard library. Run its tests without installing dependencies:

```powershell
python -m unittest discover -s dashboard -p "test_*.py" -v
```

Validate the Compose configuration inside WSL:

```powershell
.\scripts\start-decoder.ps1
```

## References

- [`rtl_433` operation and output documentation](https://github.com/merbanan/rtl_433/blob/master/docs/OPERATION.md)
- [`rtl_433` Docker images](https://github.com/hertzg/rtl_433_docker)
- [AcuRite 986 decoder source](https://github.com/merbanan/rtl_433/blob/master/src/devices/acurite_986.c)
- [FDA refrigerator and freezer temperature guidance](https://www.fda.gov/food/buy-store-serve-safe-food/refrigerator-thermometers-cold-facts-about-food-safety)
- [EIA Short-Term Energy Outlook](https://www.eia.gov/outlooks/steo/)
