"""Running one ComfyUI job to a result: retries with new seeds and the out-of-memory step-down.

The rules (spec, "Failure handling"):

* a job that fails (execution error, timeout, lost, missing output) is retried up to ``retries``
  times (2 by default), each time with a new seed;
* after an out-of-memory error ComfyUI is told to free memory and the mapping's step-down ladder is
  applied **once** (its first rung that lowers something), with a new seed. That extra attempt does
  not use up a retry; running out of memory again, or having no rung left, fails the job;
* nothing else changes the request. A workflow ComfyUI rejects, an unreachable server or a job
  cancelled in ComfyUI fail at once: a new seed would not help.

Whatever ends a job early (an error, Ctrl+C, a stop now) also takes it out of ComfyUI's queue. A
stop now (``stop_now``) is not a failure: the job is cancelled, not retried, and
:class:`~vidpipe.contracts.Cancelled` is raised.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vidpipe.comfy.client import (
    SUBFOLDER,
    ComfyBadOutput,
    ComfyClient,
    ComfyError,
    ComfyJobFailed,
)
from vidpipe.comfy.workflow import WorkflowModel
from vidpipe.contracts import Cancelled, Provider
from vidpipe.runlog import attempt

RETRIES = 2


class ComfyGaveUp(ComfyError):
    """Every attempt allowed failed."""


@dataclass(frozen=True)
class Attempt:
    seed: int
    #: ``ok``, ``error``, ``out_of_memory``, ``ComfyTimeout``, ...
    outcome: str
    error: str | None = None
    gpu_seconds: float = 0.0


@dataclass(frozen=True)
class JobOutcome:
    #: ``(file name, content)`` of each output file.
    files: list[tuple[str, bytes]]
    #: The seed and values of the attempt that succeeded.
    seed: int
    values: dict[str, Any]
    attempts: list[Attempt]
    #: Retries and step-down in words; ``None`` when the first attempt succeeded.
    fallback: str | None

    @property
    def gpu_seconds(self) -> float:
        """GPU time of every attempt, failed ones included."""
        return sum(a.gpu_seconds for a in self.attempts)

    def attempt_log(self) -> list[dict[str, Any]]:
        return [asdict(a) for a in self.attempts]


def retry_seed(seed: int, attempt: int) -> int:
    """The (deterministic) seed of the ``attempt``-th extra try of a job asked for ``seed``."""
    digest = hashlib.sha256(f"retry:{seed}:{attempt}".encode()).hexdigest()
    return int(digest[:8], 16) % 2**31


def run_job(
    client: ComfyClient,
    model: WorkflowModel,
    values: Mapping[str, Any],
    *,
    seed: int,
    images: Sequence[Path] = (),
    retries: int = RETRIES,
    timeout_s: float | None = None,
    poll_s: float = 0.5,
    stop_now: Callable[[], bool] | None = None,
    provider: Provider[Any],
) -> JobOutcome:
    """Run ``model`` with ``values`` and input ``images``; return the output files.

    ``values`` are written to the mapping's fields (``seed`` and ``filename_prefix`` are set here).
    Raises :class:`ComfyError` when no attempt produced a result, and
    :class:`~vidpipe.contracts.Cancelled` (after cancelling the job) once ``stop_now()`` is true.
    """
    uploaded = [client.upload_image(path) for path in images]
    current = dict(values)
    attempt_seed = seed
    attempts: list[Attempt] = []
    notes: list[str] = []
    failures = 0
    stepped: str | None = None
    while True:
        job = {
            **current,
            "seed": attempt_seed,
            # A new name each time, so the output exists even if ComfyUI had the result cached.
            "filename_prefix": f"{SUBFOLDER}/{uuid.uuid4().hex[:16]}",
        }
        prompt_id: str | None = None
        started = time.monotonic()
        try:
            with attempt(
                provider,
                model=model.workflow_name(len(uploaded)),
                parameters={
                    **{key: value for key, value in current.items() if key != "prompt"},
                    "timeout_s": timeout_s or model.spec.timeout_s,
                },
                seed=attempt_seed,
            ) as call:
                try:
                    prompt_id = client.submit(model.build(job, uploaded))
                    finished = client.wait(
                        prompt_id,
                        timeout_s=timeout_s or model.spec.timeout_s,
                        poll_s=poll_s,
                        stop_now=stop_now,
                    )
                    call.gpu_seconds = finished.gpu_seconds
                    call.output_seconds = float(current.get("seconds", 0.0))
                    remote = finished.files(model.spec.outputs.node, model.spec.outputs.key)
                    if not remote:
                        raise ComfyBadOutput("the job finished without saving an output")
                    files = [(f.filename, client.download(f)) for f in remote]
                except ComfyError as exc:
                    if exc.gpu_seconds is not None:
                        call.gpu_seconds = exc.gpu_seconds
                    raise
        except ComfyError as exc:
            if prompt_id is not None and not isinstance(exc, ComfyJobFailed):
                client.cancel(prompt_id)
            if stop_now is not None and stop_now():
                # Cancelled from both sides at once: still a stop, not a failure.
                raise Cancelled(f"job cancelled: the run was asked to stop now ({exc})") from exc
            if not exc.retryable:
                raise
            out_of_memory = isinstance(exc, ComfyJobFailed) and exc.oom
            outcome = "out_of_memory" if out_of_memory else _outcome(exc)
            seconds = exc.gpu_seconds if exc.gpu_seconds is not None else time.monotonic() - started
            attempts.append(Attempt(attempt_seed, outcome, str(exc), seconds))
            attempt_seed = retry_seed(seed, len(attempts))
            if out_of_memory:
                if stepped is not None:
                    raise ComfyGaveUp(
                        f"out of memory again after the step-down ({stepped}): {exc}"
                    ) from exc
                step = model.step_down(current, len(uploaded))
                if step is None:
                    raise ComfyGaveUp(
                        f"out of memory, and the workflow has no step-down left to try: {exc}"
                    ) from exc
                client.free()
                current, stepped = step
                notes.append(f"out-of-memory step-down ({stepped}), new seed {attempt_seed}")
            elif failures >= retries:
                raise ComfyGaveUp(
                    f"gave up after {len(attempts)} attempt{'s' if len(attempts) > 1 else ''}: "
                    f"{exc}"
                ) from exc
            else:
                failures += 1
                notes.append(f"retry with new seed {attempt_seed} after {outcome}: {exc}")
            continue
        except BaseException:  # Ctrl+C, stop now: do not leave the job running on the GPU
            if prompt_id is not None:
                client.cancel(prompt_id)
            raise
        seconds = (
            finished.gpu_seconds if finished.gpu_seconds is not None else time.monotonic() - started
        )
        attempts.append(Attempt(attempt_seed, "ok", None, seconds))
        return JobOutcome(
            files=files,
            seed=attempt_seed,
            values=current,
            attempts=attempts,
            fallback="; ".join(notes) or None,
        )


def _outcome(exc: ComfyError) -> str:
    """``error``, ``timeout``, ``job_lost``, ``bad_output``."""
    names = {
        "ComfyJobFailed": "error",
        "ComfyTimeout": "timeout",
        "ComfyJobLost": "job_lost",
        "ComfyBadOutput": "bad_output",
    }
    return names.get(type(exc).__name__, "error")
