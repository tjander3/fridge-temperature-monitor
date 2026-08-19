# Project TODO

## Public release

- [x] Choose and add the MIT License.
- [x] Rewrite all commit author and committer metadata to use `tjander22@gmail.com`.
- [x] Run a dedicated secret scanner against the complete Git history.
- [x] Complete the live direct-USB system test before describing the new runtime as verified.
- [x] Audit environment-specific configuration before making the repository public: identify machine, network, sensor, and notification values; move private or installation-specific values to ignored local configuration or environment variables; provide safe example files and setup documentation; and verify `.gitignore` coverage.
- [ ] Make the GitHub repository public, then enable secret scanning, push protection, Dependabot alerts, and private vulnerability reporting.

## Bring-up

- [x] Install `usbipd-win` from an Administrator PowerShell window.
- [x] Run `scripts/setup-docker-usb.ps1` for the one-time RTL-SDR share.
- [x] Start the all-Docker monitor and pass every check in `scripts/test-system.ps1`.
- [x] Confirm GitHub Actions passes after the current changes are pushed.

## Notifications

- [x] Implement the Dockerized notifier described in `docs/notifications.md`.
- [x] Add SMTP email delivery using credentials stored outside Git.
- [x] Add alert persistence, duplicate suppression, reminders, and recovery messages.
- [x] Add mocked notification tests and an opt-in live test notification.
- [ ] Add an external heartbeat so a sleeping or offline monitoring computer can be detected.

## Dashboard

- [x] Add persistent storage-profile presets and a custom alert range selector to each sensor card.
- [x] Add an administrator-token-protected notification settings page and queued test-message button.

## Remote access

- [ ] Make the dashboard securely available from the internet using private, authenticated access such as Tailscale, without exposing port `8080` directly through the router.
- [ ] Verify access from a phone on cellular data and document setup, access control, troubleshooting, and how to revoke access.

## Raspberry Pi deployment

- [ ] Select a Raspberry Pi 4/5, reliable storage, power supply, and Raspberry Pi OS Lite 64-bit.
- [ ] Add `compose.pi.yaml` for native Linux USB access, LAN dashboard binding, timezone configuration, and local sensor configuration.
- [ ] Add a Linux `setup-pi.sh` that checks Docker/Compose, detects the RTL-SDR, handles the conflicting DVB kernel driver when necessary, and starts the stack.
- [ ] Add a Linux/Pi live system test that does not depend on PowerShell, WSL, or `usbipd-win`.
- [ ] Add backup and restore commands for migrating the existing SQLite Docker volume from Windows to the Pi.
- [ ] Document same-LAN access, a DHCP reservation, and private remote access through Tailscale without router port forwarding.
- [ ] Validate the complete ARM64 runtime with both sensors and confirm automatic recovery after a Pi reboot and RTL-SDR reconnect.
- [ ] Add Raspberry Pi installation, upgrade, troubleshooting, and rollback instructions to the README.

## Later

- [ ] Measure actual desktop power consumption.
- [ ] Decide whether to move the stack to a Raspberry Pi or low-power mini PC.
