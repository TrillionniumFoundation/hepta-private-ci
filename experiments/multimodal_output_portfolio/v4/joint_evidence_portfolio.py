"""Finite joint QUERY/REFINE/STOP NDU control for toy four-modal generation.

Research-only, DENY_ALL. The controller observes a Bayesian belief, bounded
synthetic generation levels and the remaining integer budget. It NEVER reads
the hidden truth, future witness, or future common shock. Exact Bellman values
are checked independently against emitted terminal outputs in the audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math
from typing import Callable

from portfolio import (
    Allocation, Config, Decoded, SHOCK_PROBS, State, STOP,
    actions, advance, charge, conditional_ce, decode_all,
    decoded_external_loss, feasible,
)
from information_acquisition import (
    WITNESS_ACCURACY, map_label, posterior, prior_from_public,
    witness_probability,
)
from counterfactual_audit import empirical_cvar90


@dataclass(frozen=True)
class JointState:
    generation: State
    belief_zero: Fraction
    queried: bool = False

    def __post_init__(self):
        if (type(self.generation) is not State
            or type(self.belief_zero) is not Fraction
            or not Fraction(0) <= self.belief_zero <= Fraction(1)
            or type(self.queried) is not bool):
            raise ValueError("unadmitted observable joint state")


@dataclass(frozen=True)
class JointAction:
    kind: str
    allocation: Allocation | None = None

    def __post_init__(self):
        if self.kind not in ("EMIT", "QUERY", "REFINE"):
            raise ValueError("unknown portfolio action")
        if ((self.kind == "REFINE")
            != (type(self.allocation) is Allocation
                and not self.allocation.stop)):
            raise ValueError("invalid allocation for action")


EMIT = JointAction("EMIT")
QUERY = JointAction("QUERY")


def emission(state: JointState) -> dict:
    """Actually construct four separate toy media, bound to one output label."""
    label = map_label(state.belief_zero)
    data = decode_all(state.generation)
    return {
        "text": (label, data.text),
        "audio": (label, data.audio),
        "image": (label, data.image),
        "video": (label, data.video),
    }


def raw_output_loss(raw: dict, truth: int, cfg: Config,
                    factual_penalty: int) -> int:
    """External fixture scorer sees true fact only AFTER terminal emission."""
    if (type(raw) is not dict
        or set(raw) != {"text", "audio", "image", "video"}
        or type(truth) is not int or truth not in (0, 1)
        or type(factual_penalty) is not int or factual_penalty <= 0):
        raise ValueError("incomplete independent terminal observation")
    parts = [raw[key] for key in ("text", "audio", "image", "video")]
    if (any(type(part) is not tuple or len(part) != 2 for part in parts)
        or any(type(part[0]) is not int or part[0] not in (0, 1)
               for part in parts)
        or len({part[0] for part in parts}) != 1):
        raise ValueError("cross-modal output label conflict")
    observed = Decoded(*(part[1] for part in parts))
    return (decoded_external_loss(observed, cfg.sync_penalty)
            + factual_penalty * int(parts[0][0] != truth))


def query_next(state: JointState, witness: int, query_units: int,
               cfg: Config) -> JointState:
    if (type(query_units) is not int or query_units <= 0
        or state.queried or state.generation.remaining <
        cfg.emission_reserve + query_units):
        raise ValueError("unfunded or repeated witness query")
    s = state.generation
    next_generation = State(s.levels, s.remaining - query_units,
                            s.step, s.active_mask)
    return JointState(next_generation,
                      posterior(state.belief_zero, witness), True)


class JointController:
    """Exact-support, bounded Bellman controller for three competing actions."""

    def __init__(self, cfg: Config, *, query_units: int = 1,
                 factual_penalty: int = 12, allow_query: bool = True,
                 allow_refine: bool = True):
        if (type(query_units) is not int or query_units <= 0
            or type(factual_penalty) is not int or factual_penalty <= 0
            or type(allow_query) is not bool
            or type(allow_refine) is not bool):
            raise ValueError("unadmitted joint optimizer profile")
        self.cfg = cfg
        self.query_units = query_units
        self.factual_penalty = factual_penalty
        self.allow_query = allow_query
        self.allow_refine = allow_refine

    def _emit_value(self, state: JointState) -> float:
        raw = emission(state)
        correct = map_label(state.belief_zero)
        good = raw_output_loss(raw, correct, self.cfg, self.factual_penalty)
        bad = good + self.factual_penalty
        p = state.belief_zero if correct == 0 else 1 - state.belief_zero
        return (conditional_ce((-float(good), -float(bad)),
                               (float(p), float(1-p)),
                               self.cfg.risk_aversion)
                - self.cfg.cost_shadow_price * self.cfg.emission_reserve)

    @lru_cache(maxsize=65536)
    def solve(self, state: JointState) -> tuple[JointAction, float]:
        cfg = self.cfg
        if (state.generation.remaining < cfg.emission_reserve
            or state.generation.step > cfg.horizon):
            raise ValueError("unfunded or overhorizon output state")
        best, value = EMIT, self._emit_value(state)
        if self.allow_query and not state.queried and (
                state.generation.remaining >= cfg.emission_reserve
                + self.query_units):
            next_values = tuple(self.solve(
                query_next(state, w, self.query_units, cfg))[1]
                for w in (0, 1))
            weights = tuple(float(witness_probability(state.belief_zero, w))
                            for w in (0, 1))
            query_value = (-cfg.cost_shadow_price * self.query_units
                           + conditional_ce(next_values, weights,
                                            cfg.risk_aversion))
            if query_value > value + 1e-12:
                best, value = QUERY, query_value
        if self.allow_refine:
            for allocation in actions(state.generation, cfg)[1:]:
                values = tuple(self.solve(JointState(
                    advance(state.generation, allocation, shock, cfg),
                    state.belief_zero, state.queried))[1]
                    for shock in range(3))
                score = (-cfg.cost_shadow_price
                         * charge(state.generation, allocation, cfg)
                         + conditional_ce(values, SHOCK_PROBS,
                                          cfg.risk_aversion))
                if score > value + 1e-12:
                    best, value = JointAction("REFINE", allocation), score
        return best, value


def offline_audit(initial: JointState, controller: JointController,
                  policy: Callable[[JointState], JointAction] | None = None,
                  max_outcomes: int = 8192) -> dict:
    """Enumerate hidden-truth/witness/shock histories outside the controller.

    The independent scorer materializes actual toy outputs for each leaf.
    Exact full-path entropic risk must agree with nested Bellman valuation.
    This does not identify natural-world model error or real resource units.
    """
    if (type(max_outcomes) is not int or not 1 <= max_outcomes <= 8192
        or initial.generation.remaining < controller.cfg.emission_reserve):
        raise ValueError("unadmitted audit budget")
    cfg = controller.cfg
    decide = policy if policy is not None else lambda s: controller.solve(s)[0]
    rows: list[tuple[float, int, int, tuple[str, ...]]] = []

    def walk(state: JointState, truth: int, mass: float,
             trace: tuple[str, ...]):
        if len(rows) > max_outcomes:
            raise ValueError("independent path cap exceeded")
        action = decide(state)  # Only an observable JointState is supplied.
        if type(action) is not JointAction:
            raise ValueError("unadmitted policy decision")
        if action.kind == "EMIT":
            raw = emission(state)
            loss = raw_output_loss(raw, truth, cfg,
                                   controller.factual_penalty)
            paid = (initial.generation.remaining - state.generation.remaining
                    + cfg.emission_reserve)
            if paid > initial.generation.remaining:
                raise AssertionError("physical budget exceeded")
            rows.append((mass, loss, paid, trace + ("EMIT",)))
        elif action.kind == "QUERY":
            if state.queried or state.generation.remaining < (
                    cfg.emission_reserve + controller.query_units):
                raise ValueError("policy queried illegally")
            for w in (0, 1):
                prob = (WITNESS_ACCURACY if w == truth
                        else 1-WITNESS_ACCURACY)
                walk(query_next(state, w, controller.query_units, cfg),
                     truth, mass * float(prob), trace + ("QUERY",))
        else:
            allocation = action.allocation
            if (type(allocation) is not Allocation or allocation.stop
                or not feasible(state.generation, allocation, cfg)):
                raise ValueError("policy refined illegally")
            for shock, prob in enumerate(SHOCK_PROBS):
                walk(JointState(advance(state.generation, allocation, shock,
                                        cfg), state.belief_zero, state.queried),
                     truth, mass * prob, trace + ("REFINE",))

    for truth, p in ((0, initial.belief_zero),
                     (1, 1-initial.belief_zero)):
        if p:
            walk(initial, truth, float(p), ())
    if len(rows) > max_outcomes:
        raise ValueError("independent path cap exceeded")
    weights = [row[0] for row in rows]
    if not math.isclose(math.fsum(weights), 1, rel_tol=0, abs_tol=1e-10):
        raise AssertionError("incomplete independent outcome mass")
    values = tuple(-loss-cfg.cost_shadow_price*paid
                   for _, loss, paid, _ in rows)
    full_value = conditional_ce(values, tuple(weights), cfg.risk_aversion)
    observed_cost = math.fsum(p*paid for p, _, paid, _ in rows)
    return {
        "scope": "FINITE_SYNTHETIC_DENY_ALL",
        "full_path_utility": full_value,
        "mean_external_loss": math.fsum(p*loss for p, loss, _, _ in rows),
        "mean_modeled_units": observed_cost,
        "cvar90_external_loss": empirical_cvar90(
            [float(loss) for _, loss, _, _ in rows], weights),
        "path_count": len(rows),
        "query_path_fraction": math.fsum(
            p for p, _, _, trace in rows if "QUERY" in trace),
        "refine_path_fraction": math.fsum(
            p for p, _, _, trace in rows if "REFINE" in trace),
        "four_outputs_every_path": True,
        "all_budget_feasible": True,
        "distinct_decision_traces": len({trace for _, _, _, trace in rows}),
    }


def public_state(mode: str, levels: tuple[int, int, int, int],
                 budget: int) -> JointState:
    return JointState(State(levels, budget), prior_from_public(mode))
