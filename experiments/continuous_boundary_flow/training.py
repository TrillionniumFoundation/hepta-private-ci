"""Matched-budget readout fitting and declared feedback/boundary selection."""

from pathlib import Path

import numpy as np

from .common import CANDIDATES, CostWindow, canonical, rng_for, save_json, sha
from .execution import run_context, training_features
from .models import FEATURE_NAMES
from .native.adapter import NativeBridge, make_profile, save_profile


def encoder(seed):
    rng = rng_for(seed, "common-frozen-encoder")
    matrix = rng.normal(0.0, 0.16, (20, 20))
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1.0)
    bias = rng.uniform(-0.1, 0.15, 20)
    return matrix, bias


def ridge_head(x, y, penalty=0.01):
    design = np.column_stack((x, np.ones(len(x))))
    scale = np.maximum(design.std(axis=0), 0.15)
    scale[-1] = 1.0
    scaled = design / scale
    regularizer = np.eye(scaled.shape[1]) * penalty * len(x)
    regularizer[-1, -1] = 1e-10
    fitted = (
        np.linalg.solve(scaled.T @ scaled + regularizer, scaled.T @ y) / scale[:, None]
    )
    raw = fitted.copy()
    compression = max(1.0, float(np.max(np.abs(fitted))) / 7.5)
    fitted /= compression
    head = np.zeros((3, 20))
    head[:2] = fitted[:-1].T
    bias = np.zeros(3)
    bias[:2] = fitted[-1]
    return (
        head,
        bias,
        {
            "training_mse": float(np.mean((design @ raw - y) ** 2)),
            "head_scalars": 42,
            "nonzero_head_scalars": int(np.count_nonzero(np.abs(fitted) > 1e-12)),
            "observed_active_columns": int(np.count_nonzero(np.max(x, axis=0) > 0)),
            "common_score_rescaling": compression,
        },
    )


def profile_for(
    seed, arm, candidate, boundary_weights, head=None, bias=None, *, stage="act"
):
    enc, enc_bias = encoder(seed)
    source = {
        "seed": seed,
        "arm": arm,
        "candidate": candidate,
        "boundary_weights": None
        if boundary_weights is None
        else np.asarray(boundary_weights).tolist(),
        "encoder_seed": "common-frozen-encoder",
        "adapter_schema": "continuous-flow-adapter.v1",
    }
    return make_profile(
        FEATURE_NAMES,
        enc.tolist(),
        enc_bias.tolist(),
        np.zeros((3, 20)).tolist() if head is None else head.tolist(),
        np.zeros(3).tolist() if bias is None else bias.tolist(),
        source_model_digest=sha(canonical(source)),
        objective_digest=sha(
            b"finite-window-production-minus-discounted-failure-maintenance.v1"
        ),
        arm_id=arm,
        stage=stage,
        maximum_ticks=64,
    )


def train_arm(
    output,
    binary,
    seed,
    arm,
    train_contexts,
    histories,
    dev_contexts,
    boundary_fit,
    *,
    candidate_indices=None,
    dev_paths=8,
):
    output = Path(output)
    target = output / "training" / str(seed) / arm
    target.mkdir(parents=True, exist_ok=False)
    candidates = (
        list(range(len(CANDIDATES)))
        if candidate_indices is None
        else list(candidate_indices)
    )
    weights = np.asarray(boundary_fit["weights"]) if arm == "learned_margin" else None
    window = CostWindow()
    bridge = NativeBridge(binary, target / "host")
    fitted = []
    try:
        for index in candidates:
            candidate = CANDIDATES[index]
            transform = profile_for(seed, arm, candidate, weights, stage="transform")
            transform_path, transform_sha = save_profile(target / "profiles", transform)
            bridge.load_profile(transform_path)
            x, y, feature_receipt = training_features(
                train_contexts,
                histories,
                seed=seed,
                arm=arm,
                candidate=candidate,
                boundary_weights=weights,
                bridge=bridge,
                profile_sha=transform_sha,
            )
            head, bias, fit_receipt = ridge_head(x, y)
            profile = profile_for(seed, arm, candidate, weights, head, bias)
            profile_path, identity = save_profile(target / "profiles", profile)
            bridge.load_profile(profile_path)
            development = []
            for context in dev_contexts:
                run = run_context(
                    context,
                    seed=seed,
                    phase="development",
                    paths=dev_paths,
                    arm=arm,
                    checkpoint_sha256=identity,
                    bridge=bridge,
                    profile_sha=identity,
                    candidate=candidate,
                    boundary_weights=weights,
                    retain=False,
                )
                development.extend(run["net_utility"].tolist())
            fitted.append(
                {
                    "candidate_index": index,
                    "candidate": candidate,
                    "profile_path": str(profile_path.relative_to(output)),
                    "profile_sha256": identity,
                    "development_mean_net_utility": float(np.mean(development)),
                    "development_returns": development,
                    "head_fit": fit_receipt,
                    "features": feature_receipt,
                }
            )
        selected = max(
            fitted,
            key=lambda r: (r["development_mean_net_utility"], -r["candidate_index"]),
        )
    finally:
        native_cost = bridge.close()
    cost = window.finish()
    checkpoint = {
        "schema": "hepta.continuous-boundary.actor-checkpoint.v1",
        "seed": seed,
        "arm": arm,
        "candidate": selected["candidate"],
        "candidate_index": selected["candidate_index"],
        "profile_path": selected["profile_path"],
        "profile_sha256": selected["profile_sha256"],
        "boundary_weights": None if weights is None else weights.tolist(),
        "readout_active_parameter_budget": 42,
        "boundary_extra_coefficients": 20 if weights is not None else 0,
        "training_scope": "native sparse feature readout fit plus development feedback selection; no recurrent BPTT",
    }
    path = output / "checkpoints" / str(seed) / f"{arm}.json"
    checkpoint_sha = save_json(path, checkpoint)
    receipt = {
        "schema": "hepta.continuous-boundary.training-receipt.v1",
        "seed": seed,
        "arm": arm,
        "candidates": fitted,
        "selected_index": selected["candidate_index"],
        "cost": cost,
        "native_process_cost": native_cost,
        "selection_phase": "development",
        "test_data_used": False,
    }
    save_json(target / "TRAINING.json", receipt)
    return (
        checkpoint,
        {
            "arm": arm,
            "train_seed": seed,
            "path": str(path.relative_to(output)),
            "sha256": checkpoint_sha,
        },
        receipt,
    )
