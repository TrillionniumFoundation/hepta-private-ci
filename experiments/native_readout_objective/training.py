"""Shared actual-native training activations and matched readout development."""

from pathlib import Path

import numpy as np

from experiments.continuous_boundary_flow.native.adapter import Q, save_profile
from experiments.continuous_boundary_flow.training import ridge_head
from experiments.continuous_boundary_policy.features import native_rows, training_arrays
from experiments.continuous_boundary_policy.training import native_profile

from .common import CANDIDATES, CostMeter, open_bridge, save_json, sha, write_records
from .execution import run_context
from .head import fit


def export_features(output, binary, seed, contexts, histories, source=None):
    """KernelBatch executes once per seed; every objective consumes its same bytes."""
    output = Path(output)
    target = output / "datasets" / str(seed)
    target.mkdir(parents=True, exist_ok=True)
    meter = CostMeter()
    x, resets, q = training_arrays(contexts, histories, "native_sparse", CANDIDATES[1])
    if np.any(resets != 0):
        raise ValueError("Native sparse training has no added hidden reset")
    typed_by_time = [native_rows(row) for row in x]
    sequences = [
        [typed_by_time[t][b] for t in range(len(x))] for b in range(x.shape[1])
    ]
    profile_path, profile_sha = save_profile(
        target / "profiles", native_profile(seed, CANDIDATES[1], stage="transform")
    )
    bridge = open_bridge(binary, target / "host", source)
    try:
        bridge.load_profile(profile_path, profile_sha)
        response = bridge.kernel_batch(profile_sha, sequences)
    finally:
        native_cost = bridge.close()
    activation = np.asarray(
        [[r["activation_q24"] for r in seq] for seq in response["sequences"]],
        dtype=np.int64,
    ).reshape(-1, 20)
    physical_q = q.transpose(1, 0, 2).reshape(-1, 3)
    if (
        response["actual_kernel_calls"] != len(activation)
        or native_cost["counters"]["actual_ndu_calls"] != 0
    ):
        raise ValueError("Training export must execute only the original sparse kernel")
    array_path = target / "native_training.npz"
    with array_path.open("xb") as stream:
        np.savez_compressed(
            stream,
            activation_q24=activation,
            physical_q=physical_q,
            features=x,
            sequence_context=np.repeat(
                np.arange(len(contexts)), len(histories[0][0]["states"])
            ),
            sequence_path=np.tile(
                np.arange(len(histories[0][0]["states"])), len(contexts)
            ),
        )
    raw_path = target / "native_export.jsonl.gz"
    raw = write_records(
        raw_path, [{"request_sequences": sequences, "response": response}]
    )
    raw["path"] = str(raw_path.relative_to(output))
    receipt = {
        "schema": "hepta.native-readout-objective.feature-export.v1",
        "seed": seed,
        "phase": "training",
        "path": str(array_path.relative_to(output)),
        "sha256": sha(array_path.read_bytes()),
        "profile_path": str(profile_path.relative_to(output)),
        "profile_sha256": profile_sha,
        "native_export": raw,
        "rows": len(activation),
        "sequence_count": len(sequences),
        "order": "context, path, elapsed; teacher and activations flattened identically",
        "physical_q_sha256": sha(physical_q.tobytes()),
        "activation_q24_sha256": sha(activation.tobytes()),
        "features_sha256": sha(x.tobytes()),
        "actual_kernel_calls": response["actual_kernel_calls"],
        "actual_ndu_calls": 0,
        "native_process_cost": native_cost,
        "cost": meter.finish(),
        "shared_by_all_arms_and_candidates": True,
    }
    save_json(target / "FEATURE_EXPORT.json", receipt)
    return activation / Q, physical_q, receipt


def train_arm(
    output,
    binary,
    seed,
    arm,
    activation,
    physical_q,
    export_receipt,
    development,
    source=None,
    *,
    epochs=120,
    candidate_indices=None,
    development_paths=8,
):
    output = Path(output)
    target = output / "training" / str(seed) / arm
    target.mkdir(parents=True, exist_ok=False)
    meter = CostMeter()
    bridge = open_bridge(binary, target / "host", source)
    fitted = []
    candidates = range(3) if candidate_indices is None else candidate_indices
    try:
        for index in candidates:
            candidate, fitting = CANDIDATES[index], CostMeter()
            if arm == "ridge_reference":
                head, bias, fit_receipt = ridge_head(
                    activation, physical_q[:, :2] / 8, penalty=candidate["native_ridge"]
                )
                coefficients = np.vstack((head[:2].T, bias[:2]))
            else:
                objective = {
                    "iterative_q_mse": "q_mse",
                    "policy_regret": "policy_regret",
                }[arm]
                coefficients, fit_receipt = fit(
                    activation,
                    physical_q,
                    objective,
                    learning_rate=candidate["learning_rate"],
                    epochs=epochs,
                )
                head, bias = np.zeros((3, 20)), np.zeros(3)
                head[:2], bias[:2] = coefficients[:-1].T, coefficients[-1]
            profile_path, profile_sha = save_profile(
                target / "profiles", native_profile(seed, candidate, head, bias)
            )
            bridge.load_profile(profile_path, profile_sha)
            checkpoint = {
                "schema": "hepta.native-readout-objective.checkpoint.v1",
                "seed": seed,
                "arm": arm,
                "candidate_index": index,
                "candidate": candidate,
                "kind": "native",
                "profile_path": str(profile_path.relative_to(output)),
                "profile_sha256": profile_sha,
                "head_coefficients": coefficients.tolist(),
                "model_parameter_count": 42,
                "frozen_encoder_coefficients": 420,
                "boundary_weights": None,
                "shared_feature_export_sha256": sha(
                    (
                        output / "datasets" / str(seed) / "FEATURE_EXPORT.json"
                    ).read_bytes()
                ),
                "training_activation_q24_sha256": export_receipt[
                    "activation_q24_sha256"
                ],
                "physical_teacher_sha256": export_receipt["physical_q_sha256"],
            }
            checkpoint_path = target / "candidates" / f"{index}.json"
            identity = save_json(checkpoint_path, checkpoint)
            fit_cost = fitting.finish()
            records, returns, counts = [], [], []
            for context in development:
                result = run_context(
                    context,
                    seed=seed,
                    phase="development",
                    paths=development_paths,
                    arm=arm,
                    checkpoint_sha256=identity,
                    checkpoint=checkpoint,
                    bridge=bridge,
                )
                records.extend(result["records"])
                returns.extend(result["net_utility"].tolist())
                counts.append(result["counts"])
            dev_path = target / "development" / f"{index}.jsonl.gz"
            shard = write_records(dev_path, records)
            shard.update(
                path=str(dev_path.relative_to(output)),
                seed=seed,
                arm=arm,
                split="development",
                counts=counts,
            )
            fitted.append(
                {
                    "candidate_index": index,
                    "candidate": candidate,
                    "path": str(checkpoint_path.relative_to(output)),
                    "sha256": identity,
                    "development_mean_net_utility": float(np.mean(returns)),
                    "development_returns": returns,
                    "development_shards": [shard],
                    "fit": fit_receipt,
                    "fit_cost_subset": fit_cost,
                    "observed_active_columns": int(
                        np.count_nonzero(np.max(activation, axis=0) > 0)
                    ),
                    "activation_q24_sha256": export_receipt["activation_q24_sha256"],
                    "physical_q_sha256": export_receipt["physical_q_sha256"],
                }
            )
    finally:
        native_cost = bridge.close()
    selected = max(
        fitted,
        key=lambda row: (row["development_mean_net_utility"], -row["candidate_index"]),
    )
    selected_path = output / "checkpoints" / str(seed) / f"{arm}.json"
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    with selected_path.open("xb") as stream:
        stream.write((output / selected["path"]).read_bytes())
    receipt = {
        "schema": "hepta.native-readout-objective.training.v1",
        "seed": seed,
        "arm": arm,
        "candidates": fitted,
        "selected_index": selected["candidate_index"],
        "native_process_cost": native_cost,
        "cost": meter.finish(),
        "test_data_used": False,
    }
    save_json(target / "TRAINING.json", receipt)
    return {
        "seed": seed,
        "arm": arm,
        "path": str(selected_path.relative_to(output)),
        "sha256": selected["sha256"],
    }, receipt
