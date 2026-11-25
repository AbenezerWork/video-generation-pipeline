"""A stand-in ComfyUI server: the HTTP API vidpipe talks to, in process and without a GPU.

Modelled on ComfyUI 0.46.3 (``server.py``, ``execution.py``): ``/upload/image``, ``/prompt``,
``/history/{id}``, ``/queue``, ``/interrupt``, ``/free``, ``/view`` and ``/system_stats``, with the
same response and error shapes. Jobs "run" for a few history polls and then succeed or fail as the
test scripted (:meth:`FakeComfyUI.script`).

Outputs imitate the real server where vidpipe cares: the same graph and input images give the same
pixels, any change to the prompt (even whitespace), seed or inputs changes them, and a latent size
that is not a multiple of 16 is silently rounded down.

To fake another output node (video, audio), add its writer to :data:`WRITERS`.
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import threading
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

#: What a scripted job does. ``success`` is the default when the script has run out.
#: ``error``/``oom``: an ``execution_error``; ``hang``: runs until interrupted; ``lost``: vanishes
#: (as after a server restart); ``reject``: ``/prompt`` answers 400; ``interrupted``: someone
#: pressed cancel in ComfyUI; ``no_output``: succeeds without saving anything.
OUTCOMES = ("success", "error", "oom", "hang", "lost", "reject", "interrupted", "no_output")

Graph = dict[str, dict[str, Any]]


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def png(width: int, height: int, rgb: bytes, metadata: str = "") -> bytes:
    raw = (b"\x00" + rgb * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + (_chunk(b"tEXt", b"prompt\x00" + metadata.encode()) if metadata else b"")
        + _chunk(b"IDAT", zlib.compress(raw, 1))
        + _chunk(b"IEND", b"")
    )


@dataclass
class Job:
    """One ``POST /prompt`` as the server received it."""

    prompt_id: str
    graph: Graph
    client_id: str | None
    outcome: str
    polls: int = 0
    state: str = "queued"  # queued | running | done | gone
    history: dict[str, Any] | None = None

    def input(self, node: str, name: str) -> Any:
        return self.graph[node]["inputs"][name]

    @property
    def images(self) -> list[str]:
        """The input image names its ``LoadImage`` nodes refer to, in node order."""
        return [
            node["inputs"]["image"]
            for _, node in sorted(self.graph.items())
            if node["class_type"] == "LoadImage"
        ]

    def size(self) -> tuple[int, int]:
        for node in self.graph.values():
            inputs = node["inputs"]
            if "Latent" in node["class_type"] and "width" in inputs:
                return inputs["width"] // 16 * 16, inputs["height"] // 16 * 16
        return 64, 64

    def identity(self, uploads: dict[str, bytes]) -> bytes:
        """What decides the output: every node input except where it is saved."""
        graph = {
            key: {k: v for k, v in node["inputs"].items() if k != "filename_prefix"}
            for key, node in self.graph.items()
        }
        sha = hashlib.sha256(json.dumps(graph, sort_keys=True).encode())
        for name in self.images:
            sha.update(uploads.get(name, b""))
        return sha.digest()


def _save_image(job: Job, uploads: dict[str, bytes]) -> tuple[str, str, bytes]:
    """``(output key, file suffix, file bytes)`` for a ``SaveImage`` node."""
    width, height = job.size()
    colour = job.identity(uploads)[:3]
    return "images", ".png", png(width, height, colour, json.dumps(job.graph))


def _save_audio(job: Job, _uploads: dict[str, bytes]) -> tuple[str, str, bytes]:
    seconds = next(
        node["inputs"]["seconds"]
        for node in job.graph.values()
        if node["class_type"] == "EmptyAceStep1.5LatentAudio"
    )
    frequency = 110 + job.identity({})[0]
    with TemporaryDirectory() as directory:
        path = Path(directory) / "music.flac"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000",
                "-t",
                str(seconds),
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        audio = path.read_bytes()
    return "audio", ".flac", audio


#: Output node class -> what it writes.
WRITERS: dict[str, Callable[[Job, dict[str, bytes]], tuple[str, str, bytes]]] = {
    "SaveImage": _save_image,
    "SaveAudioAdvanced": _save_audio,
}


@dataclass
class FakeComfyUI:
    #: How many ``/history`` polls a job stays unfinished.
    polls_to_finish: int = 1
    #: Execution time reported by the status timestamps.
    job_seconds: float = 2.5
    jobs: list[Job] = field(default_factory=list[Job])
    uploads: dict[str, bytes] = field(default_factory=dict[str, bytes])
    outputs: dict[str, bytes] = field(default_factory=dict[str, bytes])
    #: Every ``/free`` body, and the prompt ids sent to ``/interrupt`` and ``/queue`` delete.
    freed: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    interrupted: list[str | None] = field(default_factory=list[str | None])
    deleted: list[str] = field(default_factory=list[str])
    #: Calls made, as ``"POST /prompt"``; shows what happened in what order.
    requests: list[str] = field(default_factory=list[str])
    version: str = "0.46.3"
    node_types: set[str] = field(default_factory=set[str])
    models: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    _script: list[str] = field(default_factory=list[str])
    #: Decides a job's outcome when set (before the script is consulted).
    decide: Callable[[Job], str | None] | None = None

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # ------------------------------------------------------------------------------ control

    def start(self) -> FakeComfyUI:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def script(self, *outcomes: str) -> None:
        """The outcomes of the next submitted jobs, in order."""
        assert set(outcomes) <= set(OUTCOMES), outcomes
        self._script.extend(outcomes)

    @property
    def running(self) -> list[Job]:
        return [j for j in self.jobs if j.state in ("queued", "running")]

    # ------------------------------------------------------------------------------ the API

    def upload(self, filename: str, subfolder: str, data: bytes) -> dict[str, str]:
        with self._lock:
            name = f"{subfolder}/{filename}" if subfolder else filename
            self.uploads[name] = data
        return {"name": filename, "subfolder": subfolder, "type": "input"}

    def submit(self, graph: Graph, client_id: str | None) -> tuple[int, dict[str, Any]]:
        problems = self._invalid(graph)
        with self._lock:
            job = Job(str(uuid.uuid4()), graph, client_id, "success")
            decided = self.decide(job) if self.decide else None
            job.outcome = decided or (self._script.pop(0) if self._script else "success")
            if job.outcome == "reject":
                problems = problems or {"unet": "Value not in list: unet_name"}
            if problems:
                error = {"type": "prompt_outputs_failed_validation", "message": "Prompt failed"}
                return 400, {"error": error, "node_errors": problems}
            self.jobs.append(job)
        return 200, {"prompt_id": job.prompt_id, "number": len(self.jobs), "node_errors": {}}

    def _invalid(self, graph: Graph) -> dict[str, str]:
        problems: dict[str, str] = {}
        for key, node in graph.items():
            if "class_type" not in node:
                problems[key] = "missing class_type"
                continue
            for name, value in node["inputs"].items():
                if isinstance(value, list) and str(cast(list[Any], value)[0]) not in graph:
                    problems[key] = f"{name} links to a missing node"
            if node["class_type"] == "LoadImage" and node["inputs"]["image"] not in self.uploads:
                problems[key] = f"Invalid image file: {node['inputs']['image']}"
        return problems

    def history(self, prompt_id: str) -> dict[str, Any]:
        with self._lock:
            job = next((j for j in self.jobs if j.prompt_id == prompt_id), None)
            if job is None or job.state == "gone":
                return {}
            if job.history is None:
                job.polls += 1
                job.state = "running"
                if job.outcome == "lost":
                    job.state = "gone"
                    return {}
                if job.outcome == "hang" or job.polls <= self.polls_to_finish:
                    return {}
                self._finish(job, job.outcome)
            return {prompt_id: job.history}

    def _finish(self, job: Job, outcome: str) -> None:
        start = 1_700_000_000_000
        end = start + round(self.job_seconds * 1000)
        ids = {"prompt_id": job.prompt_id}
        messages: list[list[Any]] = [["execution_start", {**ids, "timestamp": start}]]
        outputs: dict[str, Any] = {}
        if outcome in ("success", "no_output"):
            messages.append(["execution_success", {**ids, "timestamp": end}])
            if outcome == "success":
                outputs = self._write_outputs(job)
        elif outcome in ("interrupted", "hang"):
            stopped = {**ids, "node_id": "sample", "timestamp": end}
            messages.append(["execution_interrupted", stopped])
        else:
            kind, message = (
                ("torch.OutOfMemoryError", "Allocation on device \nThis error means you ran out of"
                 " memory on your GPU.")
                if outcome == "oom"
                else ("RuntimeError", "something went wrong in the sampler")
            )  # fmt: skip
            error = {**ids, "node_id": "sample", "node_type": "SamplerCustomAdvanced"}
            error |= {"exception_type": kind, "exception_message": message, "timestamp": end}
            messages.append(["execution_error", error])
        ok = outcome in ("success", "no_output")
        status = {"status_str": "success" if ok else "error", "completed": ok, "messages": messages}
        job.history = {"prompt": [], "outputs": outputs, "status": status}
        job.state = "done"

    def _write_outputs(self, job: Job) -> dict[str, Any]:
        outputs: dict[str, Any] = {}
        for key, node in job.graph.items():
            writer = WRITERS.get(node["class_type"])
            if writer is None:
                continue
            output_key, suffix, data = writer(job, self.uploads)
            subfolder, _, stem = node["inputs"]["filename_prefix"].rpartition("/")
            filename = f"{stem}_{len(self.outputs) + 1:05d}_{suffix}"
            self.outputs[f"{subfolder}/{filename}"] = data
            item = {"filename": filename, "subfolder": subfolder, "type": "output"}
            outputs[key] = {output_key: [item]}
        return outputs

    def queue(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queue_running": [[0, j.prompt_id] for j in self.jobs if j.state == "running"],
                "queue_pending": [[0, j.prompt_id] for j in self.jobs if j.state == "queued"],
            }

    def delete(self, prompt_ids: list[str]) -> None:
        with self._lock:
            self.deleted.extend(prompt_ids)
            for job in self.jobs:
                if job.prompt_id in prompt_ids and job.state == "queued":
                    job.state = "gone"

    def interrupt(self, prompt_id: str | None) -> None:
        with self._lock:
            self.interrupted.append(prompt_id)
            for job in self.jobs:
                if job.state == "running" and prompt_id in (None, job.prompt_id):
                    self._finish(job, "interrupted")


def _handler(fake: FakeComfyUI) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Any, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            fake.requests.append(f"GET {url.path}")
            if url.path.startswith("/history/"):
                self._json(fake.history(url.path.rsplit("/", 1)[-1]))
            elif url.path == "/queue":
                self._json(fake.queue())
            elif url.path == "/system_stats":
                self._json({"system": {"comfyui_version": fake.version}, "devices": []})
            elif url.path == "/object_info":
                self._json({node: {"name": node} for node in fake.node_types})
            elif url.path.startswith("/models/"):
                category = url.path.rsplit("/", 1)[-1]
                if category in fake.models:
                    self._json(fake.models[category])
                else:
                    self._send(404, b"", "text/plain")
            elif url.path == "/view":
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                data = fake.outputs.get(f"{query.get('subfolder', '')}/{query.get('filename')}")
                if data is None:
                    self._send(404, b"", "text/plain")
                else:
                    self._send(200, data, "image/png")
            else:
                self._send(404, b"", "text/plain")

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            fake.requests.append(f"POST {path}")
            body = self._body()
            if path == "/upload/image":
                self._upload(body)
                return
            payload: dict[str, Any] = json.loads(body or b"{}")
            if path == "/prompt":
                status, response = fake.submit(payload["prompt"], payload.get("client_id"))
                self._json(response, status)
                return
            if path == "/queue":
                fake.delete(payload.get("delete", []))
            elif path == "/interrupt":
                fake.interrupt(payload.get("prompt_id"))
            elif path == "/free":
                fake.freed.append(payload)
            else:
                self._send(404, b"", "text/plain")
                return
            self._send(200, b"", "text/plain")

        def _upload(self, body: bytes) -> None:
            head = f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode()
            message = BytesParser(policy=HTTP).parsebytes(head + body)
            fields: dict[str, str] = {}
            image: tuple[str, bytes] | None = None
            for part in message.iter_parts():
                name = str(part.get_param("name", header="content-disposition"))
                data = cast(bytes, part.get_payload(decode=True))
                if name == "image":
                    image = (str(part.get_filename()), data)
                else:
                    fields[name] = data.decode()
            if image is None:
                self._send(400, b"", "text/plain")
                return
            self._json(fake.upload(image[0], fields.get("subfolder", ""), image[1]))

    return Handler
