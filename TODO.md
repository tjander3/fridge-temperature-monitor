# Project TODO

## Public release

- [x] Choose and add the MIT License.
- [x] Rewrite all commit author and committer metadata to use `tjander22@gmail.com`.
- [x] Run a dedicated secret scanner against the complete Git history.
- [x] Complete the live direct-USB system test before describing the new runtime as verified.
- [ ] Make the GitHub repository public, then enable secret scanning, push protection, Dependabot alerts, and private vulnerability reporting.

## Bring-up

- [x] Install `usbipd-win` from an Administrator PowerShell window.
- [x] Run `scripts/setup-docker-usb.ps1` for the one-time RTL-SDR share.
- [x] Start the all-Docker monitor and pass every check in `scripts/test-system.ps1`.
- [x] Confirm GitHub Actions passes after the current changes are pushed.

## Notifications

- [ ] Implement the Dockerized notifier described in `docs/notifications.md`.
- [ ] Add SMTP email delivery using credentials stored outside Git.
- [ ] Add optional ntfy phone push.
- [ ] Add alert persistence, duplicate suppression, reminders, and recovery messages.
- [ ] Add mocked notification tests and an opt-in live test notification.
- [ ] Consider Twilio only if true SMS is still preferable after trying phone push.
- [ ] Add an external heartbeat so a sleeping or offline monitoring computer can be detected.

## Later

- [ ] Move sensor `41880` into the mini fridge and enable monitoring.
- [ ] Measure actual desktop power consumption.
- [ ] Decide whether to move the stack to a Raspberry Pi or low-power mini PC.
