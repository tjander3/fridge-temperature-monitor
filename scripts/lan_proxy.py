#!/usr/bin/env python3
"""Expose a loopback-only dashboard on one explicitly selected LAN address."""

from __future__ import annotations

import argparse
import json
import logging
import socket
import socketserver
import threading
from urllib.error import HTTPError
from urllib.request import urlopen


LOGGER = logging.getLogger("fridge-monitor-lan-proxy")
BUFFER_SIZE = 64 * 1024
MAX_REQUEST_HEAD = 64 * 1024


def compact_dashboard_data(dashboard: dict) -> dict:
    """Adapt the legacy readings response while a container upgrade is pending."""
    sensors = []
    for sensor in dashboard.get("sensors", []):
        latest = sensor.get("latest") or {}
        sensors.append(
            {
                "id": sensor.get("id"),
                "name": sensor.get("name"),
                "channel": sensor.get("channel"),
                "status": sensor.get("status"),
                "profile": sensor.get("profile"),
                "monitoring": sensor.get("monitoring", True),
                "minimum_f": sensor.get("minimum_f"),
                "maximum_f": sensor.get("maximum_f"),
                "temperature_f": latest.get("temperature_f"),
                "observed_at": latest.get("observed_at"),
                "battery_ok": latest.get("battery_ok"),
                "rssi": latest.get("rssi"),
                "snr": latest.get("snr"),
            }
        )
    problem = any(
        sensor["monitoring"] and sensor["status"] != "ok" for sensor in sensors
    )
    return {
        "generated_at": dashboard.get("generated_at"),
        "status": "attention" if problem else "ok",
        "sensors": sensors,
        "notifier": None,
    }


def home_assistant_payload(host: str, port: int, timeout: float) -> bytes:
    native_url = f"http://{host}:{port}/api/home-assistant"
    try:
        with urlopen(native_url, timeout=timeout) as response:
            return response.read()
    except HTTPError as error:
        if error.code != 404:
            raise
        error.close()

    legacy_url = f"http://{host}:{port}/api/readings?hours=1"
    with urlopen(legacy_url, timeout=timeout) as response:
        return json.dumps(
            compact_dashboard_data(json.load(response)), separators=(",", ":")
        ).encode("utf-8")


def read_request_head(connection: socket.socket) -> bytes:
    request = bytearray()
    while b"\r\n\r\n" not in request and len(request) < MAX_REQUEST_HEAD:
        chunk = connection.recv(min(BUFFER_SIZE, MAX_REQUEST_HEAD - len(request)))
        if not chunk:
            break
        request.extend(chunk)
    return bytes(request)


def send_json_response(connection: socket.socket, body: bytes) -> None:
    headers = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    connection.sendall(headers + body)


def copy_socket(source: socket.socket, destination: socket.socket) -> None:
    try:
        while chunk := source.recv(BUFFER_SIZE):
            destination.sendall(chunk)
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class LanProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, LanProxyServer)
        request_head = read_request_head(self.request)
        request_line = request_head.split(b"\r\n", 1)[0]
        if request_line.startswith(b"GET /api/home-assistant "):
            try:
                body = home_assistant_payload(
                    server.target_host, server.target_port, server.connect_timeout
                )
                send_json_response(self.request, body)
            except (OSError, ValueError) as error:
                LOGGER.warning("Could not build Home Assistant status: %s", error)
            return

        try:
            upstream = socket.create_connection(
                (server.target_host, server.target_port),
                timeout=server.connect_timeout,
            )
        except OSError as error:
            LOGGER.warning("Could not connect to dashboard: %s", error)
            return

        with upstream:
            upstream.sendall(request_head)
            request_to_upstream = threading.Thread(
                target=copy_socket,
                args=(self.request, upstream),
                daemon=True,
            )
            request_to_upstream.start()
            copy_socket(upstream, self.request)
            request_to_upstream.join(timeout=1)


class LanProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        listen_address: tuple[str, int],
        target_address: tuple[str, int],
        connect_timeout: float = 10,
    ) -> None:
        self.target_host, self.target_port = target_address
        self.connect_timeout = connect_timeout
        super().__init__(listen_address, LanProxyHandler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", type=int, default=8080)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=8080)
    parser.add_argument("--log-file")
    return parser.parse_args()


def configure_logging(log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def main() -> int:
    args = parse_args()
    configure_logging(args.log_file)
    with LanProxyServer(
        (args.listen_host, args.listen_port),
        (args.target_host, args.target_port),
    ) as server:
        LOGGER.info(
            "Forwarding %s:%d to %s:%d",
            args.listen_host,
            args.listen_port,
            args.target_host,
            args.target_port,
        )
        server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
