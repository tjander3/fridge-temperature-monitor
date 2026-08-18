import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app


SENSORS = {
    "41880": {
        "name": "Mini fridge",
        "color": "#37c9d9",
        "profile": "unmonitored",
        "monitoring": False,
        "maximum_f": 40,
    },
    "52572": {
        "name": "Basement freezer",
        "color": "#ffb84d",
        "profile": "freezer",
        "monitoring": True,
        "minimum_f": -20,
        "maximum_f": 0,
    },
}


class ReadingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database = Path(self.temporary_directory.name) / "test.db"
        self.store = app.ReadingStore(database, SENSORS)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def event(self, sensor_id=52572, temperature=-11, observed_at=None):
        return {
            "time": observed_at or app.iso_utc(app.utc_now()),
            "model": "Acurite-986",
            "id": sensor_id,
            "channel": "1R",
            "battery_ok": 1,
            "temperature_F": temperature,
            "rssi": -11.8,
            "snr": 16.3,
        }

    def test_adds_and_deduplicates_events(self):
        event = self.event()
        self.assertTrue(self.store.add_event(event))
        self.assertFalse(self.store.add_event(event))
        data = self.store.dashboard_data(24)
        freezer = next(sensor for sensor in data["sensors"] if sensor["id"] == 52572)
        self.assertEqual(len(freezer["points"]), 1)
        self.assertEqual(freezer["status"], "ok")
        self.assertEqual(freezer["color"], "#ffb84d")

    def test_ignores_unrelated_protocols(self):
        self.assertFalse(self.store.add_event({"model": "Other", "id": 1}))

    def test_rejects_incomplete_and_invalid_events(self):
        self.assertFalse(self.store.add_event({"model": "Acurite-986", "id": 52572}))
        self.assertFalse(
            self.store.add_event(
                {"model": "Acurite-986", "id": "not-an-id", "temperature_F": -4}
            )
        )

    def test_reports_stale_and_warm_readings(self):
        old_time = app.iso_utc(app.utc_now() - timedelta(minutes=20))
        self.store.add_event(self.event(observed_at=old_time))
        freezer = next(sensor for sensor in self.store.dashboard_data(24)["sensors"] if sensor["id"] == 52572)
        self.assertEqual(freezer["status"], "stale")

        fresh_store = app.ReadingStore(
            Path(self.temporary_directory.name) / "warm.db", SENSORS
        )
        fresh_store.add_event(self.event(temperature=8))
        freezer = next(sensor for sensor in fresh_store.dashboard_data(24)["sensors"] if sensor["id"] == 52572)
        self.assertEqual(freezer["status"], "too_warm")

    def test_desk_sensor_stays_in_setup_mode(self):
        self.store.add_event(self.event(sensor_id=41880, temperature=70))
        mini_fridge = next(sensor for sensor in self.store.dashboard_data(24)["sensors"] if sensor["id"] == 41880)
        self.assertEqual(mini_fridge["status"], "setup")

    def test_storage_profile_preset_persists_in_sqlite(self):
        self.store.update_sensor_profile(41880, "beverage")
        self.store.add_event(self.event(sensor_id=41880, temperature=42))
        sensor = next(
            sensor for sensor in self.store.dashboard_data(24)["sensors"]
            if sensor["id"] == 41880
        )
        self.assertEqual(sensor["profile"], "beverage")
        self.assertTrue(sensor["monitoring"])
        self.assertEqual(sensor["minimum_f"], 34)
        self.assertEqual(sensor["maximum_f"], 45)
        self.assertEqual(sensor["status"], "ok")

        reopened = app.ReadingStore(self.store.database_path, SENSORS)
        sensor = next(
            sensor for sensor in reopened.dashboard_data(24)["sensors"]
            if sensor["id"] == 41880
        )
        self.assertEqual(sensor["profile"], "beverage")
        self.assertEqual(sensor["maximum_f"], 45)

    def test_custom_profile_validates_and_applies_range(self):
        with self.assertRaisesRegex(ValueError, "minimum must be lower"):
            self.store.update_sensor_profile(41880, "custom", 50, 40)
        with self.assertRaisesRegex(ValueError, "unknown storage profile"):
            self.store.update_sensor_profile(41880, "not-a-profile")
        with self.assertRaises(KeyError):
            self.store.update_sensor_profile(12345, "beverage")

        self.store.update_sensor_profile(41880, "custom", 35, 41)
        self.store.add_event(self.event(sensor_id=41880, temperature=42))
        sensor = next(
            sensor for sensor in self.store.dashboard_data(24)["sensors"]
            if sensor["id"] == 41880
        )
        self.assertEqual(sensor["profile"], "custom")
        self.assertEqual(sensor["status"], "too_warm")

    def test_dashboard_data_includes_profile_catalog(self):
        data = self.store.dashboard_data(24)
        profiles = {profile["id"]: profile for profile in data["profiles"]}
        self.assertEqual(profiles["food_refrigerator"]["maximum_f"], 40)
        self.assertEqual(profiles["freezer"]["maximum_f"], 0)
        self.assertEqual(profiles["beverage"]["maximum_f"], 45)
        self.assertIn("custom", profiles)

    def test_reports_low_battery_before_temperature_alert(self):
        event = self.event(temperature=12)
        event["battery_ok"] = 0
        self.store.add_event(event)
        freezer = next(sensor for sensor in self.store.dashboard_data(24)["sensors"] if sensor["id"] == 52572)
        self.assertEqual(freezer["status"], "low_battery")

    def test_reports_too_cold_when_a_minimum_is_configured(self):
        sensors = {
            "41880": {
                "name": "Mini fridge",
                "monitoring": True,
                "minimum_f": 32,
                "maximum_f": 40,
            }
        }
        store = app.ReadingStore(Path(self.temporary_directory.name) / "cold.db", sensors)
        store.add_event(self.event(sensor_id=41880, temperature=28))
        sensor = store.dashboard_data(24)["sensors"][0]
        self.assertEqual(sensor["status"], "too_cold")

    def test_unknown_sensor_is_visible_with_a_default_name(self):
        self.store.add_event(self.event(sensor_id=99999, temperature=45))
        sensor = next(sensor for sensor in self.store.dashboard_data(24)["sensors"] if sensor["id"] == 99999)
        self.assertEqual(sensor["name"], "Sensor 99999")
        self.assertEqual(sensor["status"], "ok")

    def test_hours_are_clamped(self):
        self.assertEqual(self.store.dashboard_data(0)["hours"], 1)
        self.assertEqual(self.store.dashboard_data(999999)["hours"], 24 * 365)

    def test_database_integrity(self):
        self.store.add_event(self.event())
        with closing(sqlite3.connect(self.store.database_path)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(result, "ok")

    def test_iso_utc_normalizes_naive_and_offset_timestamps(self):
        self.assertEqual(app.iso_utc("2026-08-17T12:00:00"), "2026-08-17T12:00:00Z")
        self.assertEqual(
            app.iso_utc("2026-08-17T08:00:00-04:00"),
            "2026-08-17T12:00:00Z",
        )

    def test_syslog_json_shape_is_valid(self):
        payload = '<165>1 2026-08-17T22:26:37Z host rtl_433 - - - ' + json.dumps(self.event())
        event = json.loads(payload[payload.find("{"):])
        self.assertEqual(event["id"], 52572)


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database = Path(self.temporary_directory.name) / "api-test.db"
        app.DashboardHandler.store = app.ReadingStore(database, SENSORS)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.DashboardHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def put_profile(self, sensor_id, payload):
        request = Request(
            f"{self.base_url}/api/sensors/{sensor_id}/profile",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.load(response)

    def test_profile_endpoint_saves_preset(self):
        status, result = self.put_profile(41880, {"profile": "beverage"})
        self.assertEqual(status, 200)
        self.assertEqual(result["sensor"]["profile"], "beverage")
        self.assertEqual(result["sensor"]["minimum_f"], 34)
        self.assertEqual(result["sensor"]["maximum_f"], 45)

    def test_profile_endpoint_rejects_invalid_custom_range(self):
        with self.assertRaises(HTTPError) as context:
            self.put_profile(
                41880,
                {"profile": "custom", "minimum_f": 50, "maximum_f": 40},
            )
        error = context.exception
        self.assertEqual(error.code, 400)
        result = json.load(error)
        error.close()
        self.assertIn("minimum must be lower", result["error"])


if __name__ == "__main__":
    unittest.main()
