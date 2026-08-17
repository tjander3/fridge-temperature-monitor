# Fridge Temperature Monitor

Local refrigerator and freezer temperature monitoring with an RTL-SDR Blog V3 receiver, two AcuRite 00986M wireless sensors, `rtl_433`, and Docker.

This is a standalone project rather than an `rtl_433` fork because protocol 41 in `rtl_433` already supports the AcuRite 00986M. The first milestone—receiving clean JSON temperature events from both sensors—was completed on August 17, 2026.

## How the Windows setup works

The Docker Engine runs directly inside the `Ubuntu-Docker` WSL2 distribution, without Docker Desktop. WSL does not pass the USB receiver directly into a normal Linux container, so instead:

```text
AcuRite sensor -> 433.92 MHz -> RTL-SDR USB -> rtl_tcp on Windows
                                               |
                                               v
                                     rtl_433 in Docker -> JSON
```

`rtl_tcp` owns the USB device on Windows. The Docker container connects to it through `host.docker.internal` and performs the decoding.

## Phase 1: prove the radio works

### Prerequisites

- WSL2 with the `Ubuntu-Docker` distribution
- Docker Engine and Docker Compose installed inside `Ubuntu-Docker`
- An RTL-SDR-compatible Windows USB driver and `rtl_tcp.exe`
- The RTL-SDR Blog V3 and its antenna
- At least one AcuRite 00986M transmitter with fresh batteries

The included check reports what is installed:

```powershell
.\scripts\check-prerequisites.ps1
```

The Windows bridge script automatically uses `.tools\rtl-sdr\v1.3.6\x64\rtl_tcp.exe` when it is present. Otherwise, it looks on `PATH` or accepts a full location through `-RtlTcpPath`.

### 1. Prepare the receiver

1. Connect the dipole antenna to the RTL-SDR.
2. Extend both antenna arms to roughly 17 cm and orient them vertically.
3. Plug the dongle directly into the Windows computer.
4. Leave the bias tee **off**; the included antenna does not need power.

### 2. Start the Windows radio bridge

Open PowerShell in this repository and run:

```powershell
.\scripts\start-rtl-tcp.ps1
```

Leave that window open. A successful connection later prints a line similar to `client accepted`.

### 3. Start the decoder

Open a second PowerShell window in this repository:

```powershell
.\scripts\start-decoder.ps1
```

The PowerShell script starts Docker through the `Ubuntu-Docker` WSL distribution and supplies the Windows host address to the container. The container listens at 433.92 MHz and enables only `rtl_433` protocol 41 to keep this smoke test focused.

### 4. Identify each sensor

1. Place the first transmitter near the antenna.
2. Wait for JSON containing fields such as `model`, `id`, `channel`, `temperature_F`, and `battery_ok`. The sensors normally transmit about every two minutes, so battery cycling is unnecessary.
3. Write down its ID and label it fridge or freezer.
4. Repeat with the second transmitter by itself.

A first successful event should resemble this shape (the values will differ):

```json
{"model":"Acurite-986","id":1234,"channel":"1F","battery_ok":1,"temperature_F":39.2}
```

### Confirmed receiver output

The initial capture received CRC-valid packets from both transmitters:

| Sensor ID | Channel | Observed temperature | Battery |
| --- | --- | ---: | --- |
| `41880` | `2F` | 71°F | Good |
| `52572` | `1R` | -11°F | Good |

The sensor roles still need to be labeled explicitly before the collector configuration is finalized.

### Success criteria

- Both physical transmitters produce events.
- Their IDs remain distinct and stable.
- Temperature readings are plausible beside a known thermometer.
- Events continue with the fridge/freezer doors closed.

Stop both processes with `Ctrl+C` after testing. `rtl_tcp` is not encrypted, so port 1234 should never be forwarded from the router or exposed to the internet.

## Next milestone

Once reception is reliable, add a small collector, time-series storage, a temperature graph, and alerts for sustained unsafe temperatures or missing sensor reports.

## Upstream references

- [`rtl_433`](https://github.com/merbanan/rtl_433)
- [`rtl_433` Docker images](https://github.com/hertzg/rtl_433_docker)
- [AcuRite 986 decoder source](https://github.com/merbanan/rtl_433/blob/master/src/devices/acurite_986.c)
