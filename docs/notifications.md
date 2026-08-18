# Notification plan

## Recommended first version

Run a `notifier` service in the same Docker Compose stack and support two channels:

1. **Email through SMTP** for a durable alert that works without installing another app. Gmail can be used with an app password; the normal account password must never be stored in this repository.
2. **ntfy phone push** for an immediate phone notification that feels like a text message. ntfy has an official Docker image and can later be self-hosted. Start with a private, hard-to-guess topic on the hosted service, then add authentication or self-host it before sharing the project with anyone else.

True SMS can be added through Twilio later. It is pay-as-you-go, but US messaging can also involve a rented number, carrier charges, and registration fees. That is more setup than this personal monitor needs initially.

## Alert behavior

Notifications should describe the sensor, reading, threshold, first detection time, and a link to the local dashboard.

| Event | Trigger | Repeat behavior | Recovery |
| --- | --- | --- | --- |
| Too warm or too cold | Two consecutive bad readings | Once, then every 60 minutes while unresolved | Send when two consecutive readings return to range |
| Sensor stale | No reading for 10 minutes | Once, then every 4 hours | Send after the next reading |
| Low battery | Two consecutive low-battery readings | Once every 7 days | Send when battery is reported good again |
| Service started | Never by default | None | None |

The consecutive-reading rule avoids alerts caused by one corrupt radio packet or a short door opening. Every state transition and sent message should be recorded in SQLite so container restarts do not resend old alerts.

## Reliability limitation

A service running on this desktop cannot send an alert if the desktop loses power, sleeps, or its internet connection fails. A later version should send a periodic heartbeat to an external dead-man service. The external service can then notify you when heartbeats stop; this is the only reliable way to detect failure of the monitoring computer itself.

## Secrets and configuration

Notification credentials belong in a local `.env` file excluded from Git, with safe placeholders in `.env.example`. The initial settings should be:

```text
NOTIFY_EMAIL_ENABLED=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_APP_PASSWORD=
NOTIFY_EMAIL_TO=

NTFY_ENABLED=false
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=
```

The notifier should start normally when channels are disabled. Enabling a channel with missing credentials should fail its health check with a clear explanation.

## Tests to add with implementation

- alert-state transitions for warm, cold, stale, low battery, and recovery;
- duplicate suppression and reminder timing across a simulated restart;
- message formatting with sensor names, values, and thresholds;
- mocked SMTP and ntfy delivery, including retryable and permanent failures;
- an opt-in live test that sends a message clearly labeled `TEST`;
- confirmation in the system suite that the notifier container is healthy.
