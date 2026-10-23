"""Prospective compressed-state closure audit; never a Markov sufficiency proof.

Signed synthetic fixtures only check protocol algebra. Real causal support,
temporal independence and observer trust must be qualified outside this module.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import fsum, isfinite, log, sqrt

from causal_credit import CreditRejected, _digest, _number, _seal


@dataclass(frozen=True)
class ClosureProtocol:
    trial_id: str
    registrar_id: str
    actor_id: str
    objective_digest: str
    snapshot_digest: str
    critic_digest: str
    generation: int
    registered_at: int
    train_cutoff: int
    future_start: int
    expected_future: tuple[tuple[str, str], ...]  # (trace_id, independent cluster)
    maximum_history_mse_gain: float
    alpha: float
    registrar_signature: str

    def digest(self) -> str:
        return _seal(self, b"hepta.ndu-dmgp.closure-protocol.v1",
                     {"registrar_signature"})

    def check(self) -> None:
        if (not self.trial_id or not self.registrar_id or not self.actor_id
                or self.actor_id == self.registrar_id
                or type(self.generation) is not int or self.generation < 1
                or any(type(x) is not int for x in (
                    self.registered_at, self.train_cutoff, self.future_start))
                or not 0 < self.registered_at < self.train_cutoff < self.future_start
                or not all(_digest(x) for x in (
                    self.objective_digest, self.snapshot_digest, self.critic_digest))):
            raise CreditRejected("invalid prospective closure plan")
        if (not 64 <= len(self.expected_future) <= 4096
                or len({p[0] for p in self.expected_future}) != len(self.expected_future)
                or len({p[1] for p in self.expected_future}) != len(self.expected_future)
                or any(len(p) != 2 or not p[0] or not p[1]
                       for p in self.expected_future)):
            raise CreditRejected("missing independent future closure roster")
        if (not _number(self.maximum_history_mse_gain)
                or not 0 <= self.maximum_history_mse_gain <= 1
                or not _number(self.alpha) or not 0 < self.alpha < 1):
            raise CreditRejected("invalid preregistered closure statistical profile")


@dataclass(frozen=True)
class ClosureTrace:
    trial_id: str
    trace_id: str
    cluster_id: str
    split: str
    objective_digest: str
    snapshot_digest: str
    critic_digest: str
    generation: int
    # Hashes or canonical bounded labels; do not carry raw private prompts.
    compressed_state: str
    available_history: str
    feature_time: int
    outcome_time: int
    outcome: float
    actor_id: str
    observer_id: str
    observation_kind: str
    observer_signature: str

    def digest(self) -> str:
        return _seal(self, b"hepta.ndu-dmgp.closure-outcome.v1",
                     {"observer_signature"})


@dataclass(frozen=True)
class ClosureVerdict:
    future_episodes: int
    compressed_mse: float
    history_mse: float
    observed_mse_gain: float
    simultaneous_upper_gain_bound: float
    compressed_state_supported_in_region: bool
    exact_markov_sufficiency_proven: bool = False
    production_blockers_closed: bool = False
    production_authority: bool = False


def audit_prospective_closure(
    protocol: ClosureProtocol, train: Sequence[ClosureTrace],
    future: Sequence[ClosureTrace], verifier: Callable[[str, str, str], bool] | None,
) -> ClosureVerdict:
    protocol.check()
    if verifier is None or not protocol.registrar_signature:
        raise CreditRejected("independent closure verifier unavailable")
    if not verifier(protocol.registrar_id, protocol.digest(),
                    protocol.registrar_signature):
        raise CreditRejected("closure protocol registration signature rejected")
    expected = dict(protocol.expected_future)
    if len(train) < 8 or len(future) != len(expected):
        raise CreditRejected("incomplete train or preregistered future closure panel")

    trace_ids = set()
    clusters = set()
    state_train: dict[str, list[float]] = defaultdict(list)
    historical_train: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in (*train, *future):
        if (not row.trace_id or not row.cluster_id or not row.compressed_state
                or not row.available_history
                or row.trace_id in trace_ids or row.cluster_id in clusters
                or row.trial_id != protocol.trial_id
                or row.objective_digest != protocol.objective_digest
                or row.snapshot_digest != protocol.snapshot_digest
                or row.critic_digest != protocol.critic_digest
                or type(row.generation) is not int or row.generation != protocol.generation
                or row.actor_id != protocol.actor_id
                or row.observer_id in (protocol.registrar_id, protocol.actor_id)
                or not row.observer_id
                or row.observation_kind != "independent_observation"
                or type(row.feature_time) is not int
                or type(row.outcome_time) is not int
                or row.feature_time <= 0 or row.outcome_time <= row.feature_time
                or not _number(row.outcome) or not 0 <= row.outcome <= 1):
            raise CreditRejected("leaked, duplicate or unauthenticated closure evidence")
        trace_ids.add(row.trace_id)
        clusters.add(row.cluster_id)
        if not row.observer_signature or not verifier(
                row.observer_id, row.digest(), row.observer_signature):
            raise CreditRejected("invalid independent closure observation signature")
    for row in train:
        if (row.split != "train"
                or not (row.feature_time < row.outcome_time < protocol.train_cutoff)):
            raise CreditRejected("train data exceeds frozen feature/outcome cutoff")
        state_train[row.compressed_state].append(row.outcome)
        historical_train[(row.compressed_state, row.available_history)].append(
            row.outcome
        )
    if any(len(vals) < 4 for vals in historical_train.values()):
        raise CreditRejected("under-supported conditional history cells")
    compressed_losses = []
    expanded_losses = []
    for row in future:
        if (row.split != "future"
                or row.feature_time < protocol.future_start
                or row.outcome_time <= row.feature_time
                or expected.get(row.trace_id) != row.cluster_id):
            raise CreditRejected("out-of-window or cherry-picked future trace")
        s, h = row.compressed_state, row.available_history
        if s not in state_train or (s, h) not in historical_train:
            raise CreditRejected("heldout state/history outside training support")
        predicted_compressed = fsum(state_train[s]) / len(state_train[s])
        predicted_full = fsum(historical_train[(s, h)]) / len(
            historical_train[(s, h)]
        )
        compressed_losses.append((row.outcome - predicted_compressed) ** 2)
        expanded_losses.append((row.outcome - predicted_full) ** 2)
    n = len(future)
    m0 = fsum(compressed_losses)/n
    m1 = fsum(expanded_losses)/n
    gain = m0-m1
    # Bounded [0,1] squared errors: paired gain lies in [-1,+1].
    # One-sided independent-episode Hoeffding upper confidence bound.
    ucb = gain + sqrt(2 * log(1 / protocol.alpha) / n)
    return ClosureVerdict(n, m0, m1, gain, ucb,
                          ucb <= protocol.maximum_history_mse_gain)
