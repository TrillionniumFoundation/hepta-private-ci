"""Finite four-output NDU portfolio with correlated observations and real feedback.

RESEARCH ONLY. Each output is a binary symbolic channel, NOT natural media.
Every policy sees public reports/feedback, never the held-out hidden truth.
Terminal loss is fixed externally; utility is time-consistent entropic CE.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product, permutations
from math import exp, isfinite, log

NAMES = ("text", "audio", "image", "video")
EMIT_COST = 4  # All four symbolic outputs are mandatory.
UNOBSERVED = -1


class InvalidModel(ValueError):
    pass


def certainty_equivalent(values: tuple[float, ...], probs: tuple[float, ...], gamma: float) -> float:
    if len(values) != len(probs) or not values or not all(isfinite(v) for v in values):
        raise InvalidModel("finite values and aligned distribution required")
    if not isfinite(gamma) or gamma < 0 or any(not isfinite(p) or p < 0 for p in probs):
        raise InvalidModel("invalid probability or risk coefficient")
    if abs(sum(probs) - 1) > 1e-9:
        raise InvalidModel("distribution must sum to one")
    if gamma == 0:
        return sum(p * v for p, v in zip(probs, values))
    z = max(-gamma * v for p, v in zip(probs, values) if p > 0)
    return -(z + log(sum(p * exp(-gamma * v - z) for p, v in zip(probs, values) if p > 0))) / gamma


@dataclass(frozen=True)
class Model:
    """Full 4-report joint law via latent common corruption switch."""

    common_flip: float = 0.18
    report_error: tuple[float, ...] = (0.04, 0.12, 0.20, 0.28)
    probe_accuracy: tuple[float, ...] = (0.90, 0.83, 0.86, 0.94)
    witness_accuracy: float = 0.95  # Witness observes common flip, not truth.
    witness_cost: int = 2
    gamma: float = 1.5
    cost_penalty: float = 0.025

    def __post_init__(self):
        if len(self.report_error) != 4 or len(self.probe_accuracy) != 4:
            raise InvalidModel("four output channels required")
        if any(not isfinite(x) or x <= 0 or x >= 1 for x in
               (self.common_flip, self.witness_accuracy, *self.report_error, *self.probe_accuracy)):
            raise InvalidModel("probabilities must be strictly between 0 and 1")
        if not isfinite(self.cost_penalty) or self.cost_penalty < 0 or not isfinite(self.gamma) or self.gamma < 0:
            raise InvalidModel("invalid utility coefficient")
        if type(self.witness_cost) is not int or self.witness_cost < 1:
            raise InvalidModel("witness cost must be positive integer")


@dataclass(frozen=True)
class State:
    reports: tuple[int, int, int, int]
    probes: tuple[int, int, int, int] = (-1, -1, -1, -1)
    witness: int = -1
    budget: int = 6

    def __post_init__(self):
        if len(self.reports) != 4 or any(v not in (0, 1) for v in self.reports):
            raise InvalidModel("four binary public reports required")
        if len(self.probes) != 4 or any(v not in (-1, 0, 1) for v in self.probes):
            raise InvalidModel("invalid probe feedback")
        if self.witness not in (-1, 0, 1) or type(self.budget) is not int or self.budget < EMIT_COST:
            raise InvalidModel("invalid witness or inadequate all-output budget")

    def after(self, action: str, bit: int, cost: int) -> State:
        if bit not in (0, 1) or cost <= 0 or self.budget - cost < EMIT_COST:
            raise InvalidModel("invalid transition or terminal cost not reserved")
        if action == "witness" and self.witness == -1:
            return State(self.reports, self.probes, bit, self.budget - cost)
        if action in NAMES:
            i = NAMES.index(action)
            if self.probes[i] == -1:
                probes = list(self.probes)
                probes[i] = bit
                return State(self.reports, tuple(probes), self.witness, self.budget - cost)
        raise InvalidModel("duplicate or unknown action")

    @property
    def steps(self) -> int:
        return sum(v != -1 for v in self.probes) + int(self.witness != -1)


@dataclass(frozen=True)
class Decision:
    value: float
    action: str
    outputs: tuple[int, int, int, int] | None


def _bit(index: int, i: int) -> int:
    return (index >> i) & 1


def _likelihood(obs: int, true: int, accuracy: float) -> float:
    return accuracy if obs == true else 1.0 - accuracy


def external_loss(outputs: tuple[int, ...], hidden_truth: int) -> float:
    """Immutable external four-channel task metric; independent of critic scores."""
    if len(outputs) != 4 or any(x not in (0, 1) for x in outputs):
        raise InvalidModel("all four emitted symbols required")
    return sum(outputs[i] != _bit(hidden_truth, i) for i in range(4)) / 4.0


class Portfolio:
    def __init__(self, model: Model, max_states: int = 100_000):
        if type(max_states) is not int or max_states < 1:
            raise InvalidModel("positive planning cap required")
        self.model, self.max_states, self.visited = model, max_states, 0

    @lru_cache(maxsize=100_000)
    def posterior(self, state: State) -> tuple[float, ...]:
        """32 latent worlds: truth(0..15) x shared-error switch(0..1)."""
        law = self.model
        ps = []
        for truth in range(16):
            for common in range(2):
                p = (law.common_flip if common else (1 - law.common_flip)) / 16
                for i in range(4):
                    p *= _likelihood(state.reports[i], _bit(truth, i) ^ common, 1 - law.report_error[i])
                    if state.probes[i] != -1:
                        p *= _likelihood(state.probes[i], _bit(truth, i), law.probe_accuracy[i])
                if state.witness != -1:
                    p *= _likelihood(state.witness, common, law.witness_accuracy)
                ps.append(p)
        total = sum(ps)
        if total <= 0 or not isfinite(total):
            raise InvalidModel("unsupported observation or failed normalization")
        return tuple(p / total for p in ps)

    def likelihood(self, action: str, feedback: int, truth: int, common: int) -> float:
        if action == "witness":
            return _likelihood(feedback, common, self.model.witness_accuracy)
        return _likelihood(feedback, _bit(truth, NAMES.index(action)),
                           self.model.probe_accuracy[NAMES.index(action)])

    def legal(self, state: State) -> tuple[tuple[str, int], ...]:
        options = tuple((name, 1) for i, name in enumerate(NAMES)
                        if state.probes[i] == -1 and state.budget - 1 >= EMIT_COST)
        if state.witness == -1 and state.budget - self.model.witness_cost >= EMIT_COST:
            return options + (("witness", self.model.witness_cost),)
        return options

    def outcome_distribution(self, state: State, action: str) -> tuple[float, float]:
        p = self.posterior(state)
        zero = sum(p[2 * t + c] * self.likelihood(action, 0, t, c)
                   for t in range(16) for c in range(2))
        return (zero, 1 - zero)

    @lru_cache(maxsize=100_000)
    def emit(self, state: State) -> Decision:
        p = self.posterior(state)
        best = Decision(float("-inf"), "emit", None)
        for mask in range(16):
            output = tuple(_bit(mask, i) for i in range(4))
            utilities = tuple(-external_loss(output, truth)
                              for truth in range(16) for _common in range(2))
            v = certainty_equivalent(utilities, p, self.model.gamma) - self.model.cost_penalty * EMIT_COST
            if v > best.value + 1e-12:
                best = Decision(v, "emit", output)
        return best

    @lru_cache(maxsize=100_000)
    def solve(self, state: State) -> Decision:
        self.visited += 1
        if self.visited > self.max_states:
            raise InvalidModel("planning-state cap reached; no unvalidated fallback")
        best = self.emit(state)
        for action, cost in self.legal(state):
            probs = self.outcome_distribution(state, action)
            child_values = tuple(self.solve(state.after(action, obs, cost)).value for obs in (0, 1))
            value = certainty_equivalent(child_values, probs, self.model.gamma) - cost * self.model.cost_penalty
            if value > best.value + 1e-12:
                best = Decision(value, action, None)
        return best

    def _static_value(self, state: State, sequence: tuple[str, ...]) -> float:
        if not sequence:
            return self.emit(state).value
        action = sequence[0]
        cost = self.model.witness_cost if action == "witness" else 1
        probs = self.outcome_distribution(state, action)
        vals = tuple(self._static_value(state.after(action, bit, cost), sequence[1:]) for bit in (0, 1))
        return certainty_equivalent(vals, probs, self.model.gamma) - cost * self.model.cost_penalty

    @lru_cache(maxsize=100_000)
    def static_schedule(self, root: State) -> tuple[str, ...]:
        """Strong ex-ante static comparator: optimize fixed action sequence on initial reports."""
        if root.steps:
            raise InvalidModel("static schedule must be chosen before feedback")
        options = tuple(name for name, _ in self.legal(root))
        remaining = root.budget - EMIT_COST
        best_value = self._static_value(root, ())
        best_sequence: tuple[str, ...] = ()
        for k in range(1, min(remaining, len(options)) + 1):
            for seq in permutations(options, k):
                spent = sum(self.model.witness_cost if a == "witness" else 1 for a in seq)
                if spent > remaining:
                    continue
                v = self._static_value(root, seq)
                if v > best_value + 1e-12:
                    best_value, best_sequence = v, seq
        return best_sequence

    def choose(self, state: State, mode: str = "dynamic", root_budget: int | None = None) -> Decision:
        if mode == "dynamic":
            return self.solve(state)
        if mode == "myopic":
            best = self.emit(state)
            for action, cost in self.legal(state):
                probs = self.outcome_distribution(state, action)
                val = certainty_equivalent(tuple(self.emit(state.after(action, obs, cost)).value
                                              for obs in (0, 1)), probs, self.model.gamma)
                val -= cost * self.model.cost_penalty
                if val > best.value + 1e-12:
                    best = Decision(val, action, None)
            return best
        if mode == "static":
            if root_budget is None:
                raise InvalidModel("root budget required for fixed schedule")
            root = State(state.reports, budget=root_budget)
            schedule = self.static_schedule(root)
            if state.steps < len(schedule):
                return Decision(float("nan"), schedule[state.steps], None)
            return self.emit(state)
        raise InvalidModel("unknown policy")


def _initial_world_probability(model: Model, truth: int, common: int, reports: tuple[int, ...]) -> float:
    prob = (model.common_flip if common else 1.0 - model.common_flip) / 16
    for i, report in enumerate(reports):
        prob *= _likelihood(report, _bit(truth, i) ^ common, 1 - model.report_error[i])
    return prob


def fractional_cvar(losses: list[tuple[float, float]], alpha: float = 0.9) -> float:
    """Worst tail mass with fractional boundary; no ceil-tail underpricing."""
    if not (0 < alpha < 1) or not losses:
        raise InvalidModel("invalid tail level/distribution")
    tail = 1 - alpha
    left = tail
    total = 0.0
    if abs(sum(p for _, p in losses) - 1) > 1e-8:
        raise InvalidModel("scenario probabilities are not normalized")
    for loss, p in sorted(losses, key=lambda row: -row[0]):
        mass = min(p, left)
        total += mass * loss
        left -= mass
        if left <= 1e-12:
            break
    return total / tail


def evaluate_exact(policy: Portfolio, true_law: Model, mode: str, budget: int) -> dict:
    """Independent truth-bearing evaluator, never passed to the runtime policy."""
    if type(budget) is not int or budget < EMIT_COST:
        raise InvalidModel("budget must cover all outputs")
    loss_mass: list[tuple[float, float]] = []
    total_loss = total_cost = refine_rate = query_rate = 0.0
    total_prob = 0.0

    def visit(state: State, truth: int, common: int, mass: float, spent: int):
        nonlocal total_loss, total_cost, refine_rate, query_rate, total_prob
        choice = policy.choose(state, mode, root_budget=budget)
        if choice.action == "emit":
            if choice.outputs is None or spent + EMIT_COST > budget:
                raise InvalidModel("missing emission or budget violation")
            loss = external_loss(choice.outputs, truth)
            total_loss += mass * loss
            total_cost += mass * (spent + EMIT_COST)
            refine_rate += mass * int(any(x != -1 for x in state.probes))
            query_rate += mass * int(state.witness != -1)
            total_prob += mass
            loss_mass.append((loss, mass))
            return
        cost = true_law.witness_cost if choice.action == "witness" else 1
        if (choice.action, cost) not in policy.legal(state):
            raise InvalidModel("illegal policy action or cost-model mismatch")
        for bit in (0, 1):
            likelihood = _likelihood(bit, common, true_law.witness_accuracy) if choice.action == "witness" \
                else _likelihood(bit, _bit(truth, NAMES.index(choice.action)),
                                 true_law.probe_accuracy[NAMES.index(choice.action)])
            visit(state.after(choice.action, bit, cost), truth, common, mass * likelihood, spent + cost)

    for truth in range(16):
        for common in range(2):
            for reports in product((0, 1), repeat=4):
                p = _initial_world_probability(true_law, truth, common, reports)
                visit(State(reports, budget=budget), truth, common, p, 0)
    if abs(total_prob - 1) > 1e-8:
        raise InvalidModel("evaluation lost probability mass")
    return {"mean_external_loss": total_loss, "cvar90_external_loss": fractional_cvar(loss_mass),
            "mean_symbolic_cost_units": total_cost, "any_refinement_rate": refine_rate,
            "witness_query_rate": query_rate, "terminal_coverage": total_prob,
            "solver_states": policy.visited, "models_are_synthetic": True}


def verify_external_loss(outputs: tuple[int, ...], truth: int, claimed_loss: float) -> bool:
    """An independently observed truth is required; caller scores cannot relabel failures."""
    if type(truth) is not int or truth not in range(16):
        raise InvalidModel("independent truth must identify one of 16 worlds")
    if not isfinite(claimed_loss) or abs(external_loss(outputs, truth) - claimed_loss) > 1e-12:
        raise InvalidModel("reported reward does not match independently scored emission")
    return True
