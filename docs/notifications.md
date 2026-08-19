# Notification setup

The `notifier` Docker service reads current sensor data and alert settings from
the shared SQLite volume. It supports regular SMTP email and ntfy phone push.
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
never commit it or paste its app password or private ntfy topic into an issue.

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

## Phone push through ntfy

1. Install the ntfy app on the phone.
2. Choose a long random topic; on the public `ntfy.sh` service, possession of
   the topic name grants access unless account authentication is configured.
3. Subscribe to exactly that topic in the phone app.
4. Set these values in `.env`:

```text
NTFY_ENABLED=true
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=your-long-random-topic
NTFY_TOKEN=
```

For an authenticated or self-hosted server, set `NTFY_TOKEN`. The notifier
publishes urgent alerts with priority 5 and recovery messages with priority 3.
Tapping a notification opens `NOTIFY_DASHBOARD_URL` when it is configured.

## Why Verizon Vtext is not the primary phone channel

Email sent to `10-digit-number@vtext.com` can still work for some Verizon
customers, and that address may be added to `NOTIFY_EMAIL_TO` for best-effort
delivery. It must not be the only alarm channel: Verizon says Vtext/VZPix is
being shut down by March 31, 2027 and warns that individual senders may lose
access earlier or already be filtered. ntfy is therefore the supported phone
path for this project.

Verizon notice: <https://www.verizon.com/support/vtext-vzwpix-shutdown/>

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

If both channels are enabled, that command must succeed through both. Failed
attempts are logged in the `notification_deliveries` SQLite table with a short
error message. Run `scripts/test-system.ps1` afterward to verify notifier
health alongside USB, radio, dashboard, and live sensor checks.

## Reliability limitation

A notifier on this desktop cannot send anything if the computer loses power,
sleeps, or loses internet access. A future external heartbeat/dead-man service
is still required to detect failure of the monitoring computer itself.
