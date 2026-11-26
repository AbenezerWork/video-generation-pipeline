"""Approval gates: pauses after a stage until a person has looked at what it produced.

A gate is named after the stage it follows (``script``, ``storyboard``, ``keyframes`` by default;
``gates:`` in ``vidpipe.yaml`` changes the set, ``gates: []`` disables them). When the run reaches
a gate that is not approved it stops there with ``RunResult.paused_at`` set, and ``vidpipe run``
exits with :data:`EXIT_PAUSED`. Approval is how it resumes:

* ``vidpipe approve <project> <gate>`` (what scripts and tests use; no input needed),
* ``vidpipe run --approve <gate>`` (approve in advance, repeatable),
* an interactive y/N question, asked only when stdin and stdout are a terminal,
* or ``--auto``, which ignores every gate (and records nothing).

An approval is stored in ``build/approvals.json`` as a digest of the *current content* of the
gated stage's output files, so it holds exactly as long as those files do: regenerating the stage
with different results, a hand edit, or ``vidpipe redo`` asks again.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from vidpipe.artifacts import ArtifactStore, digest
from vidpipe.project import Project
from vidpipe.runstate import RunState, RunStatus, read_run_state

#: ``vidpipe run`` exit code when the run stopped at a gate (0 = finished, 1 = error).
EXIT_PAUSED = 3
APPROVALS_FILENAME = "approvals.json"
STALE_GATE_MESSAGE = "The run is no longer paused at this gate. Review the current run."

#: Asked at a gate that is not approved: ``(gate, output paths relative to the project) -> yes?``
Approver = Callable[[str, Sequence[str]], bool]


class Approvals(BaseModel):
    #: Gate name -> digest of the gated stage's outputs when it was approved.
    gates: dict[str, str] = Field(default_factory=dict[str, str])


class GateError(Exception):
    pass


def require_paused_gate(project_dir: Path, run_id: str, stage: str) -> RunState:
    """Check the decision's target while holding the project's writer lock."""
    state = read_run_state(project_dir)
    if (
        state is None
        or state.run_id != run_id
        or state.status != RunStatus.PAUSED
        or state.paused_at != stage
    ):
        raise GateError(STALE_GATE_MESSAGE)
    return state


class GateKeeper:
    def __init__(self, project: Project, store: ArtifactStore) -> None:
        self.project = project
        self.store = store
        self.path = project.build / APPROVALS_FILENAME

    def outputs(self, gate: str) -> list[Path]:
        """Absolute paths of the files the gated stage produced, sorted."""
        found = {
            o.path
            for record in self.store.ledger.artifacts.values()
            if record.stage == gate
            for o in record.outputs
        }
        return sorted(self.project.root / p for p in found)

    def current(self, gate: str) -> str | None:
        """Digest of the gated stage's outputs as they are on disk now (None: nothing there)."""
        files = [p for p in self.outputs(gate) if p.is_file()]
        if not files:
            return None
        return digest(
            {p.relative_to(self.project.root).as_posix(): self.store.hash_path(p) for p in files}
        )

    def _load(self) -> Approvals:
        try:
            return Approvals.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Approvals()

    def is_approved(self, gate: str) -> bool:
        now = self.current(gate)
        return now is not None and self._load().gates.get(gate) == now

    def approve(self, gate: str) -> None:
        now = self.current(gate)
        if now is None:
            raise GateError(f"nothing to approve: stage {gate!r} has not produced anything yet")
        approvals = self._load()
        approvals.gates[gate] = now
        self._save(approvals)

    def reject(self, gate: str) -> None:
        approvals = self._load()
        if approvals.gates.pop(gate, None) is not None:
            self._save(approvals)

    def _save(self, approvals: Approvals) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(approvals.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def passes(self, gate: str, approver: Approver | None) -> bool:
        """True when the run may continue past ``gate``; asks ``approver`` if it is not approved."""
        if self.is_approved(gate):
            return True
        if approver is None:
            return False
        shown = [p.relative_to(self.project.root).as_posix() for p in self.outputs(gate)]
        if not approver(gate, shown):
            return False
        self.approve(gate)
        return True
