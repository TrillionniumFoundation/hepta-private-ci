"""Budgeted finite-tree control of public neural rollout states.

Deterministic transitions and a conditional terminal forecast are the supported
model. Exhausting a finite tree proves optimality only under that forecast and
the reserved generation envelope; it is not a stochastic FBSDE certificate.
Work units are declared model-operation costs, not FLOPs or measured wall time.
Every hypothetical neural transition/forecast is charged, then execution is
charged separately. Metadata methods must not perform unmetered neural work.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import math
from typing import Any, Protocol


def _finite(value: float, name: str, *, positive: bool = False) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def entropic_value(values: Sequence[float], probabilities: Sequence[float], gamma: float) -> float:
    """Conditional lower entropic certainty equivalent, with stable small risk.

    The small-risk branch depends on gamma times payoff scale, not gamma alone.
    A centered expm1 remainder retains variance even for very small gamma.
    Probabilities must already represent the current state's conditional law.
    """
    gamma = _finite(gamma, "gamma")
    if len(values) == 0 or len(values) != len(probabilities):
        raise ValueError("nonempty equally sized scenarios and probabilities required")
    pairs = [(float(v), float(p)) for v, p in zip(values, probabilities)]
    if any(not math.isfinite(v) or not math.isfinite(p) or p < 0 for v, p in pairs):
        raise ValueError("finite payoffs and nonnegative finite probabilities required")
    total = math.fsum(p for _, p in pairs)
    if not math.isfinite(total) or abs(total - 1.0) > 1e-10:
        raise ValueError("conditional scenario probabilities must sum to one")
    pairs = [(v, p / total) for v, p in pairs if p > 0]
    lo, hi = min(v for v, _ in pairs), max(v for v, _ in pairs)
    scale = max(abs(lo), abs(hi))
    if scale == 0 or lo == hi:
        return lo
    mean_normalized = min(hi / scale, max(lo / scale,
                                         math.fsum(p * (v / scale) for v, p in pairs)))
    mean = mean_normalized * scale
    g = gamma * scale
    if gamma == 0 or g == 0:
        return mean
    if g < 0.125:
        remainders = []
        for v, p in pairs:
            z = -g * (v / scale - mean_normalized)
            # exp(z)-1-z; avoid cancellation of its quadratic leading term.
            rem = (z * z * (0.5 + z * (1 / 6 + z * (1 / 24 + z / 120)))
                   if abs(z) < 1e-4 else math.expm1(z) - z)
            remainders.append(p * rem)
        penalty = math.log1p(math.fsum(remainders)) / g * scale
        return min(mean, max(lo, mean - penalty))
    terms = []
    for v, p in pairs:
        gap = v - lo
        scaled_gap = gamma * gap if math.isfinite(gap) else gamma * v - gamma * lo
        terms.append(p * math.exp(-scaled_gap))
    value = lo - math.log(math.fsum(terms)) / gamma
    return min(mean, max(lo, value))


class Backend(Protocol):
    """Public-state adapter; no target or independent evaluator is exposed."""

    def actions(self, state: Any, content_control: bool) -> Sequence[str]: ...
    def transition(self, state: Any, action: str) -> Any: ...
    def predict(self, state: Any) -> tuple[Sequence[float], Sequence[float]]: ...
    def action_cost(self, state: Any, action: str) -> float: ...
    def prediction_cost(self, state: Any) -> float: ...
    def state_key(self, state: Any) -> str: ...
    def identity(self, state: Any) -> str: ...


@dataclass
class WorkBudget:
    limit: float
    stop_reserve: float
    initial_work: float = 0.0
    search_work: float = field(default=0.0, init=False)
    execution_work: float = field(default=0.0, init=False)
    stop_work: float = field(default=0.0, init=False)
    calls: dict[str, int] = field(default_factory=dict, init=False)
    finished: bool = field(default=False, init=False)

    def __post_init__(self):
        self.limit = _finite(self.limit, "limit", positive=True)
        self.stop_reserve = _finite(self.stop_reserve, "stop_reserve")
        self.initial_work = _finite(self.initial_work, "initial_work")
        if self.initial_work + self.stop_reserve > self.limit:
            raise ValueError("initial work and stop reserve exceed budget")

    @property
    def used(self) -> float:
        return math.fsum((self.initial_work, self.search_work, self.execution_work, self.stop_work))

    @property
    def available(self) -> float:
        return max(0.0, self.limit - self.used - (0.0 if self.finished else self.stop_reserve))

    def charge_search(self, kind: str, cost: float):
        cost = _finite(cost, "search cost", positive=True)
        if self.finished or cost > self.available:
            raise ValueError("search would consume stop reserve or exceed budget")
        self.search_work += cost
        self.calls[kind] = self.calls.get(kind, 0) + 1

    def charge_execution(self, cost: float):
        cost = _finite(cost, "execution cost", positive=True)
        if self.finished or cost > self.available:
            raise ValueError("execution would consume stop reserve or exceed budget")
        self.execution_work += cost
        self.calls["execution"] = self.calls.get("execution", 0) + 1

    def finish_stop(self, actual_cost: float):
        actual_cost = _finite(actual_cost, "stop cost")
        if self.finished or actual_cost > self.stop_reserve:
            raise ValueError("stop already completed or actual cost exceeds reserve")
        self.stop_work = actual_cost
        self.finished = True
        self.calls["stop"] = 1


@dataclass(frozen=True)
class ControllerConfig:
    policy: str = "risk_aware_recursive"
    horizon: int = 2
    gamma: float = 1.0
    cost_penalty: float = 0.0
    search_work_limit: float = 24.0
    search_fraction: float = 0.5
    router_work_cost: float = 1.0
    fixed_order: tuple[str, ...] = ("refine_semantic", "refine_image", "refine_text", "couple")

    def __post_init__(self):
        if self.policy not in {"fixed", "fixed_dev_tuned", "learned_router", "greedy",
                               "risk_neutral_mpc", "risk_aware_recursive", "allocation_only"}:
            raise ValueError("unknown controller policy")
        if not isinstance(self.horizon, int) or isinstance(self.horizon, bool) or self.horizon < 0:
            raise ValueError("horizon must be a nonnegative integer")
        for name in ("gamma", "cost_penalty", "search_work_limit", "search_fraction"):
            _finite(getattr(self, name), name)
        if self.search_fraction > 1:
            raise ValueError("search_fraction must be at most one")
        _finite(self.router_work_cost, "router_work_cost", positive=True)
        if not self.fixed_order:
            raise ValueError("fixed order must be nonempty")


@dataclass(frozen=True)
class Decision:
    action: str | None
    value: float | None
    complete: bool
    search_work: float
    search_calls: dict[str, int]
    generation_envelope: float
    search_envelope: float
    reason: str


class _SearchExhausted(Exception):
    pass


def _actions(backend: Backend, state: Any, content_control: bool):
    key, identity = backend.state_key(state), backend.identity(state)
    actions = tuple(backend.actions(state, content_control))
    if backend.state_key(state) != key or backend.identity(state) != identity:
        raise ValueError("actions mutated public state or identity")
    if len(set(actions)) != len(actions) or any(not isinstance(a, str) or not a for a in actions):
        raise ValueError("actions must be unique nonempty strings")
    return actions


class _Search:
    def __init__(self, backend, budget, config, cap):
        self.backend, self.budget, self.config, self.cap = backend, budget, config, cap
        self.started = budget.search_work
        self.gamma = 0.0 if config.policy in {"greedy", "risk_neutral_mpc"} else config.gamma

    def charge(self, kind, cost):
        cost = _finite(cost, kind + " cost", positive=True)
        if cost > self.cap - (self.budget.search_work - self.started):
            raise _SearchExhausted
        self.budget.charge_search(kind, cost)

    def node(self, state, depth, path_budget):
        key, identity = self.backend.state_key(state), self.backend.identity(state)
        self.charge("prediction", self.backend.prediction_cost(state))
        values, probabilities = self.backend.predict(state)
        if self.backend.state_key(state) != key or self.backend.identity(state) != identity:
            raise ValueError("prediction mutated public state or identity")
        best = entropic_value(values, probabilities, self.gamma)
        selected, complete = None, True
        if depth == 0:
            return best, selected, complete
        for action in _actions(self.backend, state, self.config.policy != "allocation_only"):
            cost = _finite(self.backend.action_cost(state, action), "action cost", positive=True)
            if cost > path_budget:
                continue
            try:
                self.charge("transition", cost)
                child = self.backend.transition(state, action)
                if self.backend.state_key(state) != key:
                    raise ValueError("transition mutated parent public state")
                if self.backend.identity(child) != identity:
                    raise ValueError("transition changed input, objective, or snapshot identity")
                value, _, child_complete = self.node(child, depth - 1, path_budget - cost)
                value -= self.config.cost_penalty * cost
                if value > best:
                    best, selected = value, action
                if not child_complete:
                    complete = False
                    break
            except _SearchExhausted:
                complete = False
                break
        return best, selected, complete


def choose(backend: Backend, state: Any, budget: WorkBudget, config: ControllerConfig,
           step_index: int = 0, router: Callable | None = None) -> Decision:
    """Choose only; caller charges and executes the selected action once more.

    Full search allowance is reserved before defining the generation envelope,
    so a searched path cannot spend hypothetical budget later consumed by search.
    Unspent allowance remains available to subsequent decisions. Stopping wins
    exact ties. Truncated search reports incomplete and never claims an oracle.
    """
    if budget.finished:
        raise ValueError("cannot control a finished episode")
    initial_key, initial_identity = backend.state_key(state), backend.identity(state)
    start, before = budget.search_work, dict(budget.calls)
    available = budget.available
    cap = min(config.search_work_limit, config.search_fraction * available)
    envelope = available - cap
    action, value, complete, reason = None, None, False, "no_search_budget"
    if config.policy in {"fixed", "fixed_dev_tuned", "learned_router"}:
        router_cost = config.router_work_cost if config.policy == "learned_router" else 0.0
        candidates = [a for a in _actions(backend, state, True)
                      if _finite(backend.action_cost(state, a), "action cost", positive=True)
                      + router_cost <= available]
        cap = min(router_cost, config.search_work_limit, available)
        envelope = max(0.0, available - cap)
        if config.policy == "learned_router" and candidates:
            if router is None:
                raise ValueError("learned_router requires a public-state router callback")
            if router_cost <= config.search_work_limit:
                key = backend.state_key(state)
                budget.charge_search("router", router_cost)
                action = router(state, tuple(candidates))
                if backend.state_key(state) != key or (action is not None and action not in candidates):
                    raise ValueError("router mutated state or returned an inadmissible action")
                reason = "router"
        elif candidates:
            order = config.fixed_order[step_index % len(config.fixed_order):] + config.fixed_order[:step_index % len(config.fixed_order)]
            action = next((a for a in order if a in candidates), None)
            reason = "fixed_schedule"
        else:
            reason = "budget_stop"
    else:
        search = _Search(backend, budget, config, cap)
        depth = 1 if config.policy == "greedy" else config.horizon
        try:
            value, action, complete = search.node(state, depth, envelope)
            reason = "finite_tree_complete" if complete else "search_truncated"
        except _SearchExhausted:
            reason = "search_truncated_before_forecast"
    if action is not None and _finite(backend.action_cost(state, action), "selected action cost", positive=True) > budget.available:
        raise ValueError("selected action no longer fits actual remaining budget")
    if backend.state_key(state) != initial_key or backend.identity(state) != initial_identity:
        raise ValueError("controller metadata or router changed public state or identity")
    calls = {k: n - before.get(k, 0) for k, n in budget.calls.items() if n != before.get(k, 0)}
    return Decision(action, value, complete, budget.search_work - start, calls, envelope, cap, reason)
