# Fridge Temperature Monitor

[![Tests](https://github.com/tjander3/fridge-temperature-monitor/actions/workflows/tests.yml/badge.svg)](https://github.com/tjander3/fridge-temperature-monitor/actions/workflows/tests.yml)

Local refrigerator and freezer temperature history using an RTL-SDR receiver, AcuRite 00986M sensors, Docker, SQLite, and a small web dashboard.

Current follow-up work is tracked in [TODO.md](TODO.md).

> **Project status:** working prototype. RF reception, AcuRite decoding, storage, the dashboard, notifications, and the direct-USB all-Docker runtime were proven with two live sensors. The complete live system suite passes 16/16 checks. This is a hobby monitor, not a certified food-safety device.

## Features

- decodes AcuRite 00986M fridge/freezer sensors on 433.92 MHz;
- stores deduplicated readings in SQLite;
- displays current temperature, battery state, last contact, and history charts;
- detects stale, warm, cold, and low-battery states;
- sends persistent, duplicate-suppressed alerts through SMTP email;
- lets users select persistent food, freezer, beverage, wine, custom, or readings-only alert profiles from the dashboard;
- can expose the dashboard to the same private LAN through a restricted Windows firewall rule;
- includes fast CI tests, full-history secret scanning, and a separate live hardware/system test suite;
- persists data in a Docker-managed volume.

## Requirements

### Hardware

- an RTL-SDR receiver compatible with `rtl_433`;
- a 433 MHz antenna;
- one or more AcuRite 00986M wireless fridge/freezer sensors.

The original setup uses an RTL-SDR Blog V3 and two AcuRite sensors, but every
installation supplies its own ignored sensor configuration.

### Software

- Windows with WSL2 and a systemd-enabled Ubuntu distribution;
- [Docker Engine and the Compose plugin installed inside Ubuntu](https://docs.docker.com/engine/install/ubuntu/); no Docker Desktop is required;
- [`usbipd-win`](https://learn.microsoft.com/en-us/windows/wsl/connect-usb) for forwarding the RTL-SDR into WSL;
- PowerShell 7, Python, and Node.js for running all development checks locally.

The scripts default to a WSL distribution named `Ubuntu-Docker`. If yours has another name, pass it explicitly, for example `-WslDistribution Ubuntu`, to the PowerShell scripts.

## Architecture

```text
AcuRite sensors
      |
      | 433.92 MHz
      v
RTL-SDR USB
      |
      | usbipd-win forwards the physical device to WSL
      v
Docker: rtl_433 -> JSON over private UDP -> dashboard + SQLite
                                                 |       |
                                                 |       v
                                                 |   notifier -> email
                                                 v
                                  named volume + localhost:8080
```

There is no Windows `rtl_tcp` process, host database service, or Docker Desktop dependency. The SQLite engine runs inside the dashboard container, and its database lives in the Docker-managed `fridge-temperature-monitor-data` volume.

The decoder uses the third-party `hertzg/rtl_433:25.12` image. Its [Dockerfiles and publishing workflow are public](https://github.com/hertzg/rtl_433_docker), and the official `rtl_433` project links to those images. The tag corresponds to the upstream 25.12 release; pinning a verified image digest remains a release-hardening task.

## Configure sensors

| Sensor ID | Channel | Role | Default profile | Alert range |
| --- | --- | --- | --- | ---: |
| `10001` | `1R` | Drinks fridge | Drinks / beer | 34–45°F |
| `10002` | `2F` | Food freezer | Freezer | -20–0°F |

FDA guidance sets a food refrigerator at 40°F or below and a freezer at 0°F. The lower bounds help detect accidental over-cooling; the drinks and wine presets are quality preferences rather than food-safety limits. This hobby monitor is not a substitute for checking food safety after an outage or prolonged warm period.

The table contains fictitious example IDs. Create the ignored local files before
starting the monitor:

```powershell
Copy-Item .env.example .env
Copy-Item dashboard/sensors.example.json dashboard/sensors.local.json
```

Edit `dashboard/sensors.local.json` with the IDs reported by `rtl_433` and keep
`SENSORS_FILE=./dashboard/sensors.local.json` in `.env`. Each entry supports a
display name, channel, stable chart/card color, monitoring state, minimum and
maximum temperatures, stale-reading timeout, and an optional note. Unknown
AcuRite 986 readings are still stored, but a new sensor ID is displayed with a
generated name only after two distinct readings. This keeps one-off RF decoding
errors off the dashboard while still allowing real sensors to be discovered
before adding them to the file.

Sensor IDs are broadcast over unencrypted 433 MHz radio. They are not
credentials, but the local file is ignored so a published fork does not reveal
installation-specific device identifiers or room labels.

## One-time USB setup

Install WSL, enable systemd if your distribution does not already use it, and install Docker Engine inside that distribution using the official links above. Confirm `docker compose version` works inside WSL.

WSL cannot access a Windows USB device by itself. Install Microsoft's recommended `usbipd-win` helper from an Administrator PowerShell window:

```powershell
winget install --interactive --exact dorssel.usbipd-win
```

Then run this repository's setup script:

```powershell
.\scripts\setup-docker-usb.ps1
```

Approve the Administrator prompt. This shares only hardware ID `0bda:2838`, the RTL-SDR. Sharing persists across reboots; attaching does not. The normal monitor launcher handles attachment and reattachment automatically without Administrator rights.

While attached to WSL, the receiver is unavailable to Windows radio programs. Stop the monitor before intentionally returning the device to Windows.

Check the remaining prerequisites with:

```powershell
.\scripts\check-prerequisites.ps1
```

Pass `-WslDistribution <name>` when the distribution is not named `Ubuntu-Docker`.

## Start and stop

Open PowerShell in this repository and run:

```powershell
.\scripts\start-monitor.ps1
```

The launcher:

1. Starts an auto-attaching USB/IP session for the RTL-SDR.
2. Keeps WSL active for as long as monitoring runs.
3. Starts Docker Engine and the Compose services.
4. Supervises USB attachment and reconnects after a device reset.

Leave the PowerShell process running, then open [http://localhost:8080](http://localhost:8080). The page refreshes every 30 seconds, while each sensor normally transmits about every two minutes.

To stop everything from another PowerShell window:

```powershell
.\scripts\stop-monitor.ps1
```

Docker retains all readings in its named SQL volume when the containers stop or rebuild.

## View the dashboard from another device on the same Wi-Fi

The Compose configuration binds the dashboard to loopback TCP port `8080`.
WSL's default Windows integration forwards that service to `127.0.0.1` on the
Windows host. `scripts/start-monitor.ps1` also starts a user-level relay bound
only to the active Windows LAN address. A narrowly scoped firewall rule is
needed once for a phone or tablet on the same LAN.

First, run `ipconfig` and note the IPv4 address and interface name for the
active Wi-Fi connection. Then open **PowerShell as Administrator**, replace
the two example values below, and run:

```powershell
$lanAddress = "192.168.1.50"
$interfaceAlias = "Wi-Fi"

New-NetFirewallRule `
  -DisplayName "Fridge Temperature Monitor (LAN)" `
  -Description "Allow the dashboard from the local subnet on TCP 8080." `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8080 `
  -LocalAddress $lanAddress `
  -RemoteAddress LocalSubnet `
  -InterfaceAlias $interfaceAlias `
  -Profile Any
```

With the monitor running, the startup script prints the same-Wi-Fi URL. Open
that URL on a device connected to the same Wi-Fi. The desktop must remain
powered on and awake. The relay process is recorded in
`data/monitor-processes.json` and is stopped by `scripts/stop-monitor.ps1`.

The dashboard has no application login. Do not forward port `8080` on the
router or expose it directly to the internet. For future remote access, use an
authenticated private network such as Tailscale instead.

The relay detects the active address whenever the monitor starts. If DHCP gives
the desktop a different address, recreate the firewall rule with that new
address. To remove LAN access completely, run this command from Administrator
PowerShell:

```powershell
Remove-NetFirewallRule -DisplayName "Fridge Temperature Monitor (LAN)"
```

## Start automatically with Windows

Install the included sign-in Scheduled Task once:

```powershell
.\scripts\install-startup-task.ps1
```

The task starts at the next sign-in and restarts the supervisor up to three times after an unexpected failure. To start it immediately:

```powershell
Start-ScheduledTask -TaskName "Fridge Temperature Monitor"
```

The task normally remains `Running` while the same-Wi-Fi relay is active. It
also watches that relay after usbipd-win 5.x hands USB auto-attachment to WSL.
If the relay exits unexpectedly, the task fails so Task Scheduler can restart
the complete monitor supervisor. When LAN access is already supplied by
another service, the task may show `Ready` after a successful USB handoff.

To remove it later:

```powershell
Unregister-ScheduledTask -TaskName "Fridge Temperature Monitor"
```

Windows must remain awake for continuous monitoring. Sleeping, shutting down, or signing out stops USB forwarding. Configure the desktop not to sleep while plugged in if uninterrupted history is important.

## Move to a new Windows computer

Git contains the application and safe example configuration, but it deliberately
does not contain installation-specific settings, credentials, sensor IDs, or
temperature history. These pieces live in different places:

| Item | Location | Included in this repository? | New-computer action |
| --- | --- | --- | --- |
| Application source and documentation | This checkout | Yes | Clone the repository. |
| Email credentials, admin token, dashboard address, and selected sensor-file path | `.env` in the repository root | No; ignored by Git | Copy it through a secure channel or recreate it from `.env.example`. |
| Sensor IDs, names, colors, notes, and first-run profiles | `dashboard/sensors.local.json` by default | No; ignored by Git | Copy it securely or recreate it from `dashboard/sensors.example.json`. |
| Temperature readings, saved storage profiles, notification state, and alert history | Docker volume `fridge-temperature-monitor-data` | No | Restore a validated private backup or begin with a new database. |
| USB supervisor state and diagnostic logs | Ignored `data/` directory | No | Do not migrate; the launcher recreates it. |
| Portable weekly SQL dumps | Separate private `home-app-backups` repository | No | Clone the private repository and validate the latest dump. |
| Monitor and backup schedules | Windows Task Scheduler | No | Run both task installers again. |
| RTL-SDR sharing | `usbipd-win` machine configuration | No | Run the one-time USB setup again. |
| LAN firewall rule and Tailscale registration | Windows and Tailscale machine configuration | No | Reconfigure them for the new computer and its address; the LAN relay itself starts from the cloned repository. |

The Docker volume is stored inside the selected WSL distribution under Docker's
data directory. Do not copy or edit the live SQLite files there while the
containers are running. Use the SQL backup workflow below so the snapshot is
consistent and portable.

On a new Windows computer:

1. Install WSL, the expected Ubuntu distribution, Docker Engine with Compose,
   `usbipd-win`, Git, Python, and GitHub CLI as described in
   [Prerequisites](#prerequisites).
2. Clone this repository to its permanent location. Scheduled tasks store
   absolute paths, so moving the checkout later requires reinstalling them.
3. Copy or recreate `.env` and `dashboard/sensors.local.json`. Never place a
   real credential or sensor file in a public repository.
4. Run `scripts/setup-docker-usb.ps1`, then `scripts/check-prerequisites.ps1`.
5. Run `scripts/start-monitor.ps1`, followed by `scripts/test-system.ps1`, and
   confirm the dashboard receives every configured sensor.
6. Run `scripts/install-startup-task.ps1` to start monitoring at Windows
   sign-in.
7. Clone the private backup repository and run `python scripts/setup_backups.py`
   to reinstall the weekly backup task for the new absolute paths.
8. Recreate LAN or Tailscale access instead of copying old firewall or proxy
   rules blindly; the new computer may have a different address.

A new installation can start with an empty Docker volume. The existing restore
command validates a dump and can create a standalone SQLite database for
inspection, but importing that database into the live Docker volume is not yet
automated. Keep the old computer or its private backup repository until the new
installation is verified, and do not overwrite a running database manually.

## Dashboard and SQL data

The local dashboard provides:

- latest temperature, battery state, and last contact;
- 6-hour, 24-hour, 7-day, and 30-day charts;
- stale-sensor detection after two hours;
- warm, cold, and low-battery status;
- a per-sensor storage-profile selector with persistent alert limits;
- SQLite persistence across container rebuilds.

### Storage profiles

Each sensor card has a **Stored contents** selector. Presets save immediately;
selecting **Custom range** reveals minimum and maximum fields plus a save
button.

| Profile | Alert range | Intended use |
| --- | ---: | --- |
| Food refrigerator | 33–40°F | Perishable food; FDA maximum is 40°F |
| Freezer | -20–0°F | Frozen food; FDA target is 0°F or below |
| Drinks / beer | 34–45°F | Drinks-only quality range; not a food-safety preset |
| Wine cooler | 45–65°F | General wine-storage range; customize when needed |
| Custom range | User selected | Any installation-specific minimum and maximum |
| Readings only | No limits | Keep history without warm or cold alerts |

Dashboard selections are stored in the `sensor_settings` table inside the
existing SQLite Docker volume, so they survive image and container rebuilds.
The file selected by `SENSORS_FILE` supplies first-run defaults and labels; a
saved dashboard selection takes precedence. Preset limits are alert thresholds,
not commands sent to the refrigerator or freezer.

Docker binds the dashboard to loopback TCP port `8080`, so it remains desktop-only unless the user-level LAN relay is running and the restricted firewall rule above is installed. The decoder and dashboard communicate across the private Compose network.

At one reading every two minutes per sensor, plan on roughly 100–250 MB of SQLite growth per year. A retention or downsampling job can be added later if long-term size becomes important.

The live database is not committed to this application repository. A separate
private GitHub repository can receive a verified SQL dump once a week. The
Windows Python scheduler asks the running dashboard container for a consistent
SQLite snapshot, restores that dump into a temporary database as a validation
step, verifies that GitHub still reports the destination as private, and only
then commits and pushes it. Git and GitHub credentials stay on Windows; the
container only reads its own `/data/fridge-monitor.db` volume.

### Weekly private GitHub backups

Authenticate GitHub CLI once, then run the setup script from the repository
root:

```powershell
gh auth login
python scripts/setup_backups.py
```

The backup repository uses your existing Git name and email. Configure them
with `git config --global user.name` and `git config --global user.email` before
setup if they are not already present.

The defaults derive `<authenticated-user>/home-app-backups` from GitHub CLI,
refuse to continue unless GitHub reports that repository as **private**, clone
it beside this repository, create and push the first backup, and install the Windows task
`Fridge Temperature Monitor Weekly Database Backup`. It runs every Sunday at
3:00 AM. The task uses the current Windows login and `StartWhenAvailable`, so a
missed run starts after the next login when the network is available.

The private repository contains two managed files:

- `fridge-monitor.sql` — the complete, readable SQLite schema and data;
- `backup-manifest.json` — creation time, SHA-256, size, integrity result, and
  row count for each table.

Run or test the process manually:

```powershell
python scripts/backup_database.py
python scripts/restore_database.py
```

The restore command defaults to a temporary test restore and does not touch the
live Docker volume. To create a standalone recovered database for inspection or
migration, specify a new output path:

```powershell
python scripts/restore_database.py --output .\restored-fridge-monitor.db
```

The weekly log is stored at
`%LOCALAPPDATA%\FridgeTemperatureMonitor\backup.log`. Do not copy the running
`.db`, `-wal`, or `-shm` files directly from the Docker volume; use the export
script so all tables come from one consistent database snapshot. Run
`python scripts/setup_backups.py --help` to change the private repository,
schedule, WSL distribution, or Windows task name.

## Notifications

The Dockerized notifier sends SMTP email. It waits for two distinct bad readings before temperature or low-battery alerts, suppresses duplicates, sends timed reminders, persists state in SQLite, and sends recovery notifications. A stale sensor alerts after its configured timeout.

Copy `.env.example` to the ignored `.env` file and configure email. Gmail requires a 16-character app password rather than the account password. Run an explicit test only after configuration:

```powershell
wsl -d Ubuntu-Docker --cd $PWD -- docker compose exec -T notifier python notifier.py --test
```

An administrator can also manage recipients and send tests from the hidden
`?admin=1` dashboard route. The page prompts for `ADMIN_API_TOKEN`, keeps it in
the current browser tab only, and the server enforces it on every settings or
test request. SMTP credentials remain in `.env` and are never returned to the
browser.

See [the notification guide](docs/notifications.md) for complete setup, alert timing, security, troubleshooting, and test commands.

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

These are planning ranges, not measurements. A plug-in power meter is the best way to measure this desktop before and after starting the stack. The same Compose services and RTL-SDR can move to a Raspberry Pi later; on native Linux, remove the Windows USB/IP launcher and expose `/dev/bus/usb` directly.

## Tests

Run the same fast suite used by GitHub Actions before each commit:

```powershell
.\scripts\test-ci.ps1
```

It parses every PowerShell script, compiles Python, runs the dashboard and database unit tests, checks the dashboard JavaScript syntax, and validates the Compose file.

On Windows, specify a differently named WSL distribution with `-WslDistribution <name>`.

After starting the monitor, run the live hardware and system suite:

```powershell
.\scripts\test-system.ps1
```

The live suite prints an individual pass/fail result for:

- `usbipd-win`, the Windows RTL-SDR, USB attachment, and WSL USB visibility;
- Docker Engine, all three Compose services, notifier health, and rtl_433 receiver initialization;
- dashboard health API and recognizable UI content;
- SQLite integrity plus a real transactional write and rollback;
- fresh readings from every sensor in the selected local configuration.

It waits up to three minutes for both sensors because they transmit periodically, then returns a nonzero exit code if any check fails. Use `-SkipLiveSensors` only when deliberately testing without powered sensors; USB, Docker, web, SQL, and decoder checks still run. GitHub Actions runs the hardware-independent suite automatically on every push and pull request.

## References

- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Microsoft: systemd in WSL](https://learn.microsoft.com/en-us/windows/wsl/systemd)
- [Microsoft: connect USB devices to WSL](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)
- [`usbipd-win` WSL documentation](https://github.com/dorssel/usbipd-win/wiki/WSL-support)
- [`rtl_433` operation and output documentation](https://github.com/merbanan/rtl_433/blob/master/docs/OPERATION.md)
- [`rtl_433` Docker images](https://github.com/hertzg/rtl_433_docker)
- [AcuRite 986 decoder source](https://github.com/merbanan/rtl_433/blob/master/src/devices/acurite_986.c)
- [FDA refrigerator and freezer temperature guidance](https://www.fda.gov/food/buy-store-serve-safe-food/refrigerator-thermometers-cold-facts-about-food-safety)
- [EIA Short-Term Energy Outlook](https://www.eia.gov/outlooks/steo/)

## License

Released under the [MIT License](LICENSE).
