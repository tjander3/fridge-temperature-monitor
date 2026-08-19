import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import app
import notifier


SENSORS = {
    "41880": {
        "name": "Mini fridge",
        "profile": "beverage",
        "monitoring": True,
        "minimum_f": 34,
        "maximum_f": 45,
        "stale_minutes": 10,
    }
}


def configuration(**overrides):
    values = {
        "poll_seconds": 30,
        "dashboard_url": "http://monitor.test",
        "email_enabled": False,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "sender@example.com",
        "smtp_app_password": "secret",
        "email_from": "sender@example.com",
        "email_to": ("owner@example.com",),
    }
    values.update(overrides)
    return notifier.NotifierConfig(**values)


class AlertEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "notifier.db"
        self.engine = notifier.AlertEngine(self.database, SENSORS)
        self.base = app.utc_now().replace(microsecond=0)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def reading(self, temperature, minutes=0, battery_ok=1):
        return {
            "time": app.iso_utc(self.base + timedelta(minutes=minutes)),
            "model": "Acurite-986",
            "id": 41880,
            "channel": "2F",
            "battery_ok": battery_ok,
            "temperature_F": temperature,
        }

    def events_of_kind(self, events, kind):
        return [event for event in events if event.kind == kind]

    def test_temperature_alert_confirmation_suppression_reminder_and_recovery(self):
        self.engine.store.add_event(self.reading(46, minutes=0))
        self.assertFalse(
            self.events_of_kind(self.engine.evaluate(self.base), "too_warm")
        )

        self.engine.store.add_event(self.reading(47, minutes=1))
        alerts = self.events_of_kind(
            self.engine.evaluate(self.base + timedelta(minutes=1)), "too_warm"
        )
        self.assertEqual([event.event for event in alerts], ["alert"])
        self.assertIn("47.0°F", alerts[0].body)
        self.engine.mark_sent(alerts[0], self.base + timedelta(minutes=1))

        self.assertFalse(
            self.events_of_kind(
                self.engine.evaluate(self.base + timedelta(minutes=30)), "too_warm"
            )
        )
        reminders = self.events_of_kind(
            self.engine.evaluate(self.base + timedelta(minutes=62)), "too_warm"
        )
        self.assertEqual([event.event for event in reminders], ["reminder"])
        self.engine.mark_sent(reminders[0], self.base + timedelta(minutes=62))

        self.engine.store.add_event(self.reading(44, minutes=63))
        self.assertFalse(
            self.events_of_kind(
                self.engine.evaluate(self.base + timedelta(minutes=63)), "too_warm"
            )
        )
        self.engine.store.add_event(self.reading(43, minutes=64))
        recoveries = self.events_of_kind(
            self.engine.evaluate(self.base + timedelta(minutes=64)), "too_warm"
        )
        self.assertEqual([event.event for event in recoveries], ["recovery"])

    def test_alert_state_survives_restart(self):
        self.engine.store.add_event(self.reading(46, minutes=0))
        self.engine.evaluate(self.base)
        self.engine.store.add_event(self.reading(47, minutes=1))
        alert = self.events_of_kind(
            self.engine.evaluate(self.base + timedelta(minutes=1)), "too_warm"
        )[0]
        self.engine.mark_sent(alert, self.base + timedelta(minutes=1))

        reopened = notifier.AlertEngine(self.database, SENSORS)
        events = reopened.evaluate(self.base + timedelta(minutes=30))
        self.assertFalse(self.events_of_kind(events, "too_warm"))

    def test_stale_alert_and_next_reading_recovery(self):
        self.engine.store.add_event(self.reading(42, minutes=-20))
        alerts = self.events_of_kind(self.engine.evaluate(self.base), "stale")
        self.assertEqual([event.event for event in alerts], ["alert"])
        self.engine.mark_sent(alerts[0], self.base)

        self.engine.store.add_event(self.reading(42, minutes=1))
        recoveries = self.events_of_kind(
            self.engine.evaluate(self.base + timedelta(minutes=1)), "stale"
        )
        self.assertEqual([event.event for event in recoveries], ["recovery"])

    def test_low_battery_requires_two_readings_and_recovers_on_one(self):
        self.engine.store.add_event(self.reading(42, minutes=0, battery_ok=0))
        self.engine.evaluate(self.base)
        self.engine.store.add_event(self.reading(42, minutes=1, battery_ok=0))
        alerts = self.events_of_kind(
            self.engine.evaluate(self.base + timedelta(minutes=1)), "low_battery"
        )
        self.assertEqual([event.event for event in alerts], ["alert"])
        self.engine.mark_sent(alerts[0], self.base + timedelta(minutes=1))

        self.engine.store.add_event(self.reading(42, minutes=2, battery_ok=1))
        recoveries = self.events_of_kind(
            self.engine.evaluate(self.base + timedelta(minutes=2)), "low_battery"
        )
        self.assertEqual([event.event for event in recoveries], ["recovery"])

    def test_service_records_success_and_failure(self):
        class SuccessfulChannel:
            name = "success"

            def send(self, _alert):
                return None

        class FailingChannel:
            name = "failure"

            def send(self, _alert):
                raise RuntimeError("delivery unavailable")

        self.engine.store.add_event(self.reading(46, minutes=0))
        self.engine.evaluate(self.base)
        self.engine.store.add_event(self.reading(47, minutes=1))
        service = notifier.NotificationService(
            self.engine, [SuccessfulChannel(), FailingChannel()]
        )
        service.run_once(self.base + timedelta(minutes=1))

        with closing(sqlite3.connect(self.database)) as connection:
            deliveries = connection.execute(
                "SELECT channel, success, error FROM notification_deliveries ORDER BY id"
            ).fetchall()
            last_sent = connection.execute(
                "SELECT last_sent_at FROM alert_states "
                "WHERE sensor_id = 41880 AND kind = 'too_warm'"
            ).fetchone()[0]
        self.assertEqual(deliveries[0][:2], ("success", 1))
        self.assertEqual(deliveries[1][:2], ("failure", 0))
        self.assertIn("delivery unavailable", deliveries[1][2])
        self.assertIsNotNone(last_sent)

    def test_web_settings_reload_and_test_command_state_are_persistent(self):
        config = configuration(email_enabled=True)
        self.engine.seed_notification_settings(config)
        self.engine.store.update_notification_settings(
            {
                "email_enabled": True,
                "email_to": "owner@example.com",
            }
        )
        settings = self.engine.delivery_settings()
        channels = notifier.configured_channels(config, settings)
        self.assertEqual([channel.name for channel in channels], ["email"])
        self.assertEqual(channels[0].recipients, ("owner@example.com",))

        command_id = self.engine.store.queue_notification_test()
        self.assertEqual(self.engine.claim_test_commands(), [command_id])
        self.engine.complete_test_command(command_id, True, "Sent through email")
        latest = self.engine.store.notification_settings()["latest_test"]
        self.assertEqual(latest["status"], "sent")


class ChannelTests(unittest.TestCase):
    @patch("notifier.smtplib.SMTP")
    def test_smtp_uses_starttls_login_and_expected_message(self, smtp):
        client = smtp.return_value
        alert = notifier.AlertEvent(
            1, "Freezer", "too_warm", "alert", "Freezer: too warm", "Body"
        )
        notifier.SmtpChannel(configuration(email_enabled=True)).send(alert)
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("sender@example.com", "secret")
        message = client.send_message.call_args.args[0]
        self.assertEqual(message["To"], "owner@example.com")
        self.assertIn("Freezer: too warm", message["Subject"])

    def test_enabled_channels_require_credentials(self):
        config = configuration(
            email_enabled=True,
            smtp_app_password="",
        )
        self.assertIn("SMTP_APP_PASSWORD", "; ".join(config.errors()))

    def test_healthcheck_rejects_stale_or_unhealthy_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "health.json"
            notifier.write_health(True, "ok", ["email"], path)
            self.assertEqual(notifier.healthcheck(path), 0)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["ok"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(notifier.healthcheck(path), 1)


if __name__ == "__main__":
    unittest.main()
