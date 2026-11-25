"""The UI's HTTP API for tests: a real server on a free port, and a stdlib client for it.

:class:`UiServer` runs ``vidpipe.ui.create_app`` on uvicorn in a background thread;
:class:`UiProcess` runs the ``vidpipe ui`` command itself. Requests go over a real socket, so the
SSE stream behaves as it does for a browser.
"""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from vidpipe.ui import create_app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class Event:
    event: str
    data: Any
    id: str | None = None


class UiClient:
    """Requests to a UI listening on ``127.0.0.1:port``."""

    port: int

    def get(self, path: str, headers: dict[str, str] | None = None) -> Response:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers=headers or {})
            reply = conn.getresponse()
            headers_ = {k.lower(): v for k, v in reply.getheaders()}
            return Response(reply.status, headers_, reply.read())
        finally:
            conn.close()

    def events(
        self, path: str = "/api/events", headers: dict[str, str] | None = None
    ) -> EventStream:
        return EventStream(self.port, path, headers or {})


class UiServer(UiClient):
    """``create_app(project)`` served in this process on ``127.0.0.1:port`` until :meth:`stop`."""

    def __init__(self, project: Path) -> None:
        self.port = free_port()
        app = create_app(project, poll_interval=0.05)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning", timeout_graceful_shutdown=1
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert self.thread.is_alive(), "the UI server exited on start"
            assert time.monotonic() < deadline, "the UI server never started"
            time.sleep(0.02)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class UiProcess(UiClient):
    """``vidpipe ui <project> <args>`` in its own process, as a creator starts it.

    ``output`` holds what it printed up to the line saying it is listening.
    """

    def __init__(self, project: Path, *args: str) -> None:
        self.port = free_port()
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "vidpipe", "ui", str(project), "--port", str(self.port)]
            + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        assert self.process.stdout is not None
        self.output: list[str] = []
        for line in self.process.stdout:
            self.output.append(line.rstrip("\n"))
            if "Press Ctrl+C" in line:  # the end of the banner
                break
        else:
            raise AssertionError("vidpipe ui exited:\n" + "\n".join(self.output))
        deadline = time.monotonic() + 10
        while True:  # the banner comes just before uvicorn binds the port
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                break
            except OSError:
                assert self.process.poll() is None, "vidpipe ui exited on start"
                assert time.monotonic() < deadline, "vidpipe ui never started listening"
                time.sleep(0.05)

    def stop(self) -> None:
        self.process.kill()
        self.process.wait()
        if self.process.stdout:
            self.process.stdout.close()


class EventStream:
    """One open SSE connection; :meth:`next` reads the next event (skipping comments)."""

    def __init__(self, port: int, path: str, headers: dict[str, str]) -> None:
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        self.conn.request("GET", path, headers={"Accept": "text/event-stream", **headers})
        self.response = self.conn.getresponse()
        self.status = self.response.status
        self.headers = {k.lower(): v for k, v in self.response.getheaders()}

    def next(self) -> Event:
        fields: dict[str, str] = {}
        data: list[str] = []
        while True:
            line = self.response.readline()
            if not line:
                raise EOFError("the event stream ended")
            text = line.decode("utf-8").rstrip("\r\n")
            if text == "":
                if data:  # as in a browser, a block without data (say only `retry:`) is no event
                    payload = json.loads("\n".join(data))
                    return Event(fields.get("event", "message"), payload, fields.get("id"))
                fields.clear()
                continue
            if text.startswith(":"):
                continue
            name, _, value = text.partition(":")
            value = value.removeprefix(" ")
            if name == "data":
                data.append(value)
            else:
                fields[name] = value

    def until(self, predicate: Callable[[Event], bool], timeout: float = 60) -> Iterator[Event]:
        """Events up to and including the first one ``predicate`` accepts."""
        deadline = time.monotonic() + timeout
        while True:
            assert time.monotonic() < deadline, "the expected event never came"
            event = self.next()
            yield event
            if predicate(event):
                return

    def close(self) -> None:
        self.conn.close()
