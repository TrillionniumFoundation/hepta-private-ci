"""Shared calibrated beliefs with distinctly typed stopping policy scores."""

import math
import hashlib
import json
import time

import torch
from torch.nn import functional as F

from experiments.continuous_spiking_network.boundary import (
    FiniteHorizonStoppingBoundary,
    StoppingPolicy,
)
from experiments.continuous_spiking_network.boundary_study import (
    fit_direct,
    select_fixed,
)


def fit_temperature(odds, labels, updates=100):
    raw = torch.nn.Parameter(torch.tensor(0.0))
    optimizer = torch.optim.Adam([raw], lr=0.03)
    target = labels[:, None].expand_as(odds).float()
    history = []
    for _ in range(updates):
        optimizer.zero_grad(set_to_none=True)
        temperature = raw.exp().clamp(0.25, 4.0)
        loss = F.binary_cross_entropy_with_logits(odds.detach() / temperature, target)
        loss.backward()
        optimizer.step()
        history.append(float(loss.detach()))
    return float(raw.detach().exp().clamp(0.25, 4.0)), history


class OnlinePolicies:
    """All primary policies receive the same temperature-adjusted actor odds.

    A threshold/confidence margin is a policy score, not a continuation value.
    Only the Bellman arm exposes model-derived stopping/continuation utilities.
    """

    def __init__(self, temperature, fixed_threshold, direct_parameters):
        self.temperature = float(temperature)
        self.fixed_threshold = float(fixed_threshold)
        self.direct = StoppingPolicy("direct", threshold=0.85)
        with torch.no_grad():
            for name, parameter in self.direct.named_parameters():
                parameter.copy_(torch.as_tensor(direct_parameters[name]))
        self.direct.eval()
        self.solver = FiniteHorizonStoppingBoundary(grid_size=257).double()
        self.tables = {}
        self.table_build_cpu_seconds = 0.0

    @property
    def identity(self):
        value = {
            "temperature": self.temperature,
            "fixed_threshold": self.fixed_threshold,
            "direct": {
                name: parameter.detach().tolist()
                for name, parameter in self.direct.named_parameters()
            },
            "solver_grid": self.solver.grid.tolist(),
            "transition": "known Gaussian observation log-likelihood increments",
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    @classmethod
    def fit(cls, train_odds, validation_odds, train, validation):
        start = time.process_time(), time.perf_counter()
        temperature, history = fit_temperature(train_odds, train["label"])
        temperature_cpu = time.process_time() - start[0]
        cpu = time.process_time()
        threshold, fixed = select_fixed(validation_odds / temperature, validation)
        fixed_cpu = time.process_time() - cpu
        cpu = time.process_time()
        _, direct = fit_direct(train_odds / temperature, train, updates=100)
        direct_cpu = time.process_time() - cpu
        instance = cls(temperature, threshold, direct["parameters"])
        receipt = {
            "temperature": temperature,
            "temperature_updates": 100,
            "temperature_bounds": [0.25, 4.0],
            "temperature_train_ce": history,
            "fixed": fixed,
            "direct": direct,
            "temperature_cpu_seconds": temperature_cpu,
            "fixed_selection_cpu_seconds": fixed_cpu,
            "direct_training_cpu_seconds": direct_cpu,
            "total_cpu_seconds": time.process_time() - start[0],
            "total_wall_seconds": time.perf_counter() - start[1],
            "data_scope": "temperature/direct fit use training only; fixed uses validation utility; no heldout outcome is consumed",
        }
        return instance, receipt

    def precompute(self, snrs, costs, horizon):
        for snr, cost in sorted(set(zip(snrs, costs, strict=True))):
            key = (float(snr), float(cost), int(horizon))
            if key not in self.tables:
                cpu = time.process_time()
                self.tables[key] = self.solver.table(
                    torch.tensor([snr], dtype=torch.float64),
                    torch.tensor([cost], dtype=torch.float64),
                    horizon - 1,
                )
                self.table_build_cpu_seconds += time.process_time() - cpu

    @torch.inference_mode()
    def decide(self, mode, raw_log_odds, snr, cost, remaining, horizon):
        if mode not in {"fixed", "direct", "value", "full"}:
            raise ValueError("unknown stopping mode")
        if remaining < 0 or remaining >= horizon:
            raise ValueError("remaining horizon is invalid")
        odds = torch.tensor(float(raw_log_odds) / self.temperature, dtype=torch.float64)
        confidence = float(odds.abs().sigmoid())
        forced = remaining == 0
        genuine_stop, genuine_continue = None, None
        if mode == "value":
            genuine_stop = confidence
            if forced:
                advantage = 1.0
            else:
                result = self.solver.evaluate(
                    odds.reshape(1),
                    torch.tensor([remaining]),
                    self.tables[(float(snr), float(cost), int(horizon))],
                )
                genuine_continue = float(result["wait_value"][0])
                advantage = confidence - genuine_continue
            kind = "value_model_advantage"
        elif mode == "full":
            advantage = 1.0 if forced else -1.0
            kind = "fixed_horizon_constraint"
        else:
            if mode == "fixed":
                threshold = self.fixed_threshold
            else:
                values = self.direct(
                    odds.float().reshape(1),
                    torch.tensor([remaining]),
                    torch.tensor([snr]),
                    torch.tensor([cost]),
                )
                threshold = float(values["threshold"][0])
            advantage = 1.0 if forced else confidence - threshold
            kind = "threshold_confidence_advantage"
        if not math.isfinite(advantage):
            raise ValueError("action score must be finite")
        return {
            "stop": forced or advantage >= 0,
            "continue_score": -advantage,
            "score_kind": kind,
            "forced_terminal": forced,
            "stopping_value": genuine_stop,
            "continuation_value": genuine_continue,
            "confidence": confidence,
            "predicted_error_probability": 1 - confidence,
            "calibrated_log_odds": float(odds),
        }
