"""Frozen-encoder feature extraction with causal boundary and timestamp controls."""

import hashlib
from dataclasses import asdict
import time

import numpy as np
import torch

from .batched_flow import BatchedFlow, FlowConfig
from .continuation import fit_continuation


BOUNDARIES = ("fixed", "scalar", "input_boundary", "task_continuation")
CHANNEL_ABLATIONS = {
    "all_four": (), "drop_risk": ("risk",), "drop_call": ("call",),
    "drop_margin": ("margin",), "drop_occupation": ("occupation",),
    "dual": (), "risk_only": ("call",), "call_only": ("risk",),
    "neither": ("risk", "call"), "no_margin": ("margin",),
    "no_occupation": ("occupation",),
}


def flow_for(config, variant):
    """Variant overrides are immutable experiment inputs, including phase count."""
    flow = {**config.get("flow", {}), **variant.get("flow", {})}
    if "input_size" in flow:
        raise ValueError("input_size is derived from the frozen dataset, not a flow override")
    return flow


def tensor_digest(tensor):
    value = tensor.detach().cpu().contiguous()
    return hashlib.sha256(str((str(value.dtype), tuple(value.shape))).encode()
                          + value.numpy().tobytes()).hexdigest()


def build_encoder(input_size, *, seed, flow=None, device="cpu", dtype="float64"):
    torch.manual_seed(seed)
    model = BatchedFlow(FlowConfig(input_size=input_size, **(flow or {})))
    return model.to(device=device, dtype=getattr(torch, dtype)).eval()


def extract_features(model, observations, *, intervals=None, policy=None,
                     critic=None, drift="input", channels="dual"):
    """Return last/mean features. Distinct physical-time schedules are grouped.

    There is no interpolation, constant-dt substitution, or state sharing
    between examples. The observed-input MDP is a declared surrogate for the
    population state, not an identified counterfactual reset model.
    """
    started = time.perf_counter()
    array = np.asarray(observations)
    if array.ndim != 3 or min(array.shape) < 1 or not np.isfinite(array).all():
        raise ValueError("finite nonempty [samples,time,input] observations required")
    policy = policy or {"kind": "fixed", "offset": 0.0}
    if policy["kind"] not in BOUNDARIES or drift not in ("fixed", "input"):
        raise ValueError("unknown boundary/drift control")
    if channels not in CHANNEL_ABLATIONS:
        raise ValueError("unknown channel ablation")
    if policy["kind"] == "task_continuation" and critic is None:
        raise ValueError("task boundary needs a frozen training critic")
    dt = (np.full(array.shape[:2], model.config.dt) if intervals is None
          else np.asarray(intervals, dtype=np.float64))
    micros = np.rint(dt * 1_000_000)
    if (dt.shape != array.shape[:2] or not np.isfinite(dt).all() or np.any(micros < 1)
            or not np.allclose(dt * 1_000_000, micros, rtol=0, atol=1e-6)):
        raise ValueError("intervals must be positive integer microseconds in seconds")
    schedules, inverse = np.unique(micros.astype(np.int64), axis=0, return_inverse=True)
    like = model.drive.weight
    output = like.new_empty(len(array), 2 * len(model.feature_names))
    mask = [1.0] * len(model.feature_names)
    for name in CHANNEL_ABLATIONS[channels]:
        mask[model.feature_names.index(name)] = 0.0
    peak_state, max_mass_error, max_content_error, upper_projection = 0, 0.0, 0.0, 0.0
    boundary_min, boundary_max, boundary_range, boundary_jump = float("inf"), -float("inf"), 0.0, 0.0
    with torch.no_grad():
        for schedule_id, schedule in enumerate(schedules):
            members = np.flatnonzero(inverse == schedule_id)
            for start in range(0, len(members), model.config.max_batch):
                indices = members[start:start + model.config.max_batch]
                batch = torch.as_tensor(array[indices], dtype=like.dtype, device=like.device)
                state, total = None, None
                for step in range(array.shape[1]):
                    causal = batch[:, step]
                    if policy["kind"] == "task_continuation":
                        boundary = like.new_tensor(critic.query(array[indices, step], array.shape[1] - step))
                    else:
                        boundary = causal.new_full((len(causal),), float(policy.get("offset", 0.0)))
                        if policy["kind"] == "input_boundary":
                            boundary = boundary + float(policy.get("gain", 0.0)) * causal[:, 0].tanh()
                    fixed_drift = model.config.base_drift if drift == "fixed" else None
                    boundary_min = min(boundary_min, float(boundary.min()))
                    boundary_max = max(boundary_max, float(boundary.max()))
                    boundary_range = max(boundary_range, float(boundary.max() - boundary.min()))
                    previous_boundary = torch.zeros_like(boundary) if state is None else state.boundary
                    boundary_jump = max(boundary_jump, float((boundary - previous_boundary).abs().max()))
                    features, state, diagnostics = model.step(
                        causal, state, dt=int(schedule[step]) / 1_000_000,
                        boundary_override=boundary, drift_override=fixed_drift, feature_mask=mask)
                    total = features if total is None else total + features
                    peak_state = max(peak_state, state.tensor_bytes())
                    max_mass_error = max(max_mass_error, float(diagnostics["mass_error"].abs().max()))
                    max_content_error = max(max_content_error, float(diagnostics["content_balance_error"].abs().max()))
                    upper_projection += float(diagnostics["upper_projection_mass"].sum())
                output[torch.as_tensor(indices, device=like.device)] = torch.cat(
                    (features, total / array.shape[1]), dim=1)
        if like.is_cuda:
            torch.cuda.synchronize(like.device)
    return output, {"wall_seconds": time.perf_counter() - started,
                    "encoder_events": int(array.shape[0] * array.shape[1]),
                    "time_schedules": len(schedules), "timestamp_semantics": "physical integer microseconds",
                    "feature_digest": tensor_digest(output), "peak_batch_state_bytes": peak_state,
                    "feature_tensor_bytes": output.numel() * output.element_size(),
                    "max_mass_error": max_mass_error, "max_content_balance_error": max_content_error,
                    "upper_projection_mass": upper_projection, "upper_mode": model.config.upper_mode,
                    "flow_config": asdict(model.config), "input_output_dtype": str(like.dtype),
                    "state_dtype": str(state.density.dtype),
                    "boundary_min": boundary_min, "boundary_max": boundary_max,
                    "maximum_within_step_boundary_range": boundary_range,
                    "maximum_boundary_jump": boundary_jump,
                    "task_boundary_scope": "hard context/time table; no encoder-gradient or global-task-optimality claim",
                    "channels": channels, "drift": drift, "policy": policy,
                    "channel_mask": dict(zip(model.feature_names, mask)),
                    "ablation_scope": "readout features masked; state dynamics and channel computation retained",
                    "call_kind": "frozen_finite_policy_continuation; not full HX equity"}


def standardize(train, other):
    mean, scale = train.mean(0), train.std(0, unbiased=False).clamp_min(1e-8)
    return (train - mean) / scale, (other - mean) / scale, mean, scale


def training_ridge_score(features, targets, penalty=0.001):
    """Training-only boundary search objective; never consumes dev/test labels."""
    normalized, _, _, _ = standardize(features, features)
    design = torch.cat((normalized, torch.ones_like(normalized[:, :1])), 1)
    regularizer = torch.eye(design.shape[1], dtype=design.dtype, device=design.device) * penalty
    regularizer[-1, -1] = 0
    solution = torch.linalg.solve(design.T @ design + regularizer, design.T @ targets)
    return float((design @ solution - targets).square().mean())


def boundary_candidates(kind, offsets=(-0.25, 0.0, 0.25), gains=(-0.25, 0.0, 0.25)):
    if kind == "fixed" or kind == "task_continuation":
        return [{"kind": kind, "offset": 0.0}]
    if kind == "scalar":
        return [{"kind": kind, "offset": float(offset)} for offset in offsets]
    if kind == "input_boundary":
        return [{"kind": kind, "offset": float(offset), "gain": float(gain)}
                for offset in offsets for gain in gains]
    raise ValueError("unknown boundary family")


def fit_task_boundary(train, *, reward_definition=None):
    return fit_continuation(train["x"], split="train", horizon=train["x"].shape[1],
                            context_column=1 if train["x"].shape[2] > 1 else None,
                            running_rewards=train.get("running_rewards"),
                            reward_definition=reward_definition)
