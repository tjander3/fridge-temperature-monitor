# Security policy

## Supported version

This is an experimental personal project. Only the latest commit on `main` is maintained.

## Reporting a vulnerability

Please use GitHub's **Report a vulnerability** option on the repository's Security page instead of opening a public issue. Do not include credentials, private RF captures, sensor history, or other personal data in a public report.

## Deployment boundaries

- The dashboard binds to `127.0.0.1` and is intended for local access only.
- Do not expose the dashboard, Docker daemon, or USB/IP services directly to the internet.
- Treat decoded RF data as untrusted input.
- Keep notification credentials in an ignored local `.env` file when that feature is implemented.

This monitor is not a certified food-safety device. Confirm temperatures independently before making food-safety decisions.
