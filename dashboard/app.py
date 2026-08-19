import json
import os
import re
import secrets
import signal
import socketserver
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "/data/fridge-monitor.db"))
SENSORS_PATH = Path(os.environ.get("SENSORS_PATH", APP_DIR / "sensors.json"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
SYSLOG_PORT = int(os.environ.get("SYSLOG_PORT", "1514"))
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN", "").strip()

STORAGE_PROFILES = {
    "food_refrigerator": {
        "label": "Food refrigerator",
        "minimum_f": 33,
        "maximum_f": 40,
        "monitoring": True,
        "description": "Food-safety preset; FDA guidance is 40°F or below.",
    },
    "freezer": {
        "label": "Freezer",
        "minimum_f": -20,
        "maximum_f": 0,
        "monitoring": True,
        "description": "Frozen-food preset; FDA guidance is 0°F or below.",
    },
    "beverage": {
        "label": "Drinks / beer",
        "minimum_f": 34,
        "maximum_f": 45,
        "monitoring": True,
        "description": "Quality range for cold drinks and beer; not a food-safety preset.",
    },
    "wine": {
        "label": "Wine cooler",
        "minimum_f": 45,
        "maximum_f": 65,
        "monitoring": True,
        "description": "General wine-storage range; adjust for the bottles you keep.",
    },
    "custom": {
        "label": "Custom range",
        "minimum_f": None,
        "maximum_f": None,
        "monitoring": True,
        "description": "Choose your own minimum and maximum temperatures.",
    },
    "unmonitored": {
        "label": "Readings only",
        "minimum_f": None,
        "maximum_f": None,
        "monitoring": False,
        "description": "Show temperatures without warm or cold alerts.",
    },
}


def storage_profile_catalog():
    return [{"id": profile_id, **profile} for profile_id, profile in STORAGE_PROFILES.items()]


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(value):
    if not value:
        return utc_now().isoformat().replace("+00:00", "Z")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_sensors(path=SENSORS_PATH):
    with path.open(encoding="utf-8") as sensor_file:
        return json.load(sensor_file)


class ReadingStore:
    def __init__(self, database_path=DATABASE_PATH, sensors=None):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.sensors = sensors if sensors is not None else load_sensors()
        self.lock = threading.Lock()
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
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at TEXT NOT NULL,
                    sensor_id INTEGER NOT NULL,
                    channel TEXT,
                    temperature_f REAL NOT NULL,
                    battery_ok INTEGER,
                    rssi REAL,
                    snr REAL,
                    raw_json TEXT NOT NULL,
                    UNIQUE(sensor_id, observed_at, temperature_f)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS readings_time_idx ON readings(observed_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_settings (
                    sensor_id INTEGER PRIMARY KEY,
                    profile TEXT NOT NULL,
                    minimum_f REAL,
                    maximum_f REAL,
                    monitoring INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    email_enabled INTEGER NOT NULL,
                    email_to TEXT NOT NULL,
                    ntfy_enabled INTEGER NOT NULL,
                    vtext_enabled INTEGER NOT NULL,
                    phone_number TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    result TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notifier_runtime (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    healthy INTEGER NOT NULL,
                    detail TEXT NOT NULL,
                    channels_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def add_event(self, event):
        if event.get("model") != "Acurite-986":
            return False

        try:
            sensor_id = int(event["id"])
            temperature_f = float(event["temperature_F"])
            observed_at = iso_utc(event.get("time"))
        except (KeyError, TypeError, ValueError):
            return False

        with self.lock, self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO readings (
                    observed_at, sensor_id, channel, temperature_f,
                    battery_ok, rssi, snr, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observed_at,
                    sensor_id,
                    event.get("channel"),
                    temperature_f,
                    event.get("battery_ok"),
                    event.get("rssi"),
                    event.get("snr"),
                    json.dumps(event, separators=(",", ":"), sort_keys=True),
                ),
            )
            return cursor.rowcount == 1

    def update_sensor_profile(self, sensor_id, profile, minimum_f=None, maximum_f=None):
        try:
            sensor_id = int(sensor_id)
        except (TypeError, ValueError) as error:
            raise ValueError("sensor ID must be an integer") from error

        if profile not in STORAGE_PROFILES:
            raise ValueError("unknown storage profile")

        profile_config = STORAGE_PROFILES[profile]
        if profile == "custom":
            try:
                minimum_f = float(minimum_f)
                maximum_f = float(maximum_f)
            except (TypeError, ValueError) as error:
                raise ValueError("custom minimum and maximum must be numbers") from error
            if not -100 <= minimum_f <= 200 or not -100 <= maximum_f <= 200:
                raise ValueError("custom temperatures must be between -100°F and 200°F")
            if minimum_f >= maximum_f:
                raise ValueError("custom minimum must be lower than the maximum")
        else:
            minimum_f = profile_config["minimum_f"]
            maximum_f = profile_config["maximum_f"]

        with self.lock, self._connection() as connection:
            known_sensor = str(sensor_id) in self.sensors or connection.execute(
                "SELECT 1 FROM readings WHERE sensor_id = ? LIMIT 1", (sensor_id,)
            ).fetchone()
            if not known_sensor:
                raise KeyError(sensor_id)

            connection.execute(
                """
                INSERT INTO sensor_settings (
                    sensor_id, profile, minimum_f, maximum_f, monitoring, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sensor_id) DO UPDATE SET
                    profile = excluded.profile,
                    minimum_f = excluded.minimum_f,
                    maximum_f = excluded.maximum_f,
                    monitoring = excluded.monitoring,
                    updated_at = excluded.updated_at
                """,
                (
                    sensor_id,
                    profile,
                    minimum_f,
                    maximum_f,
                    int(profile_config["monitoring"]),
                    iso_utc(utc_now()),
                ),
            )

    def notification_settings(self):
        with self.lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM notification_settings WHERE id = 1"
            ).fetchone()
            runtime = connection.execute(
                "SELECT * FROM notifier_runtime WHERE id = 1"
            ).fetchone()
            latest_test = connection.execute(
                """
                SELECT id, status, created_at, completed_at, result
                FROM notification_commands
                WHERE command = 'test'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        settings = {
            "email_enabled": False,
            "email_to": "",
            "ntfy_enabled": False,
            "vtext_enabled": False,
            "phone_number": "",
            "updated_at": None,
        }
        if row:
            settings.update(
                {
                    "email_enabled": bool(row["email_enabled"]),
                    "email_to": row["email_to"],
                    "ntfy_enabled": bool(row["ntfy_enabled"]),
                    "vtext_enabled": bool(row["vtext_enabled"]),
                    "phone_number": row["phone_number"],
                    "updated_at": row["updated_at"],
                }
            )
        settings["runtime"] = (
            {
                "healthy": bool(runtime["healthy"]),
                "detail": runtime["detail"],
                "channels": json.loads(runtime["channels_json"]),
                "updated_at": runtime["updated_at"],
            }
            if runtime
            else None
        )
        settings["latest_test"] = dict(latest_test) if latest_test else None
        return settings

    def update_notification_settings(self, payload):
        email_enabled = payload.get("email_enabled") is True
        ntfy_enabled = payload.get("ntfy_enabled") is True
        vtext_enabled = payload.get("vtext_enabled") is True
        email_to = str(payload.get("email_to") or "").strip()
        recipients = [item.strip() for item in email_to.split(",") if item.strip()]
        invalid_recipients = [
            item
            for item in recipients
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", item)
        ]
        if invalid_recipients:
            raise ValueError("enter valid comma-separated email addresses")
        if email_enabled and not recipients and not vtext_enabled:
            raise ValueError("email alerts require a recipient or Verizon fallback")

        phone_number = re.sub(r"\D", "", str(payload.get("phone_number") or ""))
        if phone_number.startswith("1") and len(phone_number) == 11:
            phone_number = phone_number[1:]
        if phone_number and len(phone_number) != 10:
            raise ValueError("Verizon phone number must contain 10 digits")
        if vtext_enabled and not phone_number:
            raise ValueError("Verizon fallback requires a phone number")

        with self.lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO notification_settings (
                    id, email_enabled, email_to, ntfy_enabled,
                    vtext_enabled, phone_number, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    email_enabled = excluded.email_enabled,
                    email_to = excluded.email_to,
                    ntfy_enabled = excluded.ntfy_enabled,
                    vtext_enabled = excluded.vtext_enabled,
                    phone_number = excluded.phone_number,
                    updated_at = excluded.updated_at
                """,
                (
                    int(email_enabled),
                    ",".join(recipients),
                    int(ntfy_enabled),
                    int(vtext_enabled),
                    phone_number,
                    iso_utc(utc_now()),
                ),
            )
        return self.notification_settings()

    def queue_notification_test(self):
        with self.lock, self._connection() as connection:
            pending = connection.execute(
                """
                SELECT id FROM notification_commands
                WHERE command = 'test' AND status IN ('pending', 'processing')
                LIMIT 1
                """
            ).fetchone()
            if pending:
                return pending["id"]
            cursor = connection.execute(
                """
                INSERT INTO notification_commands (command, status, created_at)
                VALUES ('test', 'pending', ?)
                """,
                (iso_utc(utc_now()),),
            )
            return cursor.lastrowid

    def dashboard_data(self, hours=24):
        hours = max(1, min(int(hours), 24 * 365))
        cutoff = iso_utc(utc_now() - timedelta(hours=hours))
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT observed_at, sensor_id, channel, temperature_f,
                       battery_ok, rssi, snr
                FROM readings
                WHERE observed_at >= ?
                ORDER BY observed_at
                """,
                (cutoff,),
            ).fetchall()

            latest_rows = connection.execute(
                """
                SELECT r.observed_at, r.sensor_id, r.channel, r.temperature_f,
                       r.battery_ok, r.rssi, r.snr
                FROM readings r
                INNER JOIN (
                    SELECT sensor_id, MAX(observed_at) AS observed_at
                    FROM readings
                    GROUP BY sensor_id
                ) latest
                ON latest.sensor_id = r.sensor_id
                AND latest.observed_at = r.observed_at
                """
            ).fetchall()

            setting_rows = connection.execute(
                """
                SELECT sensor_id, profile, minimum_f, maximum_f, monitoring
                FROM sensor_settings
                """
            ).fetchall()

        points_by_sensor = {}
        for row in rows:
            points_by_sensor.setdefault(str(row["sensor_id"]), []).append(
                {"time": row["observed_at"], "temperature_f": row["temperature_f"]}
            )
        latest_by_sensor = {str(row["sensor_id"]): dict(row) for row in latest_rows}
        settings_by_sensor = {
            str(row["sensor_id"]): {
                "profile": row["profile"],
                "minimum_f": row["minimum_f"],
                "maximum_f": row["maximum_f"],
                "monitoring": bool(row["monitoring"]),
            }
            for row in setting_rows
        }

        sensors = []
        known_ids = set(self.sensors) | set(points_by_sensor) | set(latest_by_sensor) | set(settings_by_sensor)
        for sensor_id in sorted(known_ids):
            config = dict(self.sensors.get(sensor_id, {}))
            config.update(settings_by_sensor.get(sensor_id, {}))
            profile = config.get("profile")
            if profile not in STORAGE_PROFILES:
                profile = "unmonitored" if not config.get("monitoring", True) else "custom"
            latest = latest_by_sensor.get(sensor_id)
            sensors.append(
                {
                    "id": int(sensor_id),
                    "name": config.get("name", f"Sensor {sensor_id}"),
                    "channel": config.get("channel") or (latest or {}).get("channel"),
                    "color": config.get("color"),
                    "profile": profile,
                    "monitoring": config.get("monitoring", True),
                    "minimum_f": config.get("minimum_f"),
                    "maximum_f": config.get("maximum_f"),
                    "note": config.get("note"),
                    "status": self._status(config, latest),
                    "latest": latest,
                    "points": points_by_sensor.get(sensor_id, []),
                }
            )

        return {
            "generated_at": iso_utc(utc_now()),
            "hours": hours,
            "profiles": storage_profile_catalog(),
            "sensors": sensors,
        }

    @staticmethod
    def _status(config, latest):
        if not config.get("monitoring", True):
            return "setup"
        if not latest:
            return "no_data"

        observed = datetime.fromisoformat(latest["observed_at"].replace("Z", "+00:00"))
        stale_minutes = int(config.get("stale_minutes", 10))
        if utc_now() - observed > timedelta(minutes=stale_minutes):
            return "stale"
        if latest.get("battery_ok") == 0:
            return "low_battery"

        temperature = latest["temperature_f"]
        minimum = config.get("minimum_f")
        maximum = config.get("maximum_f")
        if maximum is not None and temperature > maximum:
            return "too_warm"
        if minimum is not None and temperature < minimum:
            return "too_cold"
        return "ok"


class SyslogHandler(socketserver.BaseRequestHandler):
    def handle(self):
        payload = self.request[0].decode("utf-8", errors="replace")
        json_start = payload.find("{")
        if json_start < 0:
            return
        try:
            event = json.loads(payload[json_start:])
        except json.JSONDecodeError:
            return
        self.server.store.add_event(event)


class DashboardHandler(SimpleHTTPRequestHandler):
    store = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR / "static"), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if parsed.path == "/api/readings":
            try:
                hours = int(parse_qs(parsed.query).get("hours", ["24"])[0])
            except ValueError:
                self._send_json({"error": "hours must be an integer"}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(self.store.dashboard_data(hours))
            return
        if parsed.path == "/api/admin/notifications":
            if not self._require_admin():
                return
            self._send_json(self.store.notification_settings())
            return
        super().do_GET()

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/admin/notifications":
            if not self._require_admin():
                return
            try:
                payload = self._read_json()
                self._send_json(self.store.update_notification_settings(payload))
            except ValueError as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) != 4 or path_parts[:2] != ["api", "sensors"] or path_parts[3] != "profile":
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 4096:
            self._send_json({"error": "invalid request body"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            self.store.update_sensor_profile(
                path_parts[2],
                payload.get("profile"),
                payload.get("minimum_f"),
                payload.get("maximum_f"),
            )
        except json.JSONDecodeError:
            self._send_json({"error": "request body must be valid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        except KeyError:
            self._send_json({"error": "sensor not found"}, HTTPStatus.NOT_FOUND)
            return

        data = self.store.dashboard_data(24)
        sensor_id = int(path_parts[2])
        sensor = next(sensor for sensor in data["sensors"] if sensor["id"] == sensor_id)
        self._send_json({"sensor": sensor, "profiles": data["profiles"]})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/admin/notifications/test":
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not self._require_admin():
            return
        command_id = self.store.queue_notification_test()
        self._send_json(
            {"status": "queued", "command_id": command_id}, HTTPStatus.ACCEPTED
        )

    def _read_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid request body") from error
        if content_length <= 0 or content_length > 4096:
            raise ValueError("invalid request body")
        try:
            payload = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError as error:
            raise ValueError("request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _require_admin(self):
        if not ADMIN_API_TOKEN:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return False
        supplied = self.headers.get("X-Admin-Token", "")
        if not secrets.compare_digest(supplied, ADMIN_API_TOKEN):
            self._send_json({"error": "administrator token required"}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def _send_json(self, value, status=HTTPStatus.OK):
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message_format, *args):
        print(f"http: {message_format % args}", flush=True)


def serve():
    sensors = load_sensors()
    store = ReadingStore(sensors=sensors)
    DashboardHandler.store = store

    udp_server = socketserver.ThreadingUDPServer(("0.0.0.0", SYSLOG_PORT), SyslogHandler)
    udp_server.store = store
    udp_thread = threading.Thread(target=udp_server.serve_forever, daemon=True)
    udp_thread.start()

    http_server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), DashboardHandler)

    def shutdown(_signum, _frame):
        threading.Thread(target=http_server.shutdown, daemon=True).start()
        threading.Thread(target=udp_server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(
        f"Dashboard listening on :{HTTP_PORT}; rtl_433 syslog on UDP :{SYSLOG_PORT}",
        flush=True,
    )
    try:
        http_server.serve_forever()
    finally:
        udp_server.shutdown()
        http_server.server_close()
        udp_server.server_close()


if __name__ == "__main__":
    serve()
