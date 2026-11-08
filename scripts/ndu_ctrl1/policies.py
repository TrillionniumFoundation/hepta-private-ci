"""Public-belief controllers with explicit, bounded computation charges.

Credits and seconds here are declared simulation prices. Measured process time
is retained separately and is never silently converted into those prices.
"""

import math
import time
from dataclasses import dataclass, replace

from ndu_real_runtime.objective import edge_value

from .model import backup, legal_actions, transitions


@dataclass(frozen=True)
class Decision:
    action: str
    cost: int
    duration: int
    expanded_nodes: int = 0
    forecast_calls: int = 0
    fallback: bool = False
    route: str = "fast"


def after_compute(state, decision):
    if (
        decision.cost < 0
        or decision.duration < 0
        or decision.cost > state.budget_left
        or decision.duration > state.time_left
    ):
        raise ValueError("Computation exceeds the admitted hard budget")
    return replace(
        state,
        budget_left=state.budget_left - decision.cost,
        time_left=state.time_left - decision.duration,
    )


class PlanningLimit(Exception):
    """The declared number of action forecasts has been consumed."""


class Search:
    """Depth-limited belief planning. Every action forecast consumes one node."""

    def __init__(self, scenario, profile, limit, representation="joint", owner=None):
        if not 1 <= limit <= 512 or representation not in ("joint", "mean"):
            raise ValueError("Unsupported planning limit or representation")
        self.scenario, self.profile = scenario, profile
        self.limit, self.representation = limit, representation
        self.nodes = 0
        self.legal_mask_calls = 0
        self.owner = owner
        self._values = {}
        self._qs = {}

    def q(self, state, action, depth):
        key = (state, action, depth)
        if key in self._qs:
            return self._qs[key]
        if self.nodes >= self.limit:
            raise PlanningLimit
        self.nodes += 1
        outcomes = transitions(self.scenario, state, action)
        continuations = [
            outcome.reward
            if outcome.next_state is None
            else self.value(outcome.next_state, depth - 1)
            for outcome in outcomes
        ]
        if self.representation == "joint":
            result = backup(outcomes, continuations, self.profile)
            self._qs[key] = result
            return result
        # A forecast ablation, not a change to the evaluation objective. Keep
        # visible posterior branches, but discard time/cost/return dependence.
        p = [float(outcome.probability) for outcome in outcomes]
        duration = math.fsum(
            mass * outcome.duration for mass, outcome in zip(p, outcomes)
        )
        cost = math.fsum(mass * outcome.cost for mass, outcome in zip(p, outcomes))
        result = -self.profile.resource_weight * cost + edge_value(
            duration,
            math.fsum(mass * value for mass, value in zip(p, continuations)),
            self.profile,
        )
        self._qs[key] = result
        return result

    def value(self, state, depth):
        key = (state, depth)
        if key not in self._values:
            # Forecast the same deterministic compute admission used online.
            # The truncated boundary is safe delivery, with its compute charge.
            charge = (
                self.owner.compute_charge(state)
                if self.owner is not None
                else Decision("stop", 0, 0)
            )
            admitted = after_compute(state, charge)
            if depth <= 0 or charge.route == "emergency_stop":
                continuation = self.scenario.stop_reward
            elif self.owner is not None and charge.route == "fast":
                continuation = self.q(
                    admitted, self.owner.fast_action(self.scenario, admitted), depth
                )
            else:
                self.legal_mask_calls += 1
                continuation = max(
                    self.q(admitted, action, depth)
                    for action in legal_actions(self.scenario, admitted)
                )
            self._values[key] = (
                -self.profile.resource_weight * charge.cost
                + edge_value(charge.duration, continuation, self.profile)
            )
        return self._values[key]


class Controller:
    """A frozen router. Parameter updates belong to the learning adapter."""

    KINDS = ("fixed", "fast", "voi", "mpc", "mean_mpc", "hybrid")

    def __init__(self, kind, profile, learner=None, node_limit=96):
        if kind not in self.KINDS or not 1 <= node_limit <= 512:
            raise ValueError("Unknown controller or unbounded planning request")
        if kind in ("fast", "hybrid") and learner is None:
            raise ValueError("A learned controller needs a frozen checkpoint")
        self.kind, self.profile, self.learner = kind, profile, learner
        self.node_limit = node_limit
        self.counters = {
            "calls": 0,
            "expanded_nodes": 0,
            "forecast_calls": 0,
            "fallbacks": 0,
            "legal_mask_calls": 0,
            "wall_ns": 0,
            "cpu_ns": 0,
        }

    def fast_action(self, scenario, state):
        self.counters["legal_mask_calls"] += 1
        legal = legal_actions(scenario, state)
        if self.learner is not None:
            self.counters["legal_mask_calls"] += 1
            action = self.learner.action(scenario, state)
            if action not in legal:
                raise ValueError("Learned action violates the public legal mask")
            return action
        # The fixed policy is intentionally untuned and consumes no forecasts.
        return "execute" if state.belief >= 0.75 and "execute" in legal else "stop"

    def choose(self, scenario, state):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        decision = self._choose(scenario, state)
        self.counters["wall_ns"] += time.perf_counter_ns() - wall
        self.counters["cpu_ns"] += time.process_time_ns() - cpu
        self.counters["calls"] += 1
        self.counters["expanded_nodes"] += decision.expanded_nodes
        self.counters["forecast_calls"] += decision.forecast_calls
        self.counters["fallbacks"] += int(decision.fallback)
        return decision

    def _choose(self, scenario, state):
        charge = self.compute_charge(state)
        if charge.route == "emergency_stop":
            return charge
        fast_state = after_compute(state, Decision("stop", 1, 0))
        fast = self.fast_action(scenario, fast_state)
        if charge.route == "fast":
            if self.kind == "voi" and state.used_mask:
                search = Search(scenario, self.profile, 2)
                self.counters["legal_mask_calls"] += 1
                choices = [
                    a
                    for a in legal_actions(scenario, fast_state)
                    if a in ("stop", "execute")
                ]
                action = max(choices, key=lambda a: search.q(fast_state, a, 1))
                return Decision(action, 1, 0, search.nodes, search.nodes)
            return replace(charge, action=fast)
        planned_state = after_compute(state, charge)
        fallback = self.fast_action(scenario, planned_state)
        search = Search(
            scenario,
            self.profile,
            self.node_limit,
            "mean" if self.kind == "mean_mpc" else "joint",
            self,
        )
        self.counters["legal_mask_calls"] += 1
        legal = legal_actions(scenario, planned_state)
        # VOI allows at most one information acquisition before a delivery.
        actions = (
            tuple(a for a in legal if a != "repair") if self.kind == "voi" else legal
        )
        if fallback not in actions:
            fallback = "stop"
        ordered = (fallback,) + tuple(a for a in actions if a != fallback)
        action, exhausted = fallback, False
        depths = (2,) if self.kind == "voi" else (1, 2, 3)
        for depth in depths:
            scores = {}
            try:
                for candidate in ordered:
                    scores[candidate] = (
                        self._voi_q(search, planned_state, candidate)
                        if self.kind == "voi"
                        else search.q(planned_state, candidate, depth)
                    )
            except PlanningLimit:
                exhausted = True
                break
            # Use only a completed comparison of every root action. If a
            # deeper iteration exhausts its cap, retain this completed depth.
            action = max(scores, key=scores.get)
        self.counters["legal_mask_calls"] += search.legal_mask_calls
        return Decision(
            action,
            charge.cost,
            1,
            search.nodes,
            search.nodes,
            exhausted,
            "slow",
        )

    def compute_charge(self, state):
        """Admission and fixed invocation price, shared by forecast and runtime.

        The reserved planning credits are a nonrefundable invocation price;
        actual expanded nodes and measured CPU are separately reported.
        """
        if state.steps_left <= 0 or state.budget_left < 1:
            return Decision("stop", 0, 0, route="emergency_stop")
        slow = self.kind not in ("fixed", "fast")
        if self.kind == "hybrid":
            slow = 0.25 <= float(state.belief) <= 0.75 and state.steps_left > 1
        if self.kind == "voi" and state.used_mask:
            slow = False
        reserve = math.ceil(self.node_limit / 32)
        if slow and state.budget_left >= 1 + reserve and state.time_left >= 1:
            return Decision("stop", 1 + reserve, 1, route="slow")
        return Decision("stop", 1, 0, fallback=slow)

    @staticmethod
    def _voi_q(search, state, action):
        if search.nodes >= search.limit:
            raise PlanningLimit
        search.nodes += 1
        outcomes = transitions(search.scenario, state, action)
        continuations = []
        for outcome in outcomes:
            if outcome.next_state is None:
                continuations.append(outcome.reward)
            else:
                search.legal_mask_calls += 1
                successor = outcome.next_state
                cost = int(successor.steps_left > 0 and successor.budget_left > 0)
                admitted = after_compute(successor, Decision("stop", cost, 0))
                choices = [
                    a
                    for a in legal_actions(search.scenario, admitted)
                    if a in ("stop", "execute")
                ]
                continuations.append(
                    -search.profile.resource_weight * cost
                    + max(search.q(admitted, a, 1) for a in choices)
                )
        return backup(outcomes, continuations, search.profile)
