"""Deployable controls over learned public-state forecasts, never future labels.

All controls receive the same current features, legal actions and frozen fitted
predictor. NDU uses a bounded nested entropic backup; MPC selects a bounded
open-loop plan and replans after the next real observation. Forecasts must come
from a fitted model, not a lookup of later evaluation outcomes.
"""

from dataclasses import dataclass
import itertools
import math
import random

from .objective import MEMORY_MODES, certainty_equivalent, edge_value, forecast_seed

ACTIONS = ("PREPARE_ROI", "READ_ROI", "WRITE_TEXT", "RENDER_IMAGE", "STOP")


@dataclass(frozen=True)
class ControlPlan:
    risk: float = 0.25
    discount_per_second: float = 1.0
    latency_weight: float = 0.01
    horizon: int = 3
    max_forecasts: int = 96
    max_sequences: int = 24
    particles: int = 4
    memory_mode: str = "reset"

    def __post_init__(self):
        values = (self.risk, self.discount_per_second, self.latency_weight)
        if (
            not all(type(x) in (int, float) and math.isfinite(x) for x in values)
            or min(self.risk, self.latency_weight) < 0
        ):
            raise ValueError("Nonfinite or negative control objective")
        if self.memory_mode not in MEMORY_MODES:
            raise ValueError("Unknown episode memory profile")
        if not 0 < self.discount_per_second <= 1:
            raise ValueError("Invalid duration discount")
        for name, lower, upper in (
            ("horizon", 1, 4),
            ("max_forecasts", 1, 512),
            ("max_sequences", 1, 128),
            ("particles", 1, 8),
        ):
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"Invalid bounded planner {name}")


@dataclass(frozen=True)
class PublicState:
    features: tuple
    remaining_seconds: float
    step: int
    legal_actions: tuple

    def __post_init__(self):
        if not self.features or len(self.features) > 4096:
            raise ValueError("Invalid public feature width")
        if not all(type(x) in (float, int) and math.isfinite(x) for x in self.features):
            raise ValueError("Only finite numerical public features are accepted")
        if not math.isfinite(self.remaining_seconds) or self.remaining_seconds < 0:
            raise ValueError("Invalid remaining wall budget")
        if type(self.step) is not int or self.step < 0:
            raise ValueError("Invalid step")
        if (
            not self.legal_actions
            or len(set(self.legal_actions)) != len(self.legal_actions)
            or set(self.legal_actions) - set(ACTIONS)
            or "STOP" not in self.legal_actions
        ):
            raise ValueError("Invalid legal action set")

    @classmethod
    def from_wire(cls, value):
        if set(value) != {"features", "remaining_seconds", "step", "legal_actions"}:
            raise ValueError(
                "Only current public-state fields may cross the control API"
            )
        return cls(
            tuple(value["features"]),
            value["remaining_seconds"],
            value["step"],
            tuple(value["legal_actions"]),
        )


@dataclass(frozen=True)
class Forecast:
    next_features: tuple
    utility: float
    duration_seconds: float
    probability: float
    legal_actions: tuple


class Controller:
    """Bounded control policy; predictor is a separately pinned neural runtime.

    predictor.utility(state) and predictor.forecast(state, action, n, seed)
    operate on public feature vectors only. Training targets are absent from
    this deployment interface. The owner meters all calls and invokes actions.
    """

    def __init__(self, kind, predictor, plan, *, fixed_schedule=(), seed=0):
        if kind not in {
            "light",
            "ndu",
            "ndu_policy",
            "initial",
            "tuned_fixed",
            "voi",
            "mpc",
        }:
            raise ValueError("Unknown deployable controller")
        if set(fixed_schedule) - (set(ACTIONS) - {"STOP"}):
            raise ValueError("Invalid fixed schedule")
        self.kind, self.predictor, self.plan = kind, predictor, plan
        self.fixed_schedule, self.seed = tuple(fixed_schedule), seed
        self.calls, self.exhausted, self.cache = 0, False, {}
        self.call_limit = self.plan.max_forecasts

    def _forecast(self, state, action):
        key = (state, action)
        # NDU expands each branch under the same counted-work convention as
        # its differentiable unroll. Equal feature values can have different
        # input Jacobians and must not alias one autograd graph. Open-loop MPC
        # retains its explicit shared-prefix cache.
        if self.kind == "mpc" and key in self.cache:
            return self.cache[key]
        if self.calls >= self.call_limit:
            self.exhausted = True
            return ()
        self.calls += 1
        seed = forecast_seed(self.seed, state.step, action)
        rows = tuple(self.predictor.forecast(state, action, self.plan.particles, seed))
        if not rows or len(rows) > self.plan.particles:
            raise ValueError("Predictor exceeds the locked particle budget")
        probabilities = []
        for row in rows:
            if (
                not isinstance(row, Forecast)
                or not 0 <= row.utility <= 1
                or not math.isfinite(row.utility)
                or not math.isfinite(row.duration_seconds)
                or row.duration_seconds <= 0
                or not math.isfinite(row.probability)
                or row.probability < 0
                or len(row.next_features) != len(state.features)
            ):
                raise ValueError("Malformed learned transition")
            PublicState(
                row.next_features,
                max(0.0, state.remaining_seconds - row.duration_seconds),
                state.step + 1,
                row.legal_actions,
            )
            probabilities.append(row.probability)
        if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-9):
            raise ValueError("Predicted probabilities do not sum to one")
        self.cache[key] = rows
        return rows

    def _terminal(self, state):
        value = float(self.predictor.utility(state))
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Invalid learned terminal utility")
        return value

    def _successor(self, state, row):
        return PublicState(
            row.next_features,
            max(0.0, state.remaining_seconds - row.duration_seconds),
            state.step + 1,
            row.legal_actions,
        )

    def _edge(self, row, future):
        return edge_value(row.duration_seconds, future, self.plan)

    def _ndu_value(self, state, depth):
        best = self._terminal(state)
        if depth == 0 or state.remaining_seconds <= 0:
            return best
        for action in state.legal_actions:
            if action == "STOP":
                continue
            rows = self._forecast(state, action)
            if not rows or any(
                r.duration_seconds > state.remaining_seconds for r in rows
            ):
                continue
            values = [
                self._edge(row, self._ndu_value(self._successor(state, row), depth - 1))
                for row in rows
            ]
            best = max(
                best,
                certainty_equivalent(
                    values, [r.probability for r in rows], self.plan.risk
                ),
            )
        return best

    def _open_loop(self, state, sequence):
        if not sequence or sequence[0] == "STOP":
            return self._terminal(state)
        action = sequence[0]
        if action not in state.legal_actions:
            return self._terminal(state)
        rows = self._forecast(state, action)
        if not rows or any(r.duration_seconds > state.remaining_seconds for r in rows):
            return self._terminal(state)
        values = [
            self._edge(row, self._open_loop(self._successor(state, row), sequence[1:]))
            for row in rows
        ]
        return certainty_equivalent(
            values, [r.probability for r in rows], self.plan.risk
        )

    def choose(self, state):
        if not isinstance(state, PublicState):
            raise TypeError("A checked PublicState is required")
        self.calls, self.exhausted, self.cache = 0, False, {}
        self.call_limit = self.plan.max_forecasts
        if self.kind == "initial" or state.remaining_seconds == 0:
            return "STOP", {"forecast_calls": 0, "planner_budget_exhausted": False}
        if self.kind == "tuned_fixed":
            action = (
                self.fixed_schedule[state.step]
                if state.step < len(self.fixed_schedule)
                else "STOP"
            )
            return (action if action in state.legal_actions else "STOP"), {
                "forecast_calls": 0,
                "planner_budget_exhausted": False,
            }
        if self.kind in {"light", "ndu_policy"}:
            logits = dict(self.predictor.light_scores(state))
            if set(logits) != set(state.legal_actions) or not all(
                math.isfinite(x) for x in logits.values()
            ):
                raise ValueError("Light router produced invalid legal logits")
            action = max(state.legal_actions, key=lambda name: logits[name])
            if self.kind == "ndu_policy":
                roots = [name for name in state.legal_actions if name != "STOP"]
                eligible = ["STOP"]
                if len(roots) <= self.plan.max_forecasts:
                    for name in roots:
                        predictions = self._forecast(state, name)
                        if predictions and all(
                            row.duration_seconds <= state.remaining_seconds
                            for row in predictions
                        ):
                            eligible.append(name)
                else:
                    self.exhausted = True
                maximum = max(logits[name] for name in eligible)
                weights = [math.exp(logits[name] - maximum) for name in eligible]
                probabilities = [value / sum(weights) for value in weights]
                generator = random.Random(
                    forecast_seed(self.seed, state.step, "POLICY")
                )
                action = generator.choices(eligible, weights=probabilities, k=1)[0]
                return action, {
                    "forecast_calls": self.calls,
                    "planner_budget_exhausted": self.exhausted,
                    "policy_profile": "exact_frozen_recursive_Q_improvement",
                    "policy_probabilities": dict(zip(eligible, probabilities)),
                    "selected_action_probability": probabilities[
                        eligible.index(action)
                    ],
                    "prediction_is_external_evidence": False,
                }
            return action, {
                "forecast_calls": 0,
                "planner_budget_exhausted": False,
                "policy_profile": "observed_action_values",
            }
        scores = {"STOP": self._terminal(state)}
        if self.kind == "mpc":
            # Every continuation is considered at depth one before spending the
            # remaining budget on longer plans; lexical order cannot erase a root.
            roots = [a for a in state.legal_actions if a != "STOP"]
            sequences = [(a,) for a in roots]
            for length in range(2, self.plan.horizon + 1):
                suffixes = itertools.product(
                    [a for a in ACTIONS if a != "STOP"], repeat=length - 1
                )
                for suffix in suffixes:
                    for root in roots:
                        if len(sequences) >= self.plan.max_sequences:
                            break
                        sequences.append((root, *suffix))
                    if len(sequences) >= self.plan.max_sequences:
                        break
            if len(roots) > self.plan.max_forecasts:
                return "STOP", {"forecast_calls": 0, "planner_budget_exhausted": True}
            for root in roots:
                self._forecast(state, root)
            extra = self.plan.max_forecasts - self.calls
            for index, root in enumerate(roots):
                self.call_limit = (
                    self.calls
                    + extra // max(1, len(roots))
                    + int(index < extra % max(1, len(roots)))
                )
                for sequence in sequences[: self.plan.max_sequences]:
                    if sequence[0] == root:
                        scores[root] = max(
                            scores.get(root, -math.inf),
                            self._open_loop(state, sequence),
                        )
            self.call_limit = self.plan.max_forecasts
        else:
            actions = [name for name in state.legal_actions if name != "STOP"]
            # Reserve one query for every root before exploring descendants.
            # Deeper work is divided across roots so lexical order cannot spend
            # the entire planner allowance before another action is considered.
            if len(actions) > self.plan.max_forecasts:
                return "STOP", {"forecast_calls": 0, "planner_budget_exhausted": True}
            roots = {action: self._forecast(state, action) for action in actions}
            extra = self.plan.max_forecasts - self.calls
            for index, action in enumerate(actions):
                rows = roots[action]
                if not rows or any(
                    r.duration_seconds > state.remaining_seconds for r in rows
                ):
                    continue
                self.call_limit = (
                    self.calls
                    + extra // max(1, len(actions))
                    + int(index < extra % max(1, len(actions)))
                )
                if self.kind == "voi":
                    values = [self._edge(row, row.utility) for row in rows]
                else:
                    values = [
                        self._edge(
                            row,
                            self._ndu_value(
                                self._successor(state, row), self.plan.horizon - 1
                            ),
                        )
                        for row in rows
                    ]
                scores[action] = certainty_equivalent(
                    values, [r.probability for r in rows], self.plan.risk
                )
            self.call_limit = self.plan.max_forecasts
        # The caller also records elapsed planner/critic work, including a cap hit.
        action = max(scores, key=scores.get)
        return action, {
            "forecast_calls": self.calls,
            "planner_budget_exhausted": self.exhausted,
            "predicted_values": scores,
            "prediction_is_external_evidence": False,
        }
