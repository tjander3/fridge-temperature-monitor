#!/usr/bin/env python3
"""Expose a loopback-only dashboard on one explicitly selected LAN address."""

from __future__ import annotations

import argparse
import logging
import socket
import socketserver
import threading


LOGGER = logging.getLogger("fridge-monitor-lan-proxy")
BUFFER_SIZE = 64 * 1024


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
        try:
            upstream = socket.create_connection(
                (server.target_host, server.target_port),
                timeout=server.connect_timeout,
            )
        except OSError as error:
            LOGGER.warning("Could not connect to dashboard: %s", error)
            return

        with upstream:
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
