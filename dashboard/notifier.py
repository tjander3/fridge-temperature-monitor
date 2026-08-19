import argparse
import json
import os
import signal
import smtplib
import sqlite3
import ssl
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from app import (
    DATABASE_PATH,
    DEFAULT_STALE_MINUTES,
    ReadingStore,
    iso_utc,
    load_sensors,
    utc_now,
)


HEALTH_PATH = Path(os.environ.get("NOTIFIER_HEALTH_PATH", "/tmp/notifier-health.json"))
ALERT_KINDS = ("too_warm", "too_cold", "stale", "low_battery")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


@dataclass(frozen=True)
class AlertEvent:
    sensor_id: int
    sensor_name: str
    kind: str
    event: str
    title: str
    body: str


@dataclass
class NotifierConfig:
    poll_seconds: int
    dashboard_url: str
    email_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_username: str
    smtp_app_password: str
    email_from: str
    email_to: tuple[str, ...]

    @classmethod
    def from_env(cls):
        recipients = tuple(
            item.strip()
            for item in os.environ.get("NOTIFY_EMAIL_TO", "").split(",")
            if item.strip()
        )
        username = os.environ.get("SMTP_USERNAME", "").strip()
        return cls(
            poll_seconds=max(10, int(os.environ.get("NOTIFIER_POLL_SECONDS", "30"))),
            dashboard_url=os.environ.get("NOTIFY_DASHBOARD_URL", "").strip(),
            email_enabled=env_bool("NOTIFY_EMAIL_ENABLED"),
            smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com").strip(),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_security=os.environ.get("SMTP_SECURITY", "starttls").strip().lower(),
            smtp_username=username,
            smtp_app_password=os.environ.get("SMTP_APP_PASSWORD", ""),
            email_from=os.environ.get("NOTIFY_EMAIL_FROM", "").strip() or username,
            email_to=recipients,
        )

    def errors(self, settings=None):
        settings = settings or {}
        email_enabled = settings.get("email_enabled", self.email_enabled)
        email_to = tuple(
            item.strip()
            for item in settings.get("email_to", ",".join(self.email_to)).split(",")
            if item.strip()
        )
        errors = []
        if email_enabled:
            missing = [
                name
                for name, value in (
                    ("SMTP_HOST", self.smtp_host),
                    ("SMTP_USERNAME", self.smtp_username),
                    ("SMTP_APP_PASSWORD", self.smtp_app_password),
                    ("NOTIFY_EMAIL_FROM", self.email_from),
                    ("NOTIFY_EMAIL_TO", email_to),
                )
                if not value
            ]
            if missing:
                errors.append("email enabled but missing " + ", ".join(missing))
            if self.smtp_security not in {"starttls", "ssl", "none"}:
                errors.append("SMTP_SECURITY must be starttls, ssl, or none")
        return errors


class SmtpChannel:
    name = "email"

    def __init__(self, config, recipients=None):
        self.config = config
        self.recipients = tuple(recipients or config.email_to)

    def send(self, alert):
        message = EmailMessage()
        message["Subject"] = f"[Cold Storage] {alert.title}"
        message["From"] = self.config.email_from
        message["To"] = ", ".join(self.recipients)
        message.set_content(alert.body)

        context = ssl.create_default_context()
        if self.config.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                timeout=20,
                context=context,
            )
        else:
            server = smtplib.SMTP(
                self.config.smtp_host, self.config.smtp_port, timeout=20
            )
        with server:
            if self.config.smtp_security == "starttls":
                server.starttls(context=context)
            if self.config.smtp_username:
                server.login(
                    self.config.smtp_username, self.config.smtp_app_password
                )
            server.send_message(message)


class AlertEngine:
    def __init__(self, database_path=DATABASE_PATH, sensors=None):
        self.database_path = Path(database_path)
        self.sensors = sensors if sensors is not None else load_sensors()
        self.store = ReadingStore(self.database_path, self.sensors)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_states (
                    sensor_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    bad_count INTEGER NOT NULL DEFAULT 0,
                    good_count INTEGER NOT NULL DEFAULT 0,
                    first_detected_at TEXT,
                    last_observed_at TEXT,
                    last_sent_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (sensor_id, kind)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    sensor_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    event TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    error TEXT
                )
                """
            )

    def seed_notification_settings(self, config):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO notification_settings (
                    id, email_enabled, email_to, ntfy_enabled,
                    vtext_enabled, phone_number, updated_at
                ) VALUES (1, ?, ?, 0, 0, '', ?)
                """,
                (
                    int(config.email_enabled),
                    ",".join(config.email_to),
                    iso_utc(utc_now()),
                ),
            )
            # Retired phone fields remain only for compatibility with old volumes.
            connection.execute(
                """
                UPDATE notification_settings
                SET ntfy_enabled = 0, vtext_enabled = 0, phone_number = ''
                WHERE id = 1
                """
            )
            connection.execute(
                """
                UPDATE notification_commands
                SET status = 'pending', result = 'Recovered after notifier restart'
                WHERE command = 'test' AND status = 'processing'
                """
            )

    def delivery_settings(self):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM notification_settings WHERE id = 1"
            ).fetchone()
        if not row:
            return {}
        return {
            "email_enabled": bool(row["email_enabled"]),
            "email_to": row["email_to"],
        }

    def write_runtime(self, healthy, detail, channels):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO notifier_runtime (
                    id, healthy, detail, channels_json, updated_at
                ) VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    healthy = excluded.healthy,
                    detail = excluded.detail,
                    channels_json = excluded.channels_json,
                    updated_at = excluded.updated_at
                """,
                (
                    int(healthy),
                    detail,
                    json.dumps(channels, separators=(",", ":")),
                    iso_utc(utc_now()),
                ),
            )

    def claim_test_commands(self):
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id FROM notification_commands
                WHERE command = 'test' AND status = 'pending'
                ORDER BY id
                """
            ).fetchall()
            ids = [row["id"] for row in rows]
            for command_id in ids:
                connection.execute(
                    "UPDATE notification_commands SET status = 'processing' WHERE id = ?",
                    (command_id,),
                )
        return ids

    def complete_test_command(self, command_id, success, result):
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE notification_commands
                SET status = ?, completed_at = ?, result = ?
                WHERE id = ?
                """,
                (
                    "sent" if success else "failed",
                    iso_utc(utc_now()),
                    result[:1000],
                    command_id,
                ),
            )

    def evaluate(self, now=None):
        now = (now or utc_now()).astimezone(timezone.utc)
        data = self.store.dashboard_data(24)
        events = []
        with self._connection() as connection:
            for sensor in data["sensors"]:
                sensor_id = sensor["id"]
                base = self.sensors.get(str(sensor_id), {})
                latest = sensor.get("latest")
                observed_at = latest.get("observed_at") if latest else None
                observed = parse_datetime(observed_at)
                temperature = latest.get("temperature_f") if latest else None
                minimum = sensor.get("minimum_f")
                maximum = sensor.get("maximum_f")
                monitoring = bool(sensor.get("monitoring", True))
                stale_minutes = int(
                    base.get("stale_minutes", DEFAULT_STALE_MINUTES)
                )

                conditions = {
                    "too_warm": latest is not None
                    and maximum is not None
                    and temperature > maximum,
                    "too_cold": latest is not None
                    and minimum is not None
                    and temperature < minimum,
                    "low_battery": latest is not None
                    and latest.get("battery_ok") == 0,
                    "stale": latest is not None
                    and observed is not None
                    and now - observed > timedelta(minutes=stale_minutes),
                }

                for kind in ALERT_KINDS:
                    event = self._update_condition(
                        connection=connection,
                        sensor=sensor,
                        kind=kind,
                        bad=conditions[kind],
                        monitoring=monitoring,
                        observed_at=observed_at,
                        now=now,
                    )
                    if event:
                        events.append(event)
        return events

    def _update_condition(
        self, connection, sensor, kind, bad, monitoring, observed_at, now
    ):
        sensor_id = sensor["id"]
        row = connection.execute(
            "SELECT * FROM alert_states WHERE sensor_id = ? AND kind = ?",
            (sensor_id, kind),
        ).fetchone()
        state = dict(row) if row else {
            "active": 0,
            "bad_count": 0,
            "good_count": 0,
            "first_detected_at": None,
            "last_observed_at": None,
            "last_sent_at": None,
        }
        active = bool(state["active"])
        bad_count = int(state["bad_count"])
        good_count = int(state["good_count"])
        first_detected_at = state["first_detected_at"]
        last_sent_at = state["last_sent_at"]
        new_observation = bool(observed_at) and observed_at != state["last_observed_at"]
        event_name = None

        if not monitoring:
            active = False
            bad_count = 0
            good_count = 0
            first_detected_at = None
            last_sent_at = None
        elif kind == "stale":
            if bad and not active:
                active = True
                first_detected_at = iso_utc(now)
                event_name = "alert"
            elif bad and active and self._reminder_due(kind, last_sent_at, now):
                event_name = "alert" if not last_sent_at else "reminder"
            elif not bad and active:
                active = False
                first_detected_at = None
                event_name = "recovery"
        elif new_observation:
            if bad:
                if bad_count == 0:
                    first_detected_at = observed_at
                bad_count += 1
                good_count = 0
                if not active and bad_count >= 2:
                    active = True
                    event_name = "alert"
            else:
                bad_count = 0
                first_detected_at = None if not active else first_detected_at
                if active:
                    good_count += 1
                    required_good = 1 if kind == "low_battery" else 2
                    if good_count >= required_good:
                        active = False
                        good_count = 0
                        first_detected_at = None
                        event_name = "recovery"
                else:
                    good_count = 0

        if active and not event_name and self._reminder_due(kind, last_sent_at, now):
            event_name = "alert" if not last_sent_at else "reminder"

        connection.execute(
            """
            INSERT INTO alert_states (
                sensor_id, kind, active, bad_count, good_count,
                first_detected_at, last_observed_at, last_sent_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sensor_id, kind) DO UPDATE SET
                active = excluded.active,
                bad_count = excluded.bad_count,
                good_count = excluded.good_count,
                first_detected_at = excluded.first_detected_at,
                last_observed_at = excluded.last_observed_at,
                last_sent_at = excluded.last_sent_at,
                updated_at = excluded.updated_at
            """,
            (
                sensor_id,
                kind,
                int(active),
                bad_count,
                good_count,
                first_detected_at,
                observed_at or state["last_observed_at"],
                last_sent_at,
                iso_utc(now),
            ),
        )
        if not event_name:
            return None
        return self._format_event(sensor, kind, event_name, first_detected_at)

    @staticmethod
    def _reminder_due(kind, last_sent_at, now):
        if not last_sent_at:
            return True
        intervals = {
            "too_warm": timedelta(hours=1),
            "too_cold": timedelta(hours=1),
            "stale": timedelta(hours=4),
            "low_battery": timedelta(days=7),
        }
        return now - parse_datetime(last_sent_at) >= intervals[kind]

    @staticmethod
    def _format_event(sensor, kind, event_name, first_detected_at):
        name = sensor["name"]
        latest = sensor.get("latest") or {}
        temperature = latest.get("temperature_f")
        minimum = sensor.get("minimum_f")
        maximum = sensor.get("maximum_f")

        labels = {
            "too_warm": "too warm",
            "too_cold": "too cold",
            "stale": "sensor overdue",
            "low_battery": "low battery",
        }
        if event_name == "recovery":
            title = (
                f"{name} sensor is reporting again"
                if kind == "stale"
                else f"{name} battery recovered"
                if kind == "low_battery"
                else f"{name} temperature recovered"
            )
        elif event_name == "reminder":
            title = f"{name} is still {labels[kind]}"
        else:
            title = f"{name}: {labels[kind]}"

        details = []
        if temperature is not None:
            details.append(f"Latest temperature: {temperature:.1f}°F.")
        if kind in {"too_warm", "too_cold"}:
            details.append(f"Configured range: {minimum:g}–{maximum:g}°F.")
        if first_detected_at and event_name != "recovery":
            detected = parse_datetime(first_detected_at).astimezone().strftime(
                "%Y-%m-%d %I:%M %p %Z"
            )
            details.append(f"First detected: {detected}.")
        if event_name == "recovery":
            details.append("The condition has cleared.")

        return AlertEvent(
            sensor_id=sensor["id"],
            sensor_name=name,
            kind=kind,
            event=event_name,
            title=title,
            body=" ".join(details),
        )

    def mark_sent(self, alert, sent_at=None):
        if alert.event == "recovery":
            return
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE alert_states
                SET last_sent_at = ?, updated_at = ?
                WHERE sensor_id = ? AND kind = ?
                """,
                (
                    iso_utc(sent_at or utc_now()),
                    iso_utc(sent_at or utc_now()),
                    alert.sensor_id,
                    alert.kind,
                ),
            )

    def record_delivery(self, alert, channel, success, error=None, created_at=None):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO notification_deliveries (
                    created_at, sensor_id, kind, event, channel,
                    success, title, body, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iso_utc(created_at or utc_now()),
                    alert.sensor_id,
                    alert.kind,
                    alert.event,
                    channel,
                    int(success),
                    alert.title,
                    alert.body,
                    error,
                ),
            )


class NotificationService:
    def __init__(self, engine, channels):
        self.engine = engine
        self.channels = channels

    def run_once(self, now=None):
        events = self.engine.evaluate(now)
        for alert in events:
            self.deliver(alert, now)
        return events

    def deliver(self, alert, now=None):
        delivered = []
        failures = []
        for channel in self.channels:
            try:
                channel.send(alert)
                self.engine.record_delivery(alert, channel.name, True, created_at=now)
                delivered.append(channel.name)
                print(
                    f"notification: sent {alert.event} {alert.kind} "
                    f"for sensor {alert.sensor_id} via {channel.name}",
                    flush=True,
                )
            except Exception as error:  # Delivery errors must not stop monitoring.
                self.engine.record_delivery(
                    alert,
                    channel.name,
                    False,
                    error=str(error)[:1000],
                    created_at=now,
                )
                failures.append(f"{channel.name}: {error}")
                print(
                    f"notification: {channel.name} failed for sensor "
                    f"{alert.sensor_id}: {error}",
                    flush=True,
                )
        if delivered:
            self.engine.mark_sent(alert, now)
        return delivered, failures


def configured_channels(config, settings=None):
    settings = settings or {}
    channels = []
    email_enabled = settings.get("email_enabled", config.email_enabled)
    recipients = [
        item.strip()
        for item in settings.get("email_to", ",".join(config.email_to)).split(",")
        if item.strip()
    ]
    if email_enabled:
        channels.append(SmtpChannel(config, recipients))
    return channels


def write_health(ok, detail, channels, path=HEALTH_PATH):
    path.write_text(
        json.dumps(
            {
                "ok": bool(ok),
                "detail": detail,
                "channels": channels,
                "updated_at": iso_utc(utc_now()),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def healthcheck(path=HEALTH_PATH):
    try:
        health = json.loads(path.read_text(encoding="utf-8"))
        updated = parse_datetime(health["updated_at"])
        if not health.get("ok") or utc_now() - updated > timedelta(minutes=3):
            return 1
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        return 1


def test_alert(config):
    return AlertEvent(
        sensor_id=0,
        sensor_name="Test",
        kind="test",
        event="test",
        title="TEST: Cold Storage Monitor email",
        body="This is an opt-in test. No temperature problem was detected."
        + (f" Dashboard: {config.dashboard_url}" if config.dashboard_url else ""),
    )


def send_test(config, engine):
    settings = engine.delivery_settings()
    errors = config.errors(settings)
    channels = configured_channels(config, settings)
    if errors:
        raise RuntimeError("; ".join(errors))
    if not channels:
        raise RuntimeError("enable at least one notification channel first")
    alert = test_alert(config)
    failures = []
    for channel in channels:
        try:
            channel.send(alert)
            engine.record_delivery(alert, channel.name, True)
            print(f"TEST notification sent through {channel.name}", flush=True)
        except Exception as error:
            engine.record_delivery(alert, channel.name, False, str(error)[:1000])
            failures.append(f"{channel.name}: {error}")
    if failures:
        raise RuntimeError("; ".join(failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.healthcheck:
        raise SystemExit(healthcheck())

    config = NotifierConfig.from_env()
    engine = AlertEngine()
    engine.seed_notification_settings(config)
    if args.test:
        send_test(config, engine)
        return

    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    print("Notifier started", flush=True)
    while not stopping:
        settings = engine.delivery_settings()
        errors = config.errors(settings)
        channels = configured_channels(config, settings)
        channel_names = [channel.name for channel in channels]
        detail = (
            "; ".join(errors)
            if errors
            else "notifications disabled"
            if not channel_names
            else "enabled: " + ", ".join(channel_names)
        )
        try:
            if errors:
                print(f"Notifier configuration error: {detail}", flush=True)
                write_health(False, detail, channel_names)
                engine.write_runtime(False, detail, channel_names)
            else:
                service = NotificationService(engine, channels)
                for command_id in engine.claim_test_commands():
                    if not channels:
                        engine.complete_test_command(
                            command_id, False, "No notification channels are enabled"
                        )
                        continue
                    delivered, failures = service.deliver(test_alert(config))
                    success = bool(delivered) and not failures
                    result = (
                        "Sent through " + ", ".join(delivered)
                        if success
                        else "; ".join(failures) or "No delivery succeeded"
                    )
                    engine.complete_test_command(command_id, success, result)
                service.run_once()
                write_health(True, detail, channel_names)
                engine.write_runtime(True, detail, channel_names)
        except Exception as error:  # Keep polling after transient database errors.
            print(f"Notifier poll failed: {error}", flush=True)
            write_health(False, str(error)[:1000], channel_names)
            engine.write_runtime(False, str(error)[:1000], channel_names)
        deadline = time.monotonic() + config.poll_seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
