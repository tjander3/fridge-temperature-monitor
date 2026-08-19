# Notification setup

The `notifier` Docker service reads current sensor data and alert settings from
the shared SQLite volume and sends SMTP email.
Alert state and every successful or failed delivery are also stored in SQLite,
so container rebuilds do not resend old alerts.

## Alert behavior

| Event | Trigger | Repeat behavior | Recovery |
| --- | --- | --- | --- |
| Too warm or too cold | Two distinct consecutive bad readings | Every 60 minutes while unresolved | After two consecutive in-range readings |
| Sensor stale | No reading for the sensor's configured timeout | Every 4 hours | After the next fresh reading |
| Low battery | Two distinct consecutive low-battery readings | Every 7 days | After the next good-battery reading |

The notifier remains healthy when every channel is disabled. If a channel is
enabled with incomplete configuration, the container stays running but becomes
unhealthy and logs the missing variable names.

## Create the private configuration

Copy the safe example file from PowerShell:

```powershell
Copy-Item .env.example .env
```

Compose automatically reads `.env`. The real file is excluded by `.gitignore`;
never commit it or paste its app password into an issue.
Generate a long random `ADMIN_API_TOKEN` value as well; the hidden settings page
requires it and the repository's `.env.example` includes the placeholder.

`NOTIFY_DASHBOARD_URL` is the link placed in messages. The LAN URL works while
the phone is on home Wi-Fi. After private remote access is configured, replace
it with the Tailscale URL or address so notification taps also work remotely.

## Email through Gmail

1. Turn on 2-Step Verification for the sending Google account.
2. Create a dedicated Google app password for `Fridge Monitor`.
3. Set these values in `.env`:

```text
NOTIFY_EMAIL_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-address@gmail.com
SMTP_APP_PASSWORD=the-16-character-app-password
NOTIFY_EMAIL_FROM=your-address@gmail.com
NOTIFY_EMAIL_TO=destination@example.com
```

Separate multiple recipients with commas. Do not use the normal Google account
password. Google documents port 587 with TLS and app-password authentication
for SMTP clients.

## Administrator settings page

The normal dashboard does not show notification administration. Open the
dashboard with `?admin=1` appended, such as:

```text
http://192.168.1.50:8080/?admin=1
```

The **Settings** button then appears and prompts for `ADMIN_API_TOKEN`. The
token is retained only in browser `sessionStorage`, so closing the tab removes
it. The API independently checks the token on every read, update, and test
request; hiding the button is only a convenience, not the security boundary.

The page can:

- enable or disable SMTP email and set one or more recipients;
- display notifier health and the latest test result;
- queue a clearly labeled test email through the notifier service.

SMTP credentials cannot be viewed or changed from the page. They stay in
`.env`, which prevents a stolen admin token from exposing the mail app password.

## Start and test

Recreate the notifier after changing `.env`:

```powershell
wsl -d Ubuntu-Docker --cd $PWD -- docker compose up -d --build notifier
```

Check configuration and recent activity:

```powershell
wsl -d Ubuntu-Docker --cd $PWD -- docker compose ps notifier
wsl -d Ubuntu-Docker --cd $PWD -- docker compose logs --tail 100 notifier
```

Sending a test is deliberately opt-in and is clearly labeled `TEST`:

```powershell
wsl -d Ubuntu-Docker --cd $PWD -- docker compose exec -T notifier python notifier.py --test
```

The administrator page's **Send test email** button queues the same kind of
test without giving the dashboard container access to delivery credentials.

Failed attempts are logged in the `notification_deliveries` SQLite table with
a short error message. Run `scripts/test-system.ps1` afterward to verify
notifier health alongside USB, radio, dashboard, and live sensor checks.

## Reliability limitation

A notifier on this desktop cannot send anything if the computer loses power,
sleeps, or loses internet access. A future external heartbeat/dead-man service
is still required to detect failure of the monitoring computer itself.
