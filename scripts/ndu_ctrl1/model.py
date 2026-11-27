"""Finite CTRL-1 research SMDP; exact rational kernels, FP64 utility only.

The hidden bit denotes whether execution will succeed. Sensors expose a noisy
label AND their elapsed time/resource charge. Repair changes the hidden bit's
law without exposing its realization. No native caller or deployment is implied.
"""

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math

from ndu_real_runtime.objective import PROFILE_ID, certainty_equivalent, edge_value

ADAPTER_ID = "hepta.ctrl1.resource-cost.v1"
ACTIONS = ("stop", "execute", "observe", "recall", "verify", "repair")
MAX_SUPPORT = 512
_BITS = {"observe": 1, "recall": 2, "verify": 4, "repair": 8}


@dataclass(frozen=True)
class Profile:
    risk: float = 0.25
    discount_per_second: float = 0.97
    latency_weight: float = 0.01
    resource_weight: float = 0.02
    profile_id: str = PROFILE_ID
    adapter_id: str = ADAPTER_ID

    def __post_init__(self):
        for name, ceiling in (
            ("risk", 64),
            ("discount_per_second", 1),
            ("latency_weight", 16),
            ("resource_weight", 16),
        ):
            value = getattr(self, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value <= ceiling
            ):
                raise ValueError(f"Invalid bounded profile field: {name}")
        if self.profile_id != PROFILE_ID or self.adapter_id != ADAPTER_ID:
            raise ValueError("Unknown objective profile or resource adapter")
        if self.discount_per_second == 0:
            raise ValueError("Finite-entropic v1 requires discount in (0, 1]")


@dataclass(frozen=True)
class Scenario:
    prior: Fraction = Fraction(1, 2)
    deadline: int = 8
    budget: int = 8
    horizon: int = 4
    variable_time: bool = True
    signal_accuracy: Fraction = Fraction(3, 4)
    repair_success: Fraction = Fraction(1, 2)
    stop_reward: float = 0.35
    outcome_correlation: int = 1

    def __post_init__(self):
        for name in ("prior", "signal_accuracy", "repair_success"):
            value = getattr(self, name)
            if (
                not isinstance(value, Fraction)
                or not 0 <= value <= 1
                or value.denominator > 1_000_000
            ):
                raise ValueError(f"Invalid bounded rational probability: {name}")
        if self.signal_accuracy < Fraction(1, 2):
            raise ValueError("Sensor accuracy must be at least chance")
        for name, ceiling in (("deadline", 12), ("budget", 16), ("horizon", 4)):
            if (
                type(getattr(self, name)) is not int
                or not 0 <= getattr(self, name) <= ceiling
            ):
                raise ValueError(f"Invalid finite scenario limit: {name}")
        if (
            type(self.variable_time) is not bool
            or type(self.outcome_correlation) is not int
            or self.outcome_correlation not in (-1, 0, 1)
        ):
            raise ValueError("Invalid time regime or outcome correlation")
        if (
            type(self.stop_reward) not in (int, float)
            or not math.isfinite(self.stop_reward)
            or not 0 <= self.stop_reward <= 1
        ):
            raise ValueError("Stop reward must lie in the declared terminal range")


@dataclass(frozen=True)
class State:
    belief: Fraction
    time_left: int
    budget_left: int
    steps_left: int
    used_mask: int = 0

    def __post_init__(self):
        if not isinstance(self.belief, Fraction) or not 0 <= self.belief <= 1:
            raise ValueError("Belief must be an exact probability")
        for name, ceiling in (
            ("time_left", 12),
            ("budget_left", 16),
            ("steps_left", 4),
            ("used_mask", 15),
        ):
            if (
                type(getattr(self, name)) is not int
                or not 0 <= getattr(self, name) <= ceiling
            ):
                raise ValueError(f"Invalid state field: {name}")


@dataclass(frozen=True)
class Outcome:
    probability: Fraction
    duration: int
    cost: int
    observation: str
    next_state: State | None
    reward: float | None


def initial_state(scenario):
    return State(scenario.prior, scenario.deadline, scenario.budget, scenario.horizon)


def _check_state(scenario, state):
    if (
        state.time_left > scenario.deadline
        or state.budget_left > scenario.budget
        or state.steps_left > scenario.horizon
    ):
        raise ValueError("State exceeds its scenario's initial limits")


def _public_kernel(scenario, action, latent):
    """Yield (duration, cost, label, likelihood) conditional on the hidden bit."""
    if action == "execute":
        aligned = Fraction(1, 2) + Fraction(scenario.outcome_correlation, 4)
        labels = (("success" if latent else "failure", Fraction(1)),)
        cheap, dear = 1, 3
    else:
        aligned = scenario.signal_accuracy
        accuracy = aligned
        if action == "recall":
            accuracy = (accuracy + Fraction(1, 2)) / 2
        elif action == "verify":
            accuracy = 1 - 2 * (1 - accuracy) ** 2
        positive = accuracy if latent else 1 - accuracy
        labels = (("positive", positive), ("negative", 1 - positive))
        cheap = 2 if action == "verify" else 1
        dear = cheap + 1
    fast_probability = aligned if latent else 1 - aligned
    # Fixed-time keeps the cost law; recall always has a one-second lookup.
    if action == "recall":
        durations = ((1, Fraction(1)),)
    elif scenario.variable_time:
        durations = ((1, fast_probability), (3, 1 - fast_probability))
    else:
        durations = ((2, Fraction(1)),)
    costs = ((cheap, fast_probability), (dear, 1 - fast_probability))
    for duration, pd in durations:
        for cost, pc in costs:
            for label, po in labels:
                probability = pd * pc * po
                if probability:
                    yield duration, cost, label, probability


@lru_cache(maxsize=8192)
def transitions(scenario, state, action):
    """Return complete positive-mass support; reject worst-support overspend."""
    _check_state(scenario, state)
    if action not in ACTIONS:
        raise ValueError("Unknown action")
    if action == "stop":
        return (
            Outcome(Fraction(1), 0, 0, "delivered", None, float(scenario.stop_reward)),
        )
    if not state.steps_left or state.used_mask & _BITS.get(action, 0):
        raise ValueError("Action has no remaining step or was already consumed")
    # A public key aggregates latent mass before Bayes conditioning. Neither a
    # private hidden-state label nor a sampled true bit enters a sensor outcome.
    groups = {}
    if action == "repair":
        belief = state.belief + (1 - state.belief) * scenario.repair_success
        groups[(2, 2, "repair_attempted")] = [1 - belief, belief]
    else:
        for latent, prior in ((0, 1 - state.belief), (1, state.belief)):
            for duration, cost, label, likelihood in _public_kernel(
                scenario, action, latent
            ):
                if prior * likelihood:
                    masses = groups.setdefault(
                        (duration, cost, label), [Fraction(0), Fraction(0)]
                    )
                    masses[latent] += prior * likelihood
    if any(
        duration > state.time_left or cost > state.budget_left
        for duration, cost, _ in groups
    ):
        raise ValueError("Action can exceed remaining time or resource budget")
    result = []
    for (duration, cost, label), masses in sorted(groups.items()):
        probability = sum(masses, Fraction(0))
        terminal = action == "execute"
        successor = (
            None
            if terminal
            else State(
                masses[1] / probability,
                state.time_left - duration,
                state.budget_left - cost,
                state.steps_left - 1,
                state.used_mask | _BITS[action],
            )
        )
        reward = float(label == "success") if terminal else None
        result.append(Outcome(probability, duration, cost, label, successor, reward))
    if (
        not 0 < len(result) <= MAX_SUPPORT
        or sum((o.probability for o in result), Fraction(0)) != 1
    ):
        raise ValueError("Invalid finite transition support")
    return tuple(result)


@lru_cache(maxsize=8192)
def legal_actions(scenario, state):
    _check_state(scenario, state)
    allowed = []
    for action in ACTIONS:
        try:
            transitions(scenario, state, action)
        except ValueError:
            continue
        allowed.append(action)
    return tuple(allowed)


def backup(outcomes, continuations, profile):
    """Nested finite-entropic edge backup with explicit immediate resource cost.

    The resource charge is outside temporal discount but inside this edge's CE.
    Callers supply observed terminal rewards, or frozen forecast values when making
    a prediction; evaluation must always use the environment's terminal rewards.
    """
    outcomes, continuations = tuple(outcomes), tuple(continuations)
    if not 0 < len(outcomes) <= MAX_SUPPORT or len(outcomes) != len(continuations):
        raise ValueError("Invalid backup support or continuation length")
    if (
        any(
            not isinstance(o.probability, Fraction) or o.probability <= 0
            for o in outcomes
        )
        or sum((o.probability for o in outcomes), Fraction(0)) != 1
    ):
        raise ValueError("Backup probabilities must be an exact positive distribution")
    if any(
        type(o.duration) is not int
        or type(o.cost) is not int
        or not 0 <= o.duration <= 12
        or not 0 <= o.cost <= 16
        for o in outcomes
    ):
        raise ValueError("Backup duration or cost is outside finite support")
    if any(
        type(value) not in (int, float) or not math.isfinite(value)
        for value in continuations
    ):
        raise ValueError("Continuations must be finite non-boolean numbers")
    values = [
        -profile.resource_weight * o.cost + edge_value(o.duration, value, profile)
        for o, value in zip(outcomes, continuations)
    ]
    return certainty_equivalent(
        values, [float(o.probability) for o in outcomes], profile.risk
    )
