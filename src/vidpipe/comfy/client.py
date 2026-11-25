"""A small client for the ComfyUI HTTP API (stdlib only).

Jobs are asynchronous on the server: :meth:`ComfyClient.submit` returns at once with a prompt id,
:meth:`ComfyClient.wait` polls ``/history`` until the job finished, and the results are fetched with
:meth:`ComfyClient.download`. Errors say whether another attempt could help (``retryable``).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any, ClassVar, cast

from vidpipe.contracts import GenerationError

DEFAULT_URL = "http://127.0.0.1:8188"
#: Subfolder of ComfyUI's input and output folders that vidpipe's files go into.
SUBFOLDER = "vidpipe"


class ComfyError(GenerationError):
    """Something went wrong talking to ComfyUI or running a job on it."""

    #: Whether a new attempt (with a new seed) could succeed.
    retryable: ClassVar[bool] = False
    #: GPU time the failed job reported, when it did.
    gpu_seconds: float | None = None


class ComfyUnreachable(ComfyError):
    """No ComfyUI answered at the URL."""


class ComfyRejected(ComfyError):
    """ComfyUI refused the workflow (a missing model or node, a bad value)."""


class ComfyInterrupted(ComfyError):
    """Someone cancelled the job in ComfyUI."""


class ComfyJobFailed(ComfyError):
    """The job raised an error while running."""

    retryable = True

    def __init__(
        self, message: str, *, oom: bool = False, gpu_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        self.oom = oom
        self.gpu_seconds = gpu_seconds


class ComfyTimeout(ComfyError):
    """The job did not finish in time."""

    retryable = True


class ComfyJobLost(ComfyError):
    """The job is neither queued nor in the history (ComfyUI restarted, or it was deleted)."""

    retryable = True


class ComfyBadOutput(ComfyError):
    """The job succeeded but its output is missing."""

    retryable = True


@dataclass(frozen=True)
class RemoteFile:
    """A file ComfyUI wrote, as ``/history`` names it and ``/view`` serves it."""

    filename: str
    subfolder: str = ""
    type: str = "output"


@dataclass(frozen=True)
class Finished:
    #: Node id -> what it output, e.g. ``{"save": {"images": [...]}}``.
    outputs: dict[str, Any]
    #: Execution time from the server's own timestamps.
    gpu_seconds: float | None

    def files(self, node: str, key: str) -> list[RemoteFile]:
        items = cast(list[Any], self.outputs.get(node, {}).get(key, []))
        found = [cast(dict[str, Any], i) for i in items if isinstance(i, dict)]
        return [
            RemoteFile(i["filename"], i.get("subfolder", ""), i.get("type", "output"))
            for i in found
            if "filename" in i
        ]


def _is_out_of_memory(kind: str, message: str) -> bool:
    text = f"{kind} {message}".lower()
    signs = ("outofmemory", "out of memory", "allocation on device", "not enough memory")
    return any(sign in text for sign in signs)


def _finished(entry: Mapping[str, Any]) -> Finished:
    status = cast(dict[str, Any], entry.get("status") or {})
    messages = {
        str(kind): cast(dict[str, Any], data)
        for kind, data in cast(list[list[Any]], status.get("messages", []))
    }
    ends = ("execution_success", "execution_error", "execution_interrupted")
    start = messages.get("execution_start", {}).get("timestamp")
    end = next((messages[k].get("timestamp") for k in ends if k in messages), None)
    seconds = (end - start) / 1000 if start is not None and end is not None else None
    if "execution_interrupted" in messages:
        raise ComfyInterrupted("the job was interrupted in ComfyUI")
    if status.get("status_str") == "error":
        error = messages.get("execution_error", {})
        kind = str(error.get("exception_type", ""))
        message = str(error.get("exception_message", "")).strip()
        summary = message.splitlines()[0] if message else "unknown error"
        raise ComfyJobFailed(
            f"{error.get('node_type', 'ComfyUI')}: {kind}: {summary}",
            oom=_is_out_of_memory(kind, message),
            gpu_seconds=seconds,
        )
    return Finished(outputs=dict(entry.get("outputs") or {}), gpu_seconds=seconds)


def _rejection(body: bytes) -> str:
    """Why ``/prompt`` refused a workflow: ComfyUI's error and per-node errors."""
    try:
        payload = cast(dict[str, Any], json.loads(body))
        message = cast(dict[str, Any], payload.get("error") or {}).get("message", "")
        nodes = json.dumps(payload.get("node_errors") or {})
        return f"{message} {nodes}"[:1000]
    except (ValueError, AttributeError):
        return body.decode("utf-8", "replace")[:1000]


class ComfyClient:
    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        request_timeout_s: float = 60.0,
        unreachable_grace_s: float = 30.0,
    ) -> None:
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            raise ValueError(f"ComfyUI url {url!r} must start with http:// or https://")
        self.url = url.rstrip("/")
        self.request_timeout_s = request_timeout_s
        #: How long a running job's server may stop answering before the job is given up.
        self.unreachable_grace_s = unreachable_grace_s
        self.client_id = uuid.uuid4().hex
        # ComfyUI is a local or LAN service: system proxy settings must not apply.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ------------------------------------------------------------------------------ transport

    def _request(
        self, path: str, *, data: bytes | None = None, content_type: str | None = None
    ) -> bytes:
        headers = {"Content-Type": content_type} if content_type else {}
        request = urllib.request.Request(self.url + path, data=data, headers=headers)
        try:
            with self._opener.open(request, timeout=self.request_timeout_s) as response:
                return cast(bytes, response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if path == "/prompt" and exc.code == 400:
                raise ComfyRejected(f"ComfyUI rejected the workflow: {_rejection(body)}") from exc
            raise ComfyError(f"ComfyUI answered {exc.code} to {path}") from exc
        except (OSError, HTTPException) as exc:  # URLError and timeouts are OSErrors
            raise ComfyUnreachable(
                f"cannot reach ComfyUI at {self.url} ({exc}); start it, or set `comfyui.url` in "
                "vidpipe.yaml"
            ) from exc

    def _get_json(self, path: str) -> Any:
        return self._decode(path, self._request(path))

    def _post_json(self, path: str, payload: Any) -> bytes:
        return self._request(
            path, data=json.dumps(payload).encode("utf-8"), content_type="application/json"
        )

    def _decode(self, path: str, body: bytes) -> Any:
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ComfyError(f"{self.url}{path} did not answer JSON: is it ComfyUI?") from exc

    # ------------------------------------------------------------------------------- the API

    def system_stats(self) -> dict[str, Any]:
        stats = self._get_json("/system_stats")
        if not isinstance(stats, dict):
            raise ComfyError(f"{self.url}/system_stats did not return system information")
        return cast(dict[str, Any], stats)

    def node_types(self) -> frozenset[str]:
        """The node classes currently registered on this server."""
        info = self._get_json("/object_info")
        if not isinstance(info, dict):
            raise ComfyError(f"{self.url}/object_info did not return a node catalog")
        return frozenset(cast(dict[str, Any], info))

    def model_names(self, category: str) -> frozenset[str]:
        """Model filenames visible to this server, including extra model paths."""
        files = self._get_json(f"/models/{urllib.parse.quote(category, safe='')}")
        if not isinstance(files, list) or not all(
            isinstance(f, str) for f in cast(list[Any], files)
        ):
            raise ComfyError(f"{self.url}/models/{category} did not return a list of filenames")
        return frozenset(name.replace("\\", "/") for name in cast(list[str], files))

    def upload_image(self, path: Path) -> str:
        """Upload an input image; returns the value a ``LoadImage`` node takes.

        The file is named after its content, so the same picture is stored once.
        """
        data = path.read_bytes()
        name = hashlib.sha256(data).hexdigest()[:32] + path.suffix.lower()
        boundary = uuid.uuid4().hex
        body = bytearray()
        for field, value in (("subfolder", SUBFOLDER), ("overwrite", "true")):
            body += f"--{boundary}\r\nContent-Disposition: form-data; ".encode()
            body += f'name="{field}"\r\n\r\n{value}\r\n'.encode()
        body += f"--{boundary}\r\nContent-Disposition: form-data; ".encode()
        body += f'name="image"; filename="{name}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n" + data
        body += f"\r\n--{boundary}--\r\n".encode()
        reply = self._request(
            "/upload/image",
            data=bytes(body),
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        saved = self._decode("/upload/image", reply)
        folder = saved.get("subfolder", "")
        return f"{folder}/{saved['name']}" if folder else str(saved["name"])

    def submit(self, graph: Mapping[str, Any]) -> str:
        """Queue an API-format workflow; returns its prompt id."""
        payload = {"prompt": graph, "client_id": self.client_id}
        return str(self._decode("/prompt", self._post_json("/prompt", payload))["prompt_id"])

    def history(self, prompt_id: str) -> dict[str, Any] | None:
        """The finished job's history entry; ``None`` while it is not finished."""
        return self._get_json(f"/history/{prompt_id}").get(prompt_id)

    def queued_ids(self) -> list[str]:
        """The prompt ids running or waiting to run, whoever submitted them."""
        queue = self._get_json("/queue")
        entries = [*queue.get("queue_running", []), *queue.get("queue_pending", [])]
        return [str(entry[1]) for entry in entries]

    def queue_counts(self) -> tuple[int, int]:
        """How many jobs are running and how many are waiting, whoever submitted them."""
        queue = self._get_json("/queue")
        return len(queue.get("queue_running", [])), len(queue.get("queue_pending", []))

    def wait(self, prompt_id: str, *, timeout_s: float, poll_s: float = 0.5) -> Finished:
        """Poll until the job finished; raises the matching :class:`ComfyError` if it failed."""
        deadline = time.monotonic() + timeout_s
        silent_since: float | None = None
        while True:
            try:
                entry = self.history(prompt_id)
                if entry is None and prompt_id not in self.queued_ids():
                    # It may have finished between the two requests: look once more.
                    entry = self.history(prompt_id)
                    if entry is None:
                        raise ComfyJobLost(f"ComfyUI no longer knows job {prompt_id}")
                silent_since = None
            except ComfyUnreachable:
                silent_since = silent_since or time.monotonic()
                if time.monotonic() - silent_since >= self.unreachable_grace_s:
                    raise
                entry = None
            if entry is not None:
                return _finished(entry)
            if time.monotonic() >= deadline:
                raise ComfyTimeout(f"the job did not finish within {timeout_s:g} s")
            time.sleep(poll_s)

    def download(self, file: RemoteFile) -> bytes:
        query = urllib.parse.urlencode(
            {"filename": file.filename, "subfolder": file.subfolder, "type": file.type}
        )
        try:
            return self._request(f"/view?{query}")
        except ComfyUnreachable:
            raise
        except ComfyError as exc:
            raise ComfyBadOutput(f"cannot fetch {file.filename}: {exc}") from exc

    def cancel(self, prompt_id: str) -> None:
        """Take a job out of the queue, or interrupt it if it is running. Only this job is
        touched, and failures are ignored (it is used while handling another error)."""
        for path, payload in (
            ("/queue", {"delete": [prompt_id]}),
            ("/interrupt", {"prompt_id": prompt_id}),
        ):
            try:
                self._post_json(path, payload)
            except ComfyError:
                continue

    def free(self) -> None:
        """Ask ComfyUI to unload its models and free memory (best effort)."""
        try:
            self._post_json("/free", {"unload_models": True, "free_memory": True})
        except ComfyError:
            return
