"""Offline independent optimality audit for finite v4 policy snapshots.

This research-only reference separately enumerates the legal four-modality
action lattice, advances each observable synthetic outcome, and evaluates
terminal toy outputs under the frozen external objective. It does not use
Controller.solve, BudgetedOracle, snapshot values or snapshot actions when
computing the optimum. Hashes are integrity checks, not authentication.
Never invoke this recursive oracle on the latency-critical inference path.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import math

from portfolio import Allocation, Config, SHOCK_PROBS, STOP, State
from snapshot_policy import (
    current_source_digest, load_snapshot_bytes,
)

MAX_AUDIT_STATES = 32_768
MAX_AUDIT_BRANCHES = 1_000_000
VALUE_TOL = 1e-8


class IndependentFiniteOracle:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.memo: dict[State, tuple[Allocation, float]] = {}
        self.expansions = 0
        self.branches = 0

    def _terminal(self, state: State) -> float:
        # Independently score the public symbolic terminal representation.
        t, a, i, v = state.levels
        loss = sum((2 - q) ** 2 for q in (t, a, i, v))
        loss += self.cfg.sync_penalty * int(i != v)
        loss += self.cfg.sync_penalty * int(abs(t - a) > 1)
        return -float(loss) - self.cfg.cost_shadow_price * self.cfg.emission_reserve

    def _certainty_equivalent(self, branch_values: tuple[float, ...]) -> float:
        gamma = self.cfg.risk_aversion
        if gamma == 0:
            return math.fsum(p * val for p, val in zip(SHOCK_PROBS, branch_values))
        # Independently implemented shifted logsumexp over registered support.
        exponents = [-gamma * val for val in branch_values]
        anchor = max(exponents)
        total = math.fsum(
            p * math.exp(exponent - anchor)
            for p, exponent in zip(SHOCK_PROBS, exponents)
        )
        if total <= 0 or not math.isfinite(total):
            raise ValueError("independent risk reference has invalid support")
        return -(anchor + math.log(total)) / gamma

    def best(self, state: State) -> tuple[Allocation, float]:
        cached = self.memo.get(state)
        if cached is not None:
            return cached
        if (state.step > self.cfg.horizon
            or state.remaining < self.cfg.emission_reserve):
            raise ValueError("unadmitted independent audit state")
        if self.expansions >= MAX_AUDIT_STATES:
            raise ValueError("independent audit state cap reached")
        self.expansions += 1
        best_action, best_value = STOP, self._terminal(state)
        if state.step < self.cfg.horizon:
            # This enumerator deliberately does not call the production
            # action enumeration, transition or utility implementation.
            for weights in product(range(3), repeat=4):
                units = sum(weights)
                if not 0 < units <= self.cfg.max_units_per_step:
                    continue
                mask = sum(1 << idx for idx, unit in enumerate(weights) if unit)
                activation_count = (mask & ~state.active_mask).bit_count()
                charge = (units * self.cfg.unit_cost
                          + activation_count * self.cfg.activation_cost)
                if charge + self.cfg.emission_reserve > state.remaining:
                    continue
                if self.branches + len(SHOCK_PROBS) > MAX_AUDIT_BRANCHES:
                    raise ValueError("independent audit branch cap reached")
                self.branches += len(SHOCK_PROBS)
                successor_values = []
                for shock in range(len(SHOCK_PROBS)):
                    next_levels = tuple(
                        min(2, old + min(unit, shock))
                        for old, unit in zip(state.levels, weights)
                    )
                    child = State(next_levels, state.remaining - charge,
                                  state.step + 1, mask)
                    successor_values.append(self.best(child)[1])
                value = (-self.cfg.cost_shadow_price * charge
                         + self._certainty_equivalent(tuple(successor_values)))
                if value > best_value + 1e-12:
                    best_action, best_value = Allocation(weights), value
        if not math.isfinite(best_value):
            raise ValueError("nonfinite independent audit value")
        answer = (best_action, best_value)
        self.memo[state] = answer
        return answer


@dataclass(frozen=True)
class OfflineOptimalityReceipt:
    scope: str
    source_sha256: str
    policy_sha256: str
    checked_policy_states: int
    independent_expansions: int
    independent_branch_evaluations: int
    maximum_absolute_value_error: float
    canonical_tie_rule_matched: bool
    verified_finite_oracle_only: bool


def audit_snapshot_optimality(raw: bytes, cfg: Config, initial: State,
                              source_sha256: str) -> OfflineOptimalityReceipt:
    """Independently reject a structurally valid but suboptimal policy table.

    This is an *offline* numerical certificate for one finite toy profile.
    The bundle and its score remain unauthenticated; an independent authorizer
    must still verify source custody, outcome observers and external effects.
    """
    if source_sha256 != current_source_digest():
        raise ValueError("independent audit source mismatch")
    # The existing loader enforces canonical bytes, integrity, state coverage
    # and objective/profile feasibility before optimality is considered.
    snapshot = load_snapshot_bytes(raw, cfg, initial)
    if snapshot.source_sha256 != source_sha256:
        raise ValueError("independent audit source identity mismatch")
    reference = IndependentFiniteOracle(cfg)
    maximum_error = 0.0
    for entry in snapshot.entries:
        expected_action, expected_value = reference.best(entry.state)
        value_error = abs(entry.value - expected_value)
        maximum_error = max(maximum_error, value_error)
        if value_error > VALUE_TOL:
            raise ValueError("compiled policy has forged or nonoptimal value")
        if entry.action != expected_action:
            raise ValueError("compiled policy has nonoptimal action or tie rule")
    return OfflineOptimalityReceipt(
        scope="FINITE_SYNTHETIC_OFFLINE_AUDIT_DENY_ALL",
        source_sha256=source_sha256,
        policy_sha256=snapshot.policy_sha256,
        checked_policy_states=len(snapshot.entries),
        independent_expansions=reference.expansions,
        independent_branch_evaluations=reference.branches,
        maximum_absolute_value_error=maximum_error,
        canonical_tie_rule_matched=True,
        verified_finite_oracle_only=True,
    )
