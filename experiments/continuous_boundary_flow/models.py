"""Causal input adapters for a shared native sparse encoder and learned head.

Every arm emits the same 17 raw features. The external native sparse encoder
and 42-parameter linear wait/repair head with a literal-zero stop head are unchanged. These adapters have six
bounded state variables (none retained by native_sparse), fixed coefficients
selected on development data, and no claim of full-parameter BPTT.

Boundary and channel panels are deliberately separate. fixed_margin and
learned_margin read no DP values or boundaries at execution. value_margin adds
only the model-derived boundary. value_call adds C, and value_dual adds P and
current risk. C is production plus reset-aware continuation; P is discounted
physical failure loss, not the action gap or an independent financial option.

The common typed flow is PREVIOUS action risk / dt. Using current F/dt here
would leak current risk into the nominally risk-masked ablations. event_reset
uses the previous observed failure in its internal reset/trace; continuous
arms use the previous conditional failure probability. That state expectation
is an adapter approximation, not an assertion that nonlinear path dynamics
commute with taking expectations.
"""

from collections.abc import Mapping

import numpy as np

from experiments.first_passage_cell.kernels import first_passage
from experiments.continuous_boundary_flow.math_model import solve_dp


ARMS = (
    "fixed_margin",
    "learned_margin",
    "value_margin",
    "value_call",
    "value_dual",
    "generic_gate",
    "native_sparse",
    "event_reset",
    "dense_recurrent",
)
FEATURE_NAMES = (
    "x_scaled",
    "remaining_windows_scaled",
    "mu_scaled",
    "sigma_scaled",
    "maintenance_cost",
    "failure_cost_scaled",
    "production_scaled",
    "discount_scaled",
    "maintenance_reset_scaled",
    "failure_reset_scaled",
    "window_dt",
    "state_margin",
    "state_call",
    "state_put",
    "state_risk",
    "state_flow",
    "state_drive",
)
BOUNDARY_FEATURE_NAMES = (
    "intercept",
    "remaining_windows_scaled",
    "time_scaled",
    "mu_scaled",
    "sigma_scaled",
    "maintenance_cost",
    "failure_cost_scaled",
    "production_scaled",
    "discount_scaled",
    "maintenance_reset_scaled",
    "failure_reset_scaled",
    "dt",
    "sigma_squared",
    "mu_sigma",
    "cost_sigma",
    "cost_loss_ratio",
    "time_sigma",
    "time_mu",
    "time_cost",
    "time_squared",
)
_FULL = {
    "value_dual",
    "generic_gate",
    "native_sparse",
    "event_reset",
    "dense_recurrent",
}
_VALUE_BOUNDARY = set(ARMS) - {"fixed_margin", "learned_margin"}


def boundary_features(spec, remaining):
    """Twenty public task/deadline features; never current state or test labels."""
    rem = np.asarray(remaining, dtype=float)
    scalar = rem.ndim == 0
    rem = np.atleast_1d(rem)
    if not np.isfinite(rem).all() or np.any(rem < 1) or np.any(rem > spec.horizon):
        raise ValueError("Remaining horizon outside the declared task")
    mu, sigma, time = spec.mu / 0.6, spec.sigma / 0.6, rem * spec.dt / 8
    constant = lambda value: np.full(rem.shape, value, dtype=float)
    cols = [
        constant(1),
        rem / 16.0,
        time,
        constant(mu),
        constant(sigma),
        constant(spec.maintenance_cost),
        constant(spec.failure_cost / 6),
        constant(spec.production_rate / 1.5),
        constant(spec.discount / 0.2),
        constant(spec.maintenance_reset / 2),
        constant(spec.failure_reset / 2),
        constant(spec.dt),
        constant(sigma**2),
        constant(mu * sigma),
        constant(spec.maintenance_cost * sigma),
        constant(spec.maintenance_cost / (1 + spec.failure_cost)),
        time * sigma,
        time * mu,
        time * spec.maintenance_cost,
        time**2,
    ]
    out = np.stack(cols, axis=-1)
    return out[0] if scalar else out


def fit_boundary(training_models, ridge=1e-3):
    """Fit a direct boundary regressor using training task models only.

    Each entry can be a GridModel, (GridModel, dp_result), or a dict containing
    model and dp. Training targets are public-model Bellman boundaries; this
    is explicitly teacher-assisted supervised fitting, not reward-only RL.
    The returned 20 coefficients count in addition to the external head.
    """
    features, targets, task_count, skipped = [], [], 0, 0
    for item in training_models:
        if isinstance(item, Mapping):
            model, dp = item["model"], item["dp"]
        elif isinstance(item, tuple):
            model, dp = item
        else:
            model, dp = item, solve_dp(item)
        task_count += 1
        for remaining, record in enumerate(dp["boundaries"], 1):
            boundary = record["boundary"]
            if boundary is None or not record["threshold_shape"]:
                skipped += 1
                continue
            features.append(boundary_features(model.spec, remaining))
            targets.append(boundary)
    if not targets or ridge < 0:
        raise ValueError("Finite training boundaries and nonnegative ridge required")
    design, target = np.asarray(features), np.asarray(targets)
    regularizer = ridge * np.eye(design.shape[1])
    regularizer[0, 0] = 0
    weights = np.linalg.lstsq(
        design.T @ design + regularizer, design.T @ target, rcond=None
    )[0]
    error = design @ weights - target
    return {
        "weights": weights,
        "feature_names": BOUNDARY_FEATURE_NAMES,
        "training_tasks": task_count,
        "training_rows": len(targets),
        "skipped_non_threshold_rows": skipped,
        "ridge": ridge,
        "training_rmse": float(np.sqrt(np.mean(error**2))),
        "training_max_abs_error": float(np.max(np.abs(error))),
        "boundary_parameter_count": int(weights.size),
        "target": "training-only public-model Bellman maintenance boundary",
    }


class ActorAdapter:
    """Stateful batch adapter; remaining indexes DP at remaining-1.

    The batch size is stable for a trajectory. Stopped rows use state index -1,
    are masked to zero, and have their adapter state cleared. Call reset before
    a new batch or use reset(mask=...) when recycling individual case slots.
    """

    def __init__(self, spec, dp, arm, candidate, seed, boundary_weights=None):
        if arm not in ARMS:
            raise ValueError(f"Unknown adapter arm: {arm}")
        self.spec, self.dp, self.arm = spec, dp, arm
        self.x = np.asarray(dp["x"], dtype=float)
        if self.x.ndim != 1 or self.x.size < 2 or np.any(np.diff(self.x) <= 0):
            raise ValueError("DP metadata must include its increasing grid x")
        candidate = dict(candidate or {})
        self.decay = float(candidate.get("decay", 0.7))
        self.gain_c = float(candidate.get("gain_c", 0.25))
        self.gain_p = float(candidate.get("gain_p", 0.25))
        self.fixed_boundary = float(candidate.get("fixed_boundary", 0.65))
        if (
            not np.isfinite(
                [self.decay, self.gain_c, self.gain_p, self.fixed_boundary]
            ).all()
            or not 0 <= self.decay < 1
            or self.fixed_boundary < 0
        ):
            raise ValueError("Invalid feedback candidate")
        if isinstance(boundary_weights, Mapping):
            boundary_weights = boundary_weights["weights"]
        self.boundary_weights = (
            None
            if boundary_weights is None
            else np.asarray(boundary_weights, dtype=float)
        )
        if arm == "learned_margin" and (
            self.boundary_weights is None
            or self.boundary_weights.shape != (len(BOUNDARY_FEATURE_NAMES),)
            or not np.isfinite(self.boundary_weights).all()
        ):
            raise ValueError("learned_margin requires finite fitted boundary weights")
        self.state = None
        self.seed = int(seed)
        self._calls = 0
        self._input_mix = self._recurrent_mix = self._bias = None
        if arm in {"generic_gate", "dense_recurrent"}:
            rng = np.random.default_rng(self.seed)
            self._input_mix = rng.normal(size=(6, 6)) / np.sqrt(6)
            self._bias = rng.normal(scale=0.1, size=6)
            if arm == "dense_recurrent":
                matrix = rng.normal(size=(6, 6))
                self._recurrent_mix = matrix / max(np.linalg.norm(matrix, ord=2), 1)
        # Only value-boundary arms access this DP field. The first two can be
        # constructed with a deliberately poison-protected mapping.
        self._boundaries = None
        if arm in _VALUE_BOUNDARY:
            records = dp["boundaries"]
            if len(records) < spec.horizon or any(
                r["boundary"] is None or not r["threshold_shape"] for r in records
            ):
                raise ValueError(
                    "Value-boundary arm requires threshold-shaped task solutions"
                )
            self._boundaries = np.asarray([r["boundary"] for r in records], dtype=float)
        self._C = self._P = None
        if arm in _FULL or arm == "value_call":
            # Q_keep = production + continuation - discounted physical loss.
            # Reconstructing C with +L*H avoids mixing P with the action gap.
            h = first_passage(self.x, spec.mu, spec.sigma, spec.dt, spec.discount)["H"]
            self._P = spec.failure_cost * h
            self._C = np.asarray(dp["q_keep"], dtype=float) + self._P[None, :]
            if self._C.shape != (spec.horizon, self.x.size):
                raise ValueError("Channel value table has the wrong horizon/grid")

    def reset(self, batch_size=None, mask=None):
        if mask is not None:
            if self.state is None:
                raise ValueError("Cannot reset a mask before batch initialization")
            mask = np.asarray(mask, dtype=bool)
            if mask.shape != (self.state.shape[0],):
                raise ValueError("Reset mask has wrong batch size")
            self.state[mask] = 0
        else:
            self.state = None if batch_size is None else np.zeros((int(batch_size), 6))
            self._calls = 0

    def _boundary(self, remaining):
        if self.arm == "fixed_margin":
            return np.full(remaining.shape, self.fixed_boundary)
        if self.arm == "learned_margin":
            return np.clip(
                boundary_features(self.spec, remaining) @ self.boundary_weights,
                0,
                self.x[-1],
            )
        return self._boundaries[remaining - 1]

    def step(self, state_indices, remaining, previous_failed, previous_action_risk):
        states = np.asarray(state_indices, dtype=int)
        if states.ndim != 1:
            raise ValueError("State indices must be one-dimensional")
        batch = states.size
        rem = np.broadcast_to(np.asarray(remaining, dtype=int), states.shape)
        previous_failed = np.broadcast_to(
            np.asarray(previous_failed, dtype=float), states.shape
        )
        previous_risk = np.broadcast_to(
            np.asarray(previous_action_risk, dtype=float), states.shape
        )
        if (
            np.any(states < -1)
            or np.any(states >= self.x.size)
            or np.any(rem < 1)
            or np.any(rem > self.spec.horizon)
            or not np.isfinite(previous_failed).all()
            or not np.isfinite(previous_risk).all()
            or np.any(previous_failed < 0)
            or np.any(previous_failed > 1)
            or np.any(previous_risk < 0)
            or np.any(previous_risk > 1)
        ):
            raise ValueError(
                "Invalid state, remaining time or causal previous event input"
            )
        if self.state is None:
            self.state = np.zeros((batch, 6))
        if self.state.shape != (batch, 6):
            raise ValueError(
                "Batch size changed; call reset before a new trajectory batch"
            )
        active = states >= 0
        safe_indices = np.maximum(states, 0)
        x = self.x[safe_indices]
        boundary = self._boundary(rem)
        raw_margin = np.clip(
            (x - boundary) / (self.spec.sigma * np.sqrt(self.spec.dt)), -4, 4
        )
        # Past action risk is public to all arms. No current-risk leak through
        # typed flow is allowed in the margin/call feature ablations.
        flow = np.clip(previous_risk / self.spec.dt, 0, 8)
        risk = np.zeros(batch)
        call = np.zeros(batch)
        put = np.zeros(batch)
        scale = 1 + rem * self.spec.dt * self.spec.production_rate
        if self._C is not None:
            call = self._C[rem - 1, safe_indices] / scale
        if self.arm in _FULL:
            put = self._P[safe_indices] / scale
            risk = first_passage(x, self.spec.mu, self.spec.sigma, self.spec.dt)["F"]
        event_input = previous_failed if self.arm == "event_reset" else previous_risk
        old = self.state * (1 - event_input[:, None])
        if self.arm == "native_sparse":
            feedback = self.gain_c * call - self.gain_p * put
        else:
            feedback = self.gain_c * old[:, 1] - self.gain_p * old[:, 2]
        margin = np.clip(raw_margin + feedback, -4, 4)
        drive = np.clip(
            -margin - self.gain_c * call + self.gain_p * put + event_input, -4, 4
        )
        inputs = np.column_stack((margin, call, put, risk, event_input, drive))
        if self.arm == "native_sparse":
            next_state = inputs
        elif self.arm == "generic_gate":
            mixed = np.tanh(inputs @ self._input_mix + self._bias)
            next_state = self.decay * old + (1 - self.decay) * mixed
        elif self.arm == "dense_recurrent":
            next_state = np.tanh(
                inputs @ self._input_mix
                + self.decay * old @ self._recurrent_mix
                + self._bias
            )
        else:
            next_state = self.decay * old + (1 - self.decay) * inputs
            # A trace of prior events is accumulated, rather than erased by its
            # own reset factor. Actual vs expected is the event/flow contrast.
            next_state[:, 4] = (
                self.decay * self.state[:, 4] + (1 - self.decay) * event_input
            )
        next_state = np.clip(next_state, -4, 4)
        next_state[~active] = 0
        context = np.column_stack(
            (
                x / 2,
                rem / 16.0,
                np.full(batch, self.spec.mu / 0.6),
                np.full(batch, self.spec.sigma / 0.6),
                np.full(batch, self.spec.maintenance_cost),
                np.full(batch, self.spec.failure_cost / 6),
                np.full(batch, self.spec.production_rate / 1.5),
                np.full(batch, self.spec.discount / 0.2),
                np.full(batch, self.spec.maintenance_reset / 2),
                np.full(batch, self.spec.failure_reset / 2),
                np.full(batch, self.spec.dt),
            )
        )
        raw = np.clip(np.column_stack((context, next_state)), -4, 4)
        raw[~active] = 0
        margin, risk, flow = [
            np.where(active, item, 0.0) for item in (margin, risk, flow)
        ]
        self.state = next_state
        self._calls += 1
        return {
            "raw": raw,
            "margin": margin,
            "risk": risk,
            "flow": flow,
            "boundary": np.where(active, boundary, 0.0),
            "C": np.where(active, call, 0.0),
            "P": np.where(active, put, 0.0),
            "active": active,
        }

    def metadata(self):
        full = self.arm in _FULL
        return {
            "arm": self.arm,
            "raw_features": len(FEATURE_NAMES),
            "feature_names": FEATURE_NAMES,
            "adapter_state_dims": 0 if self.arm == "native_sparse" else 6,
            "boundary_source": "fixed_candidate"
            if self.arm == "fixed_margin"
            else "training_regression"
            if self.arm == "learned_margin"
            else "public_model_bellman",
            "uses_dp_continuation": self._C is not None,
            "uses_dp_boundary": self._boundaries is not None,
            "current_risk_visible": full,
            "C_visible": self._C is not None,
            "P_visible": full,
            "flow_semantics": "previous_action_risk / dt; initial zero",
            "reset_trace": "previous_observed_failure"
            if self.arm == "event_reset"
            else "previous_action_risk",
            "mixing_coefficient_count": 78
            if self.arm == "dense_recurrent"
            else 42
            if self.arm == "generic_gate"
            else 0,
            "feedback_coefficient_count": 3,
            "trainable_adapter_parameters": 0,
            "boundary_parameter_count": len(BOUNDARY_FEATURE_NAMES)
            if self.arm == "learned_margin"
            else 0,
            "external_head_parameter_count": 42,
            "seed": self.seed,
            "candidate": {
                "decay": self.decay,
                "gain_c": self.gain_c,
                "gain_p": self.gain_p,
                "fixed_boundary": self.fixed_boundary,
            },
        }
