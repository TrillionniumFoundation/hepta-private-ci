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
                       State, actions, advance, decode_all, decoded_external_loss,
                       feasible)


# Offline algorithmic work is counted before each recursive expansion. These
# are logical state/action calls, NOT CPU, GPU, FLOPs or physical energy.
MAX_OFFLINE_STATES = 32768
MAX_OFFLINE_TRANSITIONS = 1000000


class BudgetedOracle(Controller):
    """Preserve v4 Bellman semantics without unbounded recursive expansion.

    The parent's undecorated solve recursively dispatches through self.solve,
    so this adapter enforces a true per-compilation cap at every expansion.
    It intentionally bypasses the parent's global, cross-instance lru_cache.
    """

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self._memo: dict[State, tuple[Allocation, float]] = {}
        self._hits = 0
        self._expansions = 0
        self._transitions = 0

    def solve(self, state: State) -> tuple[Allocation, float]:
        if state in self._memo:
            self._hits += 1
            return self._memo[state]
        if self._expansions >= MAX_OFFLINE_STATES:
            raise ValueError("offline NDU state expansion cap exceeded")
        if state.step > self.cfg.horizon:
            raise ValueError("offline NDU invalid horizon")
        transitions = 3 * (len(actions(state, self.cfg)) - 1)
        if self._transitions + transitions > MAX_OFFLINE_TRANSITIONS:
            raise ValueError("offline NDU action branch cap exceeded")
        self._expansions += 1
        self._transitions += transitions
        result = Controller.solve.__wrapped__(self, state)
        self._memo[state] = result
        return result

    def work_receipt(self) -> dict[str, int]:
        return {"expanded_states": self._expansions,
                "cache_hits": self._hits,
                "evaluated_branches": self._transitions,
                "cached_states": len(self._memo),
                "maximum_states": MAX_OFFLINE_STATES,
                "maximum_branches": MAX_OFFLINE_TRANSITIONS}


def _canonical_bytes(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def current_source_digest() -> str:
    return sha256(Path(__file__).with_name('portfolio.py').read_bytes()).hexdigest()


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
    """All and only states reachable while following this frozen policy."""
    if (type(initial) is not State or initial.step != 0
        or initial.remaining < cfg.emission_reserve
        or initial.active_mask != 0
        or type(source_sha256) is not str
        or source_sha256 != current_source_digest()):
        raise ValueError("unadmitted snapshot source or initial state")
    oracle = BudgetedOracle(cfg)
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


MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _snapshot_payload(snapshot: PolicySnapshot) -> dict:
    return {"schema": "hepta.ndu-v4.compiled-policy.v1",
            "scope": "FINITE_SYNTHETIC_DENY_ALL",
            "cfg": asdict(snapshot.profile),
            "initial": asdict(snapshot.initial),
            "source_sha256": snapshot.source_sha256,
            "entries": [{"state": asdict(entry.state),
                         "allocation": entry.action.units,
                         "value_hex": entry.value.hex()}
                        for entry in snapshot.entries]}


def export_snapshot_bytes(snapshot: PolicySnapshot) -> bytes:
    """Canonical, self-checking artifact bytes; a digest is NOT a signature."""
    import math
    if any(not math.isfinite(entry.value) for entry in snapshot.entries):
        raise ValueError("nonfinite compiled continuation utility")
    payload = _snapshot_payload(snapshot)
    digest = sha256(_canonical_bytes(payload)).hexdigest()
    if digest != snapshot.policy_sha256:
        raise ValueError("snapshot was mutated after compilation")
    result = _canonical_bytes({"policy_sha256": digest, "payload": payload})
    if len(result) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot byte admission limit exceeded")
    return result


def load_snapshot_bytes(raw: bytes, cfg: Config, initial: State) -> PolicySnapshot:
    """Fail closed on corruption, scope/version mismatch or incomplete paths.

    Validity is integrity + feasibility only. A digest does not authenticate a
    real observer, authorize an execution, or certify global policy optimality.
    """
    import math
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SNAPSHOT_BYTES:
        raise ValueError("missing or oversized compiled policy artifact")
    try:
        envelope = json.loads(raw.decode("utf-8"))
        if (type(envelope) is not dict
            or set(envelope) != {"policy_sha256", "payload"}
            or _canonical_bytes(envelope) != raw):
            raise ValueError("noncanonical policy artifact")
        digest = envelope["policy_sha256"]
        payload = envelope["payload"]
        if (type(digest) is not str or len(digest) != 64
            or not isinstance(payload, dict)
            or set(payload) != {"schema", "scope", "cfg", "initial",
                                "source_sha256", "entries"}
            or sha256(_canonical_bytes(payload)).hexdigest() != digest):
            raise ValueError("compiled policy digest mismatch")
        if (payload["schema"] != "hepta.ndu-v4.compiled-policy.v1"
            or payload["scope"] != "FINITE_SYNTHETIC_DENY_ALL"
            or _canonical_bytes(payload["cfg"]) != _canonical_bytes(asdict(cfg))
            or _canonical_bytes(payload["initial"]) != _canonical_bytes(asdict(initial))
            or payload["source_sha256"] != current_source_digest()):
            raise ValueError("compiled policy source, scope or profile mismatch")
        rows = payload["entries"]
        if type(rows) is not list or not 0 < len(rows) <= MAX_OFFLINE_STATES:
            raise ValueError("compiled policy state admission limit exceeded")
        parsed = []
        seen = set()
        for row in rows:
            if type(row) is not dict or set(row) != {"state", "allocation", "value_hex"}:
                raise ValueError("invalid compiled policy entry")
            fields = row["state"]
            if type(fields) is not dict or set(fields) != {"levels", "remaining", "step", "active_mask"}:
                raise ValueError("invalid compiled state record")
            state = State(tuple(fields["levels"]), fields["remaining"],
                          fields["step"], fields["active_mask"])
            alloc = Allocation(tuple(row["allocation"]))
            if type(row["value_hex"]) is not str:
                raise ValueError("invalid numeric policy value")
            value = float.fromhex(row["value_hex"])
            if (not math.isfinite(value) or state in seen
                or state.step > cfg.horizon or not feasible(state, alloc, cfg)):
                raise ValueError("duplicate, nonfinite or infeasible policy state")
            seen.add(state)
            parsed.append(PolicyEntry(state, alloc, value))
        order = lambda state: (state.step, state.levels,
                               state.remaining, state.active_mask)
        if tuple(e.state for e in parsed) != tuple(sorted(seen, key=order)):
            raise ValueError("noncanonical policy state order")
        decisions = {e.state: (e.action, e.value) for e in parsed}
        if initial not in decisions:
            raise ValueError("compiled policy missing initial state")
        reachable = {initial}
        pending = [initial]
        while pending:
            state = pending.pop()
            action, _ = decisions[state]
            if action.stop:
                continue
            for innovation in range(len(SHOCK_PROBS)):
                next_state = advance(state, action, innovation, cfg)
                if next_state not in decisions:
                    raise ValueError("compiled policy missing reachable outcome")
                if next_state not in reachable:
                    reachable.add(next_state)
                    pending.append(next_state)
        if reachable != set(decisions):
            raise ValueError("compiled policy contains extraneous states")
        return PolicySnapshot(cfg, initial, payload["source_sha256"], digest,
                              tuple(parsed), tuple(), MappingProxyType(decisions))
    except (TypeError, KeyError, OverflowError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid compiled policy bytes") from exc


def rollout_snapshot(snapshot: PolicySnapshot, cfg: Config,
                     source_sha256: str, seed: int) -> dict:
    """Run time: each choice is constant-time dictionary lookup, not Bellman."""
    # Match the generator's bounded, deterministic seed contract. A negative
    # or oversized seed is not a valid source-bound draw identity even if
    # random.Random can technically accept it.
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError("invalid committed random seed")
    # One per-invocation identity check; no disk hashing in each online lookup.
    if source_sha256 != current_source_digest():
        raise ValueError("runtime source does not match compiled portfolio")
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
