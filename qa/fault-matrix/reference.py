"""Dependency-free executable model of Hepta operation crash windows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class State(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    DISPATCHED = "dispatched"
    INDETERMINATE = "indeterminate"
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    QUARANTINED = "quarantined"


TERMINAL = {State.APPLIED, State.NOT_APPLIED, State.QUARANTINED}


@dataclass(frozen=True)
class Record:
    operation_id: str
    payload_digest: str
    generation: int
    revision: int = 1
    state: State = State.PENDING


def transition(record: Record, target: State, *, generation: int) -> Record:
    if record.state in TERMINAL:
        raise ValueError("terminal")
    if generation != record.generation:
        raise ValueError("stale-generation")
    allowed = {
        State.PENDING: {State.AUTHORIZED},
        State.AUTHORIZED: {State.DISPATCHED},
        State.DISPATCHED: {State.INDETERMINATE, State.APPLIED, State.NOT_APPLIED, State.QUARANTINED},
        State.INDETERMINATE: {State.APPLIED, State.NOT_APPLIED, State.QUARANTINED},
    }
    if target not in allowed.get(record.state, set()):
        raise ValueError("invalid-transition")
    return replace(record, revision=record.revision + 1, state=target)


def replay(existing: Record, operation_id: str, payload_digest: str, generation: int) -> Record:
    if (existing.operation_id, existing.payload_digest, existing.generation) != (
        operation_id,
        payload_digest,
        generation,
    ):
        raise ValueError("binding-conflict")
    return existing
