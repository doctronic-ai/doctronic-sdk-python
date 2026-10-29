"""A real HTTP server on 127.0.0.1, for behavior a mock transport can't show: socket timeouts and
closing a stream while another thread or task is blocked reading it."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FRAME = (
    b'event: message.start\ndata: {"type":"message.start","role":"assistant","messageId":"m1"}\n\n'
)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: LocalServer

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests += 1
        time.sleep(float(self.headers.get("X-Test-Delay-Headers", "0")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        gap = float(self.headers.get("X-Test-Gap", "0"))
        try:
            for _ in range(int(self.headers.get("X-Test-Frames", "3"))):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(FRAME), FRAME))
                self.wfile.flush()
                if self.server.closing.wait(gap):
                    return
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            pass  # The client hung up, which is what some tests do.

    def log_message(self, format: str, *args: object) -> None:
        pass


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests = 0
        self.closing = threading.Event()

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}/api/v1"


def serve() -> Iterator[LocalServer]:
    server = LocalServer()
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.closing.set()
        server.shutdown()
        server.server_close()
