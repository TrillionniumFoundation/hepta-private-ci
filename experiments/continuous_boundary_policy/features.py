"""Causal, information-matched task features; no policy outcomes enter inputs."""

import numpy as np

from experiments.first_passage_cell.kernels import first_passage
from experiments.continuous_boundary_flow.models import boundary_features
from experiments.continuous_boundary_flow.native.adapter import (
    features as native_features,
)
from .common import FEATURE_NAMES

FULL = {"dual_flow", "generic_gru", "dual_event", "elman_mlp", "native_sparse"}


class FeatureMap:
    def __init__(self, context, arm, candidate, boundary_weights=None):
        self.model, self.dp = context["model"], context["dp"]
        self.spec, self.arm = self.model.spec, arm
        self.fixed = candidate["fixed_boundary"]
        self.weights = (
            None if boundary_weights is None else np.asarray(boundary_weights)
        )
        if arm == "learned_margin" and (
            self.weights is None or self.weights.shape != (20,)
        ):
            raise ValueError("Missing training-only boundary coefficients")
        self.boundaries = None
        if arm not in {"fixed_margin", "learned_margin"}:
            records = self.dp["boundaries"]
            if any(
                row["boundary"] is None or not row["threshold_shape"] for row in records
            ):
                raise ValueError("Declared threshold-shaped domain was violated")
            self.boundaries = np.asarray([row["boundary"] for row in records])
        self.call = self.put = self.risk = None
        if arm in FULL or arm == "value_call":
            fp = first_passage(
                self.model.x,
                self.spec.mu,
                self.spec.sigma,
                self.spec.dt,
                self.spec.discount,
            )
            self.put = self.spec.failure_cost * fp["H"]
            self.call = np.asarray(self.dp["q_keep"]) + self.put[None, :]
            self.risk = fp["F"]

    def step(self, states, remaining, previous_failed, previous_risk, previous_repair):
        states = np.asarray(states, dtype=int)
        n = len(states)
        if (
            not 1 <= remaining <= self.spec.horizon
            or np.any(states < -1)
            or np.any(states >= self.model.n_states)
        ):
            raise ValueError("Invalid causal state/deadline")
        pf, pr, pa = [
            np.asarray(v, dtype=float)
            for v in (previous_failed, previous_risk, previous_repair)
        ]
        if any(
            v.shape != states.shape
            or not np.isfinite(v).all()
            or np.any(v < 0)
            or np.any(v > 1)
            for v in (pf, pr, pa)
        ):
            raise ValueError("Invalid causal history")
        safe, active = np.maximum(states, 0), states >= 0
        x, s = self.model.x[safe], self.spec
        if self.arm == "fixed_margin":
            boundary = self.fixed
        elif self.arm == "learned_margin":
            boundary = float(
                np.clip(
                    boundary_features(s, remaining) @ self.weights, 0, self.model.x[-1]
                )
            )
        else:
            boundary = self.boundaries[remaining - 1]
        margin = np.clip((x - boundary) / (s.sigma * np.sqrt(s.dt)), -4, 4)
        scale = 1 + remaining * s.dt * s.production_rate
        c = (
            self.call[remaining - 1, safe] / scale
            if self.call is not None
            else np.zeros(n)
        )
        p = self.put[safe] / scale if self.arm in FULL else np.zeros(n)
        f = self.risk[safe] if self.arm in FULL else np.zeros(n)
        const = lambda value: np.full(n, value)
        values = np.column_stack(
            (
                x / 2,
                const(remaining / 16),
                const(s.mu / 0.6),
                const(s.sigma / 0.6),
                const(s.maintenance_cost),
                const(s.failure_cost / 6),
                const(s.production_rate / 1.5),
                const(s.discount / 0.2),
                const(s.maintenance_reset / 2),
                const(s.failure_reset / 2),
                const(s.dt),
                margin,
                c,
                p,
                f,
                pr / s.dt,
                pf,
                pa,
            )
        )
        values = np.clip(values, -4, 4)
        values[~active] = 0
        reset = pf.copy() if self.arm == "dual_event" else pr.copy()
        if self.arm in {"elman_mlp", "native_sparse"}:
            reset[:] = 0
        reset[~active] = 0
        if values.shape != (n, len(FEATURE_NAMES)) or not np.isfinite(values).all():
            raise ValueError("Invalid feature shape/domain")
        return values, reset


def native_rows(values):
    """17 raw plus typed margin/risk/flow: all18 input values, two duplicates."""
    out = []
    for x in values:
        raw = np.r_[x[:15], x[16:18]]
        out.append(native_features(raw, margin=x[11], risk=x[14], flow=x[15]))
    return out


def training_arrays(contexts, histories, arm, candidate, boundary_weights=None):
    all_x, all_reset, all_q = [], [], []
    for context, history in zip(contexts, histories):
        mapping = FeatureMap(context, arm, candidate, boundary_weights)
        xs, resets, qs = [], [], []
        previous_repair = np.zeros(len(history[0]["states"]))
        for row in history:
            x, reset = mapping.step(
                row["states"],
                row["remaining"],
                row["previous_failed"],
                row["previous_risk"],
                previous_repair,
            )
            xs.append(x)
            resets.append(reset)
            qs.append(np.column_stack((row["target_q"] * 8, np.zeros(len(x)))))
            previous_repair = (row["actions"] == 1).astype(float)
        all_x.append(np.asarray(xs))
        all_reset.append(np.asarray(resets))
        all_q.append(np.asarray(qs))
    return (
        np.concatenate(all_x, axis=1),
        np.concatenate(all_reset, axis=1),
        np.concatenate(all_q, axis=1),
    )
