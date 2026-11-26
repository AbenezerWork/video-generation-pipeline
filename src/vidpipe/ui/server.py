"""``vidpipe ui <project>``: serve the UI for one project until Ctrl+C."""

from __future__ import annotations

import contextlib
import ipaddress
import socket
from pathlib import Path

import uvicorn

from vidpipe.project import Project
from vidpipe.ui.access import new_token
from vidpipe.ui.app import create_app
from vidpipe.ui.runs import ask_on_quit

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
#: The ``Host`` names accepted when bound to this machine only.
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1", "[::1]")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _shown_host(host: str) -> str:
    """The address to print for ``host``: this machine's LAN address for a wildcard bind."""
    if host not in ("0.0.0.0", "::", ""):
        return f"[{host}]" if ":" in host else host
    try:  # no packet is sent: connecting a UDP socket only picks the outgoing interface
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
    except OSError:
        return socket.gethostname()


def serve(project_dir: Path, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Serve the UI for ``project_dir`` on ``host:port``.

    Bound to this machine (the default), no token is needed and only loopback ``Host`` names are
    accepted. Bound to anything else, a fresh token is required (:mod:`vidpipe.ui.access`) and the
    link carrying it is printed.
    """
    Project(project_dir)  # fail now, with the usual message, on a missing or invalid project
    if is_loopback(host):
        app = create_app(project_dir, allowed_hosts=LOOPBACK_NAMES)
        print(f"vidpipe UI for {project_dir.resolve().name}: http://{_shown_host(host)}:{port}/")
    else:
        token = new_token()
        app = create_app(project_dir, token=token)
        print(f"vidpipe UI for {project_dir.resolve().name}, open to the network.")
        print(f"Open: http://{_shown_host(host)}:{port}/?token={token}")
        print("Anyone with this link can watch and control runs of this project.")
    print("Press Ctrl+C to quit.", flush=True)
    # Uvicorn re-raises SIGINT after it finishes shutting down.
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=2)
    ask_on_quit(project_dir)
