# Contributing

Bug reports, documentation improvements, and focused pull requests are welcome.

## Before opening a pull request

1. Keep changes scoped to one problem.
2. Run `./scripts/test-ci.ps1` from PowerShell.
3. Add or update tests when behavior changes.
4. Explain any hardware and operating-system assumptions in the pull request.

The GitHub Actions workflow runs the hardware-independent suite and builds and smoke-tests the dashboard container. The RTL-SDR and live sensors are not available in CI, so describe any live test performed with `./scripts/test-system.ps1` in the pull request.

Never commit databases, RF captures, logs, credentials, `.env` files, or personally identifying sensor data. Those paths are excluded by `.gitignore`, but contributors should still inspect their staged changes before committing.
