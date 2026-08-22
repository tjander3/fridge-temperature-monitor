import http.server
import threading
import unittest
import urllib.request

from lan_proxy import LanProxyServer


class _DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
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
        finally:
            proxy.shutdown()
            proxy.server_close()
            dashboard.shutdown()
            dashboard.server_close()
            proxy_thread.join(timeout=2)
            dashboard_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
