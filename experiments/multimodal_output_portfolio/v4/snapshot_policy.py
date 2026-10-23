"""Offline Bellman compiler and immutable, version-bound finite Policy Head.

RESEARCH_ONLY/DENY_ALL. Offline compilation uses the exact v4 oracle; online
lookups do not invoke the solver. No learned weights, neural outputs, signed
attestation, actual external verification or natural-data generalization.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
import json
import random

from portfolio import (Allocation, Config, Controller, SHOCK_PROBS, STOP,
                       State, advance, decode_all, decoded_external_loss,
                       feasible)


def _canonical_bytes(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def current_source_digest() -> str:
    return sha256(Path(__file__).with_name("portfolio.py").read_bytes()).hexdigest()


@dataclass(frozen=True)
class PolicyEntry:
    state: State
    action: Allocation
    value: float


@dataclass(frozen=True)
class PolicySnapshot:
    profile: Config
    initial: State
    source_sha256: str
    policy_sha256: str
    entries: tuple[PolicyEntry, ...]
    offline_work: tuple[tuple[str, int], ...]
    _choices: MappingProxyType = field(repr=False, compare=False)

    def choose(self, state: State, profile: Config, source_sha256: str,
               scope: str) -> tuple[Allocation, float]:
        if (scope != "FINITE_SYNTHETIC_DENY_ALL" or profile != self.profile
            or source_sha256 != self.source_sha256):
            raise ValueError("policy snapshot version or scope mismatch")
        try:
            return self._choices[state]
        except KeyError as exc:
            raise ValueError("uncovered portfolio state; abstain or recompile") from exc


def compile_optimal_snapshot(initial: State, cfg: Config,
                             source_sha256: str) -> PolicySnapshot:
    """Compile all and only states reachable while following this frozen policy."""
    if (type(cfg) is not Config or type(initial) is not State or initial.step != 0
        or initial.remaining < cfg.emission_reserve
        or type(source_sha256) is not str
        or source_sha256 != current_source_digest()):
        raise ValueError("unadmitted snapshot source or initial state")
    oracle = Controller(cfg)
    todo = [initial]
    choices: dict[State, tuple[Allocation, float]] = {}
    while todo:
        state = todo.pop()
        if state in choices:
            continue
        action, value = oracle.solve(state)
        if not feasible(state, action, cfg):
            raise AssertionError("oracle emitted illegal portfolio action")
        choices[state] = (action, value)
        if not action.stop:
            for shock in range(len(SHOCK_PROBS)):
                todo.append(advance(state, action, shock, cfg))
    entries = tuple(PolicyEntry(state, *choices[state])
                    for state in sorted(choices,
                                        key=lambda s: (s.step, s.levels,
                                                       s.remaining, s.active_mask)))
    payload = {
        "schema": "hepta.ndu-v4.compiled-policy.v1",
        "scope": "FINITE_SYNTHETIC_DENY_ALL",
        "cfg": asdict(cfg),
        "initial": asdict(initial),
        "source_sha256": source_sha256,
        "entries": [
            {"state": asdict(e.state), "allocation": e.action.units,
             "value_hex": e.value.hex()}
            for e in entries
        ],
    }
    digest = sha256(_canonical_bytes(payload)).hexdigest()
    return PolicySnapshot(cfg, initial, source_sha256, digest, entries,
                          tuple(sorted(oracle.work_receipt().items())),
                          MappingProxyType(dict(choices)))


def rollout_snapshot(snapshot: PolicySnapshot, cfg: Config,
                     source_sha256: str, seed: int) -> dict:
    """Run time: each choice is a dictionary lookup, never Bellman search."""
    if type(seed) is not int:
        raise ValueError("invalid committed random seed")
    state = snapshot.initial
    rng = random.Random(seed)
    trace = []
    while True:
        action, _value = snapshot.choose(state, cfg, source_sha256,
                                         "FINITE_SYNTHETIC_DENY_ALL")
        if not feasible(state, action, cfg):
            raise AssertionError("unfunded generated output")
        row = {"step": state.step, "before_levels": state.levels,
               "before_budget": state.remaining, "allocation": action.units}
        if action.stop:
            trace.append(row)
            break
        # Random innovation only becomes observable after the action.
        draw = rng.random()
        shock = (0 if draw < SHOCK_PROBS[0]
                 else 1 if draw < SHOCK_PROBS[0] + SHOCK_PROBS[1] else 2)
        state = advance(state, action, shock, cfg)
        row.update({"observed_shock": shock, "after_levels": state.levels,
                    "after_budget": state.remaining})
        trace.append(row)
    output = decode_all(state)
    paid = snapshot.initial.remaining - state.remaining + cfg.emission_reserve
    if paid > snapshot.initial.remaining or state.remaining < cfg.emission_reserve:
        raise AssertionError("invalid four-output physical reserve")
    return {"policy_sha256": snapshot.policy_sha256,
            "actions": tuple(r["allocation"] for r in trace),
            "outputs": dict(output._asdict()),
            "external_fixture_loss": decoded_external_loss(output, cfg.sync_penalty),
            "paid_units": paid,
            "remaining_after_emission": snapshot.initial.remaining - paid}
