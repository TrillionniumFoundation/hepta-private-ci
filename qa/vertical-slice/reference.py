"""Reference state machine for the P0.8B/P0.8D runtime vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
    CREATED = "created"
    PROCESS_STARTED = "process_started"
    IDENTITY_PROVED = "identity_proved"
    APP_SERVER_READY = "app_server_ready"
    REQUEST_AUTHORIZED = "request_authorized"
    DISPATCHED = "dispatched"
    INDETERMINATE = "indeterminate"
    OBSERVED = "observed"
    DRAINING = "draining"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class RuntimeSlice:
    expected_generation: int
    phase: Phase = Phase.CREATED
    outcome: str | None = None

    def start(self, generation: int) -> None:
        self._require(Phase.CREATED)
        self._generation(generation)
        self.phase = Phase.PROCESS_STARTED

    def prove_identity(self, generation: int, exact_identity: bool, fenced: bool) -> None:
        self._require(Phase.PROCESS_STARTED)
        self._generation(generation)
        if not exact_identity or fenced:
            self.phase = Phase.FAILED
            return
        self.phase = Phase.IDENTITY_PROVED

    def mark_app_server_ready(self, generation: int, home_matches: bool) -> None:
        self._require(Phase.IDENTITY_PROVED)
        self._generation(generation)
        if not home_matches:
            self.phase = Phase.FAILED
            return
        self.phase = Phase.APP_SERVER_READY

    def authorize(self, generation: int, witness_valid: bool) -> None:
        self._require(Phase.APP_SERVER_READY)
        self._generation(generation)
        if not witness_valid:
            self.phase = Phase.FAILED
            return
        self.phase = Phase.REQUEST_AUTHORIZED

    def dispatch(self, generation: int) -> None:
        self._require(Phase.REQUEST_AUTHORIZED)
        self._generation(generation)
        self.phase = Phase.DISPATCHED

    def lose_ack(self, generation: int) -> None:
        self._require(Phase.DISPATCHED)
        self._generation(generation)
        self.phase = Phase.INDETERMINATE

    def observe(self, generation: int, outcome: str) -> None:
        if self.phase not in {Phase.DISPATCHED, Phase.INDETERMINATE}:
            raise ValueError("terminal outcome requires a dispatched operation")
        self._generation(generation)
        if outcome not in {"applied", "not_applied", "quarantined"}:
            raise ValueError("unknown terminal outcome")
        self.outcome = outcome
        self.phase = Phase.OBSERVED

    def drain(self, generation: int) -> None:
        if self.phase not in {Phase.APP_SERVER_READY, Phase.OBSERVED, Phase.FAILED}:
            raise ValueError("runtime is not drainable")
        self._generation(generation)
        self.phase = Phase.DRAINING

    def stop(self, generation: int, outstanding_operations: int) -> None:
        self._require(Phase.DRAINING)
        self._generation(generation)
        if outstanding_operations:
            raise ValueError("outstanding operations must be reconciled")
        self.phase = Phase.STOPPED

    def _generation(self, generation: int) -> None:
        if generation != self.expected_generation:
            self.phase = Phase.FAILED
            raise ValueError("generation fence mismatch")

    def _require(self, expected: Phase) -> None:
        if self.phase is not expected:
            raise ValueError(f"expected {expected.value}, got {self.phase.value}")
