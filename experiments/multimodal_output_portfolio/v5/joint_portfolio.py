"""Finite jointly budgeted four-output generation and independent evidence control.

Synthetic RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL reference. Public state
excludes terminal truth and unrevealed reports. REFINE has a joint noise driver;
QUERY is a paid, single-use Bayesian observation. Four raw toy outputs are
materialized and scored against external truth only at termination.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from itertools import product
import math

MODALITIES = ("text", "audio", "image", "video")
SHOCKS = ((0, Fraction(1, 5)), (1, Fraction(1, 4)),
          (2, Fraction(11, 20)))
QUERY = "QUERY"
STOP = "STOP"


@dataclass(frozen=True)
class Profile:
    horizon: int = 3
    max_units_per_step: int = 2
    allocation_unit_cost: int = 1
    activation_cost: int = 1
    witness_cost: int = 1
    emission_cost_each: int = 1
    factual_error_cost: int = 8
    sync_error_cost: int = 5
    gamma: float = 1.0
    shadow_price: float = 0.05
    witness_accuracy: Fraction = Fraction(49, 50)

    def __post_init__(self):
        integers = (
            self.horizon, self.max_units_per_step, self.allocation_unit_cost,
            self.activation_cost, self.witness_cost, self.emission_cost_each,
            self.factual_error_cost, self.sync_error_cost,
        )
        if (
            any(type(value) is not int for value in integers)
            or not 1 <= self.horizon <= 3
            or not 1 <= self.max_units_per_step <= 2
            or self.allocation_unit_cost < 1 or self.activation_cost < 0
            or self.witness_cost < 1 or self.emission_cost_each < 1
            or self.factual_error_cost < 1 or self.sync_error_cost < 0
            or type(self.gamma) not in (int, float)
            or not math.isfinite(self.gamma)
            or not 0 <= self.gamma <= 10
            or type(self.shadow_price) not in (int, float)
            or not math.isfinite(self.shadow_price)
            or self.shadow_price < 0
            or type(self.witness_accuracy) is not Fraction
            or not Fraction(1, 2) < self.witness_accuracy < Fraction(1)
        ):
            raise ValueError("invalid joint control profile")

    @property
    def emission_reserve(self) -> int:
        return 4 * self.emission_cost_each


@dataclass(frozen=True)
class PublicState:
    levels: tuple[int, int, int, int]
    p_truth_zero: Fraction
    remaining: int
    stage: int = 0
    active_mask: int = 0
    witnessed: bool = False

    def __post_init__(self):
        if (
            type(self.levels) is not tuple or len(self.levels) != 4
            or any(type(x) is not int or not 0 <= x <= 2
                   for x in self.levels)
            or type(self.p_truth_zero) is not Fraction
            or not Fraction(0) <= self.p_truth_zero <= Fraction(1)
            or type(self.remaining) is not int or self.remaining < 0
            or type(self.stage) is not int or self.stage < 0
            or type(self.active_mask) is not int
            or not 0 <= self.active_mask <= 15
            or type(self.witnessed) is not bool
        ):
            raise ValueError("invalid public state")


@dataclass(frozen=True)
class Refine:
    units: tuple[int, int, int, int]

    def __post_init__(self):
        if (
            type(self.units) is not tuple or len(self.units) != 4
            or any(type(u) is not int or not 0 <= u <= 2
                   for u in self.units)
            or sum(self.units) < 1
        ):
            raise ValueError("invalid refinement vector")

    @property
    def mask(self) -> int:
        return sum(1 << i for i, u in enumerate(self.units) if u)


def cost(state: PublicState, action: Refine, cfg: Profile) -> int:
    return (
        sum(action.units) * cfg.allocation_unit_cost
        + (action.mask & ~state.active_mask).bit_count()
        * cfg.activation_cost
    )


def legal_actions(state: PublicState, cfg: Profile):
    if state.remaining < cfg.emission_reserve or state.stage > cfg.horizon:
        raise ValueError("unfunded or exhausted output generation")
    result = [STOP]
    if state.stage == cfg.horizon:
        return tuple(result)
    if not state.witnessed and (
        state.remaining >= cfg.emission_reserve + cfg.witness_cost
    ):
        result.append(QUERY)
    for vector in product(range(3), repeat=4):
        if 0 < sum(vector) <= cfg.max_units_per_step:
            allocation = Refine(vector)
            if state.remaining >= cfg.emission_reserve + cost(
                state, allocation, cfg
            ):
                result.append(allocation)
    return tuple(result)


def witness_likelihood(truth: int, report: int, accuracy: Fraction):
    if (
        type(truth) is not int or truth not in (0, 1)
        or type(report) is not int or report not in (0, 1)
    ):
        raise ValueError("invalid private witness observation")
    return accuracy if truth == report else 1 - accuracy


def witness_probability(
    state: PublicState, report: int, cfg: Profile
) -> Fraction:
    return (
        state.p_truth_zero
        * witness_likelihood(0, report, cfg.witness_accuracy)
        + (1 - state.p_truth_zero)
        * witness_likelihood(1, report, cfg.witness_accuracy)
    )


def observe_witness(
    state: PublicState, report: int, cfg: Profile
) -> PublicState:
    if QUERY not in legal_actions(state, cfg):
        raise ValueError("query not funded, already used, or over horizon")
    mass = witness_probability(state, report, cfg)
    if mass == 0:
        raise ValueError("impossible witness observation")
    posterior = (
        state.p_truth_zero
        * witness_likelihood(0, report, cfg.witness_accuracy) / mass
    )
    return PublicState(
        state.levels, posterior, state.remaining - cfg.witness_cost,
        state.stage + 1, state.active_mask, True,
    )


def observe_refinement(
    state: PublicState, action: Refine, shock: int, cfg: Profile
) -> PublicState:
    if (
        action not in legal_actions(state, cfg)
        or type(shock) is not int or shock not in (0, 1, 2)
    ):
        raise ValueError("invalid refinement or future shock")
    levels = tuple(
        min(2, old + min(units, shock))
        for old, units in zip(state.levels, action.units)
    )
    return PublicState(
        levels, state.p_truth_zero,
        state.remaining - cost(state, action, cfg),
        state.stage + 1, action.mask, state.witnessed,
    )


def emission(state: PublicState) -> dict:
    # Four distinct *toy* media objects repeat a claim. Repetition of a claim
    # is not independent evidence of its factual correctness.
    t, a, i, v = state.levels
    claimed = 0 if state.p_truth_zero >= Fraction(1, 2) else 1
    return {
        "text": (f"symbol:{t}", claimed),
        "audio": ((a, -a, a, -a), claimed),
        "image": (((i, i), (i, i)), claimed),
        "video": ((((v, v), (v, v)), ((v, v), (v, v))), claimed),
    }


def terminal_external_loss(
    output: dict, truth: int, cfg: Profile
) -> int:
    # This registered fixture represents an independently supplied observer.
    # The live control policy never reads the realized truth.
    if (
        type(output) is not dict or set(output) != set(MODALITIES)
        or type(truth) is not int or truth not in (0, 1)
    ):
        raise ValueError("invalid independently observed raw output")
    try:
        text, claim_t = output["text"]
        audio, claim_a = output["audio"]
        image, claim_i = output["image"]
        video, claim_v = output["video"]
        t = int(text.removeprefix("symbol:"))
        a, i, v = audio[0], image[0][0], video[0][0][0]
        if (
            text != f"symbol:{t}" or audio != (a, -a, a, -a)
            or image != ((i, i), (i, i))
            or video != (((v, v), (v, v)), ((v, v), (v, v)))
            or any(type(q) is not int or not 0 <= q <= 2
                   for q in (t, a, i, v))
            or any(type(q) is not int or q not in (0, 1)
                   for q in (claim_t, claim_a, claim_i, claim_v))
        ):
            raise ValueError("malformed raw modality")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ValueError("malformed raw modality") from exc

    factual_error_count = sum(
        claim != truth for claim in (claim_t, claim_a, claim_i, claim_v)
    )
    return (
        sum((2 - q) ** 2 for q in (t, a, i, v))
        + cfg.sync_error_cost * int(i != v)
        + cfg.sync_error_cost * int(abs(t - a) > 1)
        + cfg.factual_error_cost * factual_error_count // 4
        + cfg.factual_error_cost
        * int(len({claim_t, claim_a, claim_i, claim_v}) > 1)
    )


def conditional_ce(values, probabilities, gamma):
    if (
        not values or len(values) != len(probabilities)
        or any(not math.isfinite(v) for v in values)
        or any(not math.isfinite(p) or p < 0 for p in probabilities)
        or not math.isclose(
            math.fsum(probabilities), 1.0, rel_tol=0, abs_tol=1e-12
        )
    ):
        raise ValueError("invalid conditional risk law")
    if gamma == 0:
        return math.fsum(v * p for v, p in zip(values, probabilities))
    support = [(v, p) for v, p in zip(values, probabilities) if p > 0]
    anchor = min(v for v, _ in support)
    return anchor - math.log(
        math.fsum(p * math.exp(-gamma * (v - anchor))
                  for v, p in support)
    ) / gamma


class SolverBudgetExceeded(RuntimeError):
    """The finite value search exhausted its separately metered work cap."""


class JointController:
    """Finite nonanticipative Bellman solver, not a neural FBSDE solver."""

    def __init__(self, cfg: Profile, max_expansions: int = 100000):
        if type(max_expansions) is not int or max_expansions < 1:
            raise ValueError("invalid finite solver work cap")
        self.cfg = cfg
        self.max_expansions = max_expansions
        self.value_expansions = 0

    def select_with_fallback(self, state: PublicState):
        """Explicit bounded-work advisory; never claim fallback is optimal."""
        legal_actions(state, self.cfg)
        try:
            action, value = self.solve(state)
        except SolverBudgetExceeded:
            return STOP, self.terminal(state), "BUDGETED_STOP_FALLBACK"
        return action, value, "EXACT_FINITE_VALUE"

    def terminal(self, state: PublicState):
        output = emission(state)
        values = [
            -terminal_external_loss(output, truth, self.cfg)
            - self.cfg.shadow_price * self.cfg.emission_reserve
            for truth in (0, 1)
        ]
        return conditional_ce(
            values,
            (float(state.p_truth_zero), float(1 - state.p_truth_zero)),
            self.cfg.gamma,
        )

    @lru_cache(maxsize=100000)
    def solve(self, state: PublicState):
        if self.value_expansions >= self.max_expansions:
            raise SolverBudgetExceeded("finite value search cap exceeded")
        self.value_expansions += 1
        candidates = legal_actions(state, self.cfg)
        best_action, best_value = STOP, self.terminal(state)
        for action in candidates[1:]:
            if action == QUERY:
                successors = [
                    self.solve(observe_witness(state, r, self.cfg))[1]
                    for r in (0, 1)
                ]
                weights = [
                    float(witness_probability(state, r, self.cfg))
                    for r in (0, 1)
                ]
                step_cost = self.cfg.witness_cost
            else:
                successors = [
                    self.solve(
                        observe_refinement(state, action, shock, self.cfg)
                    )[1]
                    for shock, _ in SHOCKS
                ]
                weights = [float(p) for _, p in SHOCKS]
                step_cost = cost(state, action, self.cfg)
            estimate = (
                -self.cfg.shadow_price * step_cost
                + conditional_ce(successors, weights, self.cfg.gamma)
            )
            if estimate > best_value + 1e-12:
                best_action, best_value = action, estimate
        return best_action, best_value


def independent_path_audit(
    initial: PublicState, cfg: Profile, policy,
    actual_witness_accuracy: Fraction | None = None,
):
    """Enumerate hidden truth, reported evidence and common shocks.

    All scores are computed after four actual toy outputs are emitted.
    The optional actual evidence law is distinct from the controller's
    frozen *assumed* witness accuracy for dependence/shift falsification.
    """
    if initial.stage != 0 or initial.remaining < cfg.emission_reserve:
        raise ValueError("invalid audit initial state")
    if actual_witness_accuracy is None:
        actual_witness_accuracy = cfg.witness_accuracy
    if (
        type(actual_witness_accuracy) is not Fraction
        or not Fraction(0) <= actual_witness_accuracy <= Fraction(1)
    ):
        raise ValueError("invalid independent witness law")
    rows = []

    def visit(state, truth, probability, trace):
        action = policy(state)
        if action not in legal_actions(state, cfg):
            raise ValueError("audit observed inadmissible action")
        if action == STOP:
            output = emission(state)
            loss = terminal_external_loss(output, truth, cfg)
            paid = initial.remaining - state.remaining + cfg.emission_reserve
            if paid > initial.remaining:
                raise AssertionError("unfunded emission")
            rows.append((
                probability, -loss - cfg.shadow_price * paid,
                loss, paid, trace, output,
            ))
        elif action == QUERY:
            for report in (0, 1):
                visit(
                    observe_witness(state, report, cfg), truth,
                    probability * witness_likelihood(
                        truth, report, actual_witness_accuracy,
                    ),
                    trace + (("QUERY", report),),
                )
        else:
            for shock, mass in SHOCKS:
                visit(
                    observe_refinement(state, action, shock, cfg), truth,
                    probability * mass, trace + ((action.units, shock),),
                )

    for truth, prior in (
        (0, initial.p_truth_zero), (1, 1 - initial.p_truth_zero)
    ):
        if prior:
            visit(initial, truth, prior, ())
    mass = sum((p for p, *_ in rows), Fraction(0))
    if mass != 1:
        raise AssertionError("path mass not conserved")
    probs = [float(p) for p, *_ in rows]
    values = [v for _, v, *_ in rows]
    mean_loss = math.fsum(
        float(p) * loss for p, _, loss, *_ in rows
    )
    return {
        "risk_utility": conditional_ce(values, probs, cfg.gamma),
        "mean_loss": mean_loss,
        "mean_paid_units": math.fsum(
            float(p) * paid for p, _, _, paid, *_ in rows
        ),
        "support_paths": len(rows),
        "unique_traces": len({trace for *_, trace, _ in rows}),
        "all_four_outputs": all(
            set(output) == set(MODALITIES) for *_, output in rows
        ),
        "all_funded": all(
            paid <= initial.remaining for _, _, _, paid, *_ in rows
        ),
        "fractional_cvar90": upper_tail90(rows),
    }


def upper_tail90(rows):
    tail = Fraction(1, 10)
    total = Fraction(0)
    for p, _, loss, *_ in sorted(
        rows, key=lambda row: row[2], reverse=True
    ):
        take = min(p, tail)
        total += take * loss
        tail -= take
        if tail == 0:
            break
    if tail:
        raise ValueError("missing terminal probability mass")
    return float(total / Fraction(1, 10))
