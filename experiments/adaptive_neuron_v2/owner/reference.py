"""Independent Python stopping, spiking and resource-account reconstruction."""

import math

import numpy as np

from experiments.adaptive_neuron_v2.learning.network import initial_state, step


class Reference:
    def __init__(self, model, context, policy, initial):
        self.model, self.context, self.policy = model, context, policy
        self.settings = model["credit"]
        self.initial = dict(initial)
        self.balance = initial["balance"]
        self.work = 0.0
        self.spikes = 0
        self.cells = 0
        self.elapsed = 0
        self.raw_logit = 0.0
        self.state = initial_state()
        self.price = {
            "off": 0.0,
            "frozen": self.settings["frozen_price"],
            "live": initial["price"],
        }[policy["credit"]]
        self.grid = np.linspace(0, 1, model["grid_points"])
        reliability, cost, horizon = context
        self.effective_cost = cost + self.price * self.settings["quote"]
        chance = reliability * self.grid + (1 - reliability) * (1 - self.grid)
        plus = reliability * self.grid / chance
        minus = (1 - reliability) * self.grid / (1 - chance)
        immediate = np.maximum(np.abs(2 * self.grid - 1), 0.05)
        value = immediate.copy()
        self.continuation = [np.full_like(self.grid, -1)]
        for _ in range(1, 2 if policy["readout"] == "raw_belief_myopic" else horizon):
            wait = -self.effective_cost + chance * np.interp(plus, self.grid, value)
            wait += (1 - chance) * np.interp(minus, self.grid, value)
            self.continuation.append(wait)
            value = np.maximum(immediate, wait)

    def observe(self, observation):
        r, cost, horizon = self.context
        if self.balance + 1e-12 < self.settings["quote"]:
            raise ValueError("unreserved reference observation")
        self.elapsed += 1
        self.raw_logit += observation * math.log(r / (1 - r))
        if self.policy["readout"] == "snn":
            self.state, record = step(
                self.model["neural"],
                self.state,
                observation,
                r,
                cost,
                horizon,
                self.elapsed,
                thresholds=self.model["neural"]["thresholds"],
            )
            logit, spikes, cells = record["logit"], record["spikes"], 8
        else:
            logit, spikes, cells = self.raw_logit, 0, 0
        p = (
            1 / (1 + math.exp(-logit))
            if logit >= 0
            else math.exp(logit) / (1 + math.exp(logit))
        )
        immediate = abs(2 * p - 1)
        remaining = horizon - self.elapsed
        t = 1 if self.policy["readout"] == "raw_belief_myopic" else remaining
        continuation = (
            float(np.interp(p, self.grid, self.continuation[t])) if remaining else -1.0
        )
        if immediate >= 0.05 and (not remaining or immediate >= continuation):
            action = "positive" if logit > 0 else "negative"
        elif not remaining or 0.05 >= continuation:
            action = "abstain"
        else:
            action = "continue"
        work = 1 + spikes / 8
        self.balance -= work
        self.work += work
        self.spikes += spikes
        self.cells += cells
        forced = action == "continue" and self.balance + 1e-12 < self.settings["quote"]
        if forced:
            action = "abstain"
        return {
            "action": action,
            "logit": logit,
            "immediate": immediate,
            "continuation": continuation,
            "used_price": self.price,
            "effective_cost": self.effective_cost,
            "spikes": spikes,
            "actual_snn_cell_updates": cells,
            "actual_work": work,
            "budget_forced_abstention": forced,
            "state_after": {
                "neural": {
                    **self.state,
                    "raw_logit": self.raw_logit,
                    "elapsed": self.elapsed,
                },
                "balance": self.balance,
                "work": self.work,
                "spikes": self.spikes,
                "cell_updates": self.cells,
            },
        }

    def settle(self, budget, reward):
        return {
            "balance": min(
                self.settings["balance_cap"],
                self.initial["balance"]
                - self.work
                + budget
                + self.settings["kappa"] * reward,
            ),
            "price": float(
                np.clip(
                    self.initial["price"]
                    + self.settings["eta"]
                    * (self.work - budget - self.settings["kappa"] * reward),
                    0,
                    self.settings["pmax"],
                )
            ),
        }


def compare(actual, expected, *, path="readout", tolerance=2e-10):
    """Exact actions/counters and bounded independent floating-point differences."""
    if isinstance(expected, dict):
        for key, value in expected.items():
            compare(actual[key], value, path=f"{path}.{key}", tolerance=tolerance)
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise AssertionError(f"shape mismatch: {path}")
        for index, (left, right) in enumerate(zip(actual, expected)):
            compare(left, right, path=f"{path}[{index}]", tolerance=tolerance)
    elif isinstance(expected, float):
        if not math.isfinite(actual) or abs(actual - expected) > tolerance * max(
            1, abs(expected)
        ):
            raise AssertionError(f"numeric mismatch: {path}: {actual} != {expected}")
    elif actual != expected:
        raise AssertionError(f"discrete mismatch: {path}: {actual} != {expected}")
