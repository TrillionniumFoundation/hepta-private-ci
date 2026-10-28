"""Full BPTT and matched development selection, before independent confirmation."""

from pathlib import Path

import numpy as np

from experiments.continuous_boundary_flow.native.adapter import (
    NativeBridge,
    make_profile,
    save_profile,
    Q,
)
from experiments.continuous_boundary_flow.training import encoder, ridge_head
from . import cells
from .common import (
    CANDIDATES,
    FEATURE_NAMES,
    OBJECTIVE,
    CostMeter,
    canonical,
    kind_for,
    save_json,
    sha,
)
from .execution import run_context
from .features import native_rows, training_arrays
from .native.bridge import ScoreBridge


def native_profile(seed, candidate, head=None, bias=None, stage="act"):
    enc, enc_bias = encoder(seed)
    source = {
        "seed": seed,
        "candidate": candidate,
        "features": FEATURE_NAMES,
        "schema": "continuous-policy-common18-native.v1",
    }
    return make_profile(
        FEATURE_NAMES[:15] + FEATURE_NAMES[16:],
        enc.tolist(),
        enc_bias.tolist(),
        np.zeros((3, 20)).tolist() if head is None else head.tolist(),
        np.zeros(3).tolist() if bias is None else bias.tolist(),
        source_model_digest=sha(canonical(source)),
        objective_digest=OBJECTIVE,
        arm_id="native_sparse",
        stage=stage,
        maximum_ticks=512,
    )


def train_arm(
    output,
    binaries,
    seed,
    arm,
    train_contexts,
    histories,
    development,
    boundary_fit,
    *,
    epochs=120,
    candidate_indices=None,
    development_paths=8,
):
    output = Path(output)
    target = output / "training" / str(seed) / arm
    target.mkdir(parents=True, exist_ok=False)
    weights = np.asarray(boundary_fit["weights"]) if arm == "learned_margin" else None
    meter = CostMeter()
    bridge = (
        NativeBridge(binaries["native"], target / "host")
        if arm == "native_sparse"
        else ScoreBridge(binaries["score"], target / "host")
    )
    candidates = (
        list(range(len(CANDIDATES))) if candidate_indices is None else candidate_indices
    )
    fitted = []
    try:
        for index in candidates:
            candidate, fit_clock = CANDIDATES[index], CostMeter()
            x, resets, q = training_arrays(
                train_contexts, histories, arm, candidate, weights
            )
            checkpoint = {
                "schema": "hepta.continuous-boundary-policy.checkpoint.v1",
                "arm": arm,
                "seed": seed,
                "candidate_index": index,
                "candidate": candidate,
                "boundary_weights": None if weights is None else weights.tolist(),
                "boundary_extra_scalars": 20 if weights is not None else 0,
            }
            if arm == "native_sparse":
                transform_path, transform_sha = save_profile(
                    target / "profiles",
                    native_profile(seed, candidate, stage="transform"),
                )
                bridge.load_profile(transform_path)
                by_time = [native_rows(row) for row in x]
                sequences = [
                    [by_time[t][b] for t in range(len(x))] for b in range(x.shape[1])
                ]
                native = bridge.kernel_batch(transform_sha, sequences)
                activation = (
                    np.asarray(
                        [
                            [r["activation_q24"] for r in seq]
                            for seq in native["sequences"]
                        ]
                    ).reshape(-1, 20)
                    / Q
                )
                targets = q.transpose(1, 0, 2).reshape(-1, 3)[:, :2] / 8
                head, bias, fit = ridge_head(
                    activation, targets, penalty=candidate["native_ridge"]
                )
                profile_path, profile_sha = save_profile(
                    target / "profiles", native_profile(seed, candidate, head, bias)
                )
                bridge.load_profile(profile_path)
                checkpoint.update(
                    kind="native",
                    model_parameter_count=42,
                    frozen_encoder_coefficients=420,
                    profile_path=str(profile_path.relative_to(output)),
                    profile_sha256=profile_sha,
                )
                fit["native_training_kernel_calls"] = native["actual_kernel_calls"]
            else:
                kind = kind_for(arm)
                params = cells.initialize(seed, kind)
                params, fit = cells.fit(
                    x,
                    resets,
                    q,
                    params,
                    kind,
                    learning_rate=candidate["learning_rate"],
                    epochs=epochs,
                )
                checkpoint.update(
                    kind=kind,
                    model_parameter_count=cells.parameter_count(params),
                    model=cells.serialize(params, kind),
                )
            fit_cost = fit_clock.finish()
            path = target / "candidates" / f"{index}.json"
            identity = save_json(path, checkpoint)
            values, dev_counts = [], []
            for context in development:
                run = run_context(
                    context,
                    seed=seed,
                    phase="development",
                    paths=development_paths,
                    arm=arm,
                    checkpoint_sha256=identity,
                    checkpoint=checkpoint,
                    bridge=bridge,
                    retain=False,
                )
                values.extend(run["net_utility"].tolist())
                dev_counts.append(run["counts"])
            fitted.append(
                {
                    "candidate_index": index,
                    "candidate": candidate,
                    "path": str(path.relative_to(output)),
                    "sha256": identity,
                    "development_mean_net_utility": float(np.mean(values)),
                    "development_returns": values,
                    "development_counts": dev_counts,
                    "fit": fit,
                    "fit_cost_subset": fit_cost,
                    "feature_sha256": sha(x.tobytes()),
                    "reset_sha256": sha(resets.tobytes()),
                    "teacher_sha256": sha(q.tobytes()),
                }
            )
    finally:
        native_cost = bridge.close()
    selected = max(
        fitted,
        key=lambda item: (
            item["development_mean_net_utility"],
            -item["candidate_index"],
        ),
    )
    selected_bytes = (output / selected["path"]).read_bytes()
    selected_path = output / "checkpoints" / str(seed) / f"{arm}.json"
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    with selected_path.open("xb") as stream:
        stream.write(selected_bytes)
    receipt = {
        "schema": "hepta.continuous-boundary-policy.training.v1",
        "seed": seed,
        "arm": arm,
        "candidates": fitted,
        "selected_index": selected["candidate_index"],
        "cost": meter.finish(),
        "native_process_cost": native_cost,
        "test_data_used": False,
    }
    save_json(target / "TRAINING.json", receipt)
    return {
        "seed": seed,
        "arm": arm,
        "path": str(selected_path.relative_to(output)),
        "sha256": sha(selected_bytes),
    }, receipt
