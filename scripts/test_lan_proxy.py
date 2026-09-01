import json
import http.server
import threading
import unittest
import urllib.request

from lan_proxy import LanProxyServer


class _DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/home-assistant"):
            self.send_error(404)
            return
        if self.path == "/api/readings?hours=1":
            body = json.dumps(
                {
                    "generated_at": "2026-09-01T12:00:00Z",
                    "sensors": [
                        {
                            "id": 1,
                            "name": "Mini fridge",
                            "status": "ok",
                            "monitoring": True,
                            "latest": {
                                "temperature_f": 41,
                                "observed_at": "2026-09-01T11:59:00Z",
                            },
                            "points": [{"temperature_f": 40}],
                        }
                    ],
                }
            ).encode()
        elif self.path == "/api/readings?hours=8760":
            body = json.dumps(
                {
                    "generated_at": "2026-09-01T12:00:00Z",
                    "hours": 8760,
                    "sensors": [
                        {
                            "id": 1,
                            "name": "Mini fridge",
                            "color": "#37c9d9",
                            "points": [
                                {"time": "2026-08-17T10:00:00Z", "temperature_f": 40},
                                {"time": "2026-08-17T10:01:00Z", "temperature_f": 44},
                            ],
                        }
                    ],
                }
            ).encode()
        else:
            body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        pass


class LanProxyTests(unittest.TestCase):
    def test_relays_http_between_distinct_listeners(self):
        dashboard = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _DashboardHandler)
        dashboard_thread = threading.Thread(target=dashboard.serve_forever, daemon=True)
        dashboard_thread.start()

        proxy = LanProxyServer(
            ("127.0.0.1", 0),
            ("127.0.0.1", dashboard.server_port),
        )
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        proxy_thread.start()

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{proxy.server_address[1]}/api/health",
                timeout=5,
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'{"status":"ok"}')

            with urllib.request.urlopen(
                f"http://127.0.0.1:{proxy.server_address[1]}/api/home-assistant",
                timeout=5,
            ) as response:
                result = json.load(response)
                self.assertEqual(result["sensors"][0]["temperature_f"], 41)
                self.assertNotIn("points", result["sensors"][0])

            with urllib.request.urlopen(
                f"http://127.0.0.1:{proxy.server_address[1]}/api/home-assistant/history?hours=8760&max_points=48",
                timeout=5,
            ) as response:
                history = json.load(response)
                self.assertEqual(history["requested_hours"], 8760)
                points = history["sensors"][0]["points"]
                self.assertEqual(min(point["minimum_f"] for point in points), 40)
                self.assertEqual(max(point["maximum_f"] for point in points), 44)
        finally:
            proxy.shutdown()
            proxy.server_close()
            dashboard.shutdown()
            dashboard.server_close()
            proxy_thread.join(timeout=2)
            dashboard_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
