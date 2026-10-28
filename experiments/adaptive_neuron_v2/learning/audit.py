"""Independent checkpoint, causal-data, optimizer and hypergradient audit."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np

from ..ledger import sha, write_json_exclusive
from ..provenance import verify
from .kernel import PARAMETER_NAMES, RAW_LIMIT, initial_raw, physical
from .meta import ADAM_BETA1, ADAM_BETA2, ADAM_EPSILON, ARMS, check_hypergradient
from .network import initialize, model_payload, parameter_digest
from .runner import HISTORY_BLOCK, PROTOCOL_PATH, arrays_from_json, validate_protocol
from .task import SPLIT_CODES, make_batch


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 512_000,
        f"invalid bounded artifact: {path}",
    )
    return json.loads(path.read_text())


def expected_task_digest(seed, task_index, split, context, count):
    """Rebuild the recorded raw-data hash without calling the task generator."""
    reliability, cost, horizon = context
    truth = np.empty(count, dtype=float)
    observations = np.empty((count, int(horizon)), dtype=float)
    for episode in range(count):
        random = np.random.default_rng(
            np.random.SeedSequence([seed, SPLIT_CODES[split], task_index, episode])
        )
        truth[episode] = 2 * random.integers(2) - 1
        observations[episode] = np.where(
            random.random(int(horizon)) < reliability, truth[episode], -truth[episode]
        )
    digest = hashlib.sha256()
    for array in (
        observations,
        truth,
        np.full(count, reliability),
        np.full(count, cost),
        np.full(count, horizon, dtype=int),
    ):
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def expected_schedule(seed, protocol):
    config = protocol["training"]
    contexts = list(
        itertools.product(
            protocol["datasets"]["train_reliability"],
            protocol["datasets"]["train_cost"],
            protocol["datasets"]["train_deadline"],
        )
    )
    random = np.random.default_rng(np.random.SeedSequence([seed, 1703]))
    result = []
    for index in range(config["outer_steps"]):
        context = contexts[int(random.integers(len(contexts)))]
        result.append(
            {
                "context": list(context),
                "support_dataset_sha256": expected_task_digest(
                    seed, index, "support", context, config["support_episodes"]
                ),
                "query_dataset_sha256": expected_task_digest(
                    seed, index, "query", context, config["query_episodes"]
                ),
            }
        )
    return result


def check_identity(payload, identity):
    require(
        all(payload.get(key) == value for key, value in identity.items()),
        "artifact source/phase/seed/arm identity mismatch",
    )


def check_history(rows, expected, config, arm):
    require(len(rows) == config["outer_steps"], "incomplete training history")
    raw, first, second = initial_raw(), np.zeros(3), np.zeros(3)
    cell_updates = 0
    for index, (row, schedule) in enumerate(zip(rows, expected)):
        require(
            row["step"] == index + 1
            and all(row[key] == value for key, value in schedule.items()),
            "causal task schedule or support/query data changed",
        )
        np.testing.assert_array_equal(
            row["raw_before"], raw, err_msg="outer optimizer continuity"
        )
        hyper = np.asarray(row["hypergradient"], dtype=float)
        require(
            hyper.shape == (3,) and np.all(np.isfinite(hyper)),
            "invalid joint hypergradient",
        )
        norm = float(np.linalg.norm(hyper))
        require(row["hypergradient_norm"] == norm, "hypergradient norm counter changed")
        require(
            row["hypergradient_clipped"] == (norm > config["hypergradient_norm_clip"]),
            "hypergradient clipping changed",
        )
        direction = np.zeros(3)
        projected = 0
        if arm == "meta_theta":
            gradient = hyper * min(
                1.0, config["hypergradient_norm_clip"] / max(norm, 1e-300)
            )
            first = ADAM_BETA1 * first + (1 - ADAM_BETA1) * gradient
            second = ADAM_BETA2 * second + (1 - ADAM_BETA2) * gradient**2
            first_corrected = first / (1 - ADAM_BETA1 ** (index + 1))
            second_corrected = second / (1 - ADAM_BETA2 ** (index + 1))
            direction = first_corrected / (np.sqrt(second_corrected) + ADAM_EPSILON)
            proposed = raw - config["outer_learning_rate"] * direction
            projected = int(np.sum(np.abs(proposed) >= RAW_LIMIT))
            raw = np.clip(proposed, -RAW_LIMIT, RAW_LIMIT)
        else:
            np.testing.assert_array_equal(
                hyper, 0, err_msg="fixed arm applied an outer update"
            )
        for name, value in (
            ("raw_after", raw),
            ("outer_first_moment", first),
            ("outer_second_moment", second),
            ("outer_bias_corrected_direction", direction),
        ):
            np.testing.assert_array_equal(
                row[name], value, err_msg=f"outer optimizer field: {name}"
            )
        require(
            row["raw_projected_scalars"] == projected,
            "outer projection counter changed",
        )
        values, jacobian = physical(raw)
        require(
            row["physical_after"] == dict(zip(PARAMETER_NAMES, values.tolist())),
            "physical parameter transform changed",
        )
        require(
            row["minimum_parameterization_jacobian"] == float(np.min(jacobian)),
            "parameter conditioning metadata changed",
        )
        delta = float(np.hypot(values[0], np.sqrt(2 * values[2]) * values[1]))
        require(
            row["inverse_diffusion_discriminant"] == 1 / delta,
            "diffusion conditioning metadata changed",
        )
        require(
            row["query_weight_update"] is not None
            and row["query_weight_learning_rate"]
            == config["query_weight_learning_rate"],
            "query labels were not used by a training arm",
        )
        for split, soft, channels in (
            ("support", False, 3 if arm == "meta_theta" else 0),
            ("query", True, 0),
        ):
            work = row[f"{split}_work"]
            cells = config[f"{split}_episodes"] * int(row["context"][2]) * 8
            require(
                work["cell_updates"] == cells
                and work["surrogate_scalar_evaluations"] == 2 * cells
                and work["soft_forward"] is soft
                and work["mixed_backward_parameter_channels"] == channels,
                "training work budget changed",
            )
            require(
                np.isfinite(work["spike_sum"])
                and -1e-10 <= work["spike_sum"] <= cells + 1e-10,
                "invalid hard/soft spike accounting",
            )
            cell_updates += cells
        for loss in (row["support_hard_bce"], row["query_fixed_soft_bce"]):
            require(
                np.isfinite(loss) and loss >= 0, "nonfinite or negative training loss"
            )
        for update in (row["inner_update"], row["query_weight_update"]):
            require(
                np.isfinite(update["gradient_norm"])
                and update["gradient_norm"] >= 0
                and update["gradient_clipped"]
                == (update["gradient_norm"] > config["gradient_norm_clip"])
                and 0 <= update["projected_scalars"] <= 57,
                "invalid shared weight-update metadata",
            )
    return raw, cell_updates


def audit_fit(root, record, identity, protocol, expected):
    seed, arm = record["seed"], record["arm"]
    fit_identity = {**identity, "seed": seed, "arm": arm}
    relative = f"seed_{seed}/{arm}"
    require(record["directory"] == relative, "unregistered fit directory")
    directory = root / relative
    require(
        not directory.is_symlink()
        and directory.resolve().is_relative_to(root.resolve()),
        "fit escapes its evidence root",
    )
    complete = read(directory / "COMPLETE.json")
    require(
        sha(directory / "COMPLETE.json") == record["complete_sha256"]
        and complete.get("complete") is True,
        "completion receipt identity mismatch",
    )
    check_identity(complete, fit_identity)
    steps = protocol["training"]["outer_steps"]
    ends = list(range(HISTORY_BLOCK, steps, HISTORY_BLOCK)) + [steps]
    expected_files = {"START.json", "checkpoint.json", "neural.json", "TRAINING.json"}
    first = 1
    for end in ends:
        expected_files.update(
            (f"progress/step_{end:04}.json", f"history/steps_{first:04}_{end:04}.json")
        )
        first = end + 1
    require(set(complete["files"]) == expected_files, "missing or extra fit artifacts")
    for name, digest in complete["files"].items():
        require(
            (directory / name).resolve().is_relative_to(directory.resolve())
            and sha(directory / name) == digest,
            "fit artifact hash mismatch",
        )
    start = read(directory / "START.json")
    check_identity(start, fit_identity)
    initial = initialize(seed)
    for key, value in initial.items():
        np.testing.assert_array_equal(start["initial_parameters"][key], value)
    np.testing.assert_array_equal(start["initial_raw_theta"], initial_raw())
    require(start["expected_steps"] == steps, "initial training budget changed")
    rows, snapshots, first = [], [], 1
    for end in ends:
        block = read(directory / f"history/steps_{first:04}_{end:04}.json")
        check_identity(block, fit_identity)
        require(
            block["first_step"] == first
            and block["last_step"] == end
            and len(block["rows"]) == end - first + 1,
            "training history partition changed",
        )
        rows.extend(block["rows"])
        snapshot = read(directory / f"progress/step_{end:04}.json")
        check_identity(snapshot, fit_identity)
        require(snapshot["completed_step"] == end, "progress step changed")
        parameters = arrays_from_json(snapshot["parameters"])
        require(
            parameter_digest(parameters) == snapshot["parameter_sha256"],
            "progress parameter digest mismatch",
        )
        np.testing.assert_array_equal(snapshot["raw_theta"], rows[-1]["raw_after"])
        snapshots.append(snapshot)
        first = end + 1
    raw, updates = check_history(rows, expected, protocol["training"], arm)
    checkpoint = read(directory / "checkpoint.json")
    require(
        checkpoint == snapshots[-1],
        "final checkpoint differs from last durable progress state",
    )
    parameters = arrays_from_json(checkpoint["parameters"])
    np.testing.assert_array_equal(raw, checkpoint["raw_theta"])
    theta, _ = physical(raw)
    original_theta, _ = physical(initial_raw())
    change = float(
        np.sqrt(
            sum(np.sum((parameters[key] - initial[key]) ** 2) for key in parameters)
        )
    )
    require(change > 0, "claimed training did not change weights")
    if arm == "meta_theta":
        require(
            np.all(
                np.abs(theta - original_theta)
                > protocol["audit"]["minimum_meta_parameter_change"]
            ),
            "not all three surrogate parameters actually updated",
        )
    else:
        np.testing.assert_array_equal(
            raw, initial_raw(), err_msg="fixed surrogate parameters drifted"
        )
    family = "standard" if arm == "standard" else "first_passage"
    checkpoint_sha = sha(directory / "checkpoint.json")
    neural = read(directory / "neural.json")
    require(
        neural == model_payload(parameters, raw, family, checkpoint_sha),
        "deployed model is not the actual trained checkpoint",
    )
    require(
        checkpoint_sha == record["checkpoint_sha256"]
        and sha(directory / "neural.json") == record["neural_sha256"],
        "phase model identity changed",
    )
    summary = read(directory / "TRAINING.json")
    check_identity(summary, fit_identity)
    config = protocol["training"]
    expected_summary = {
        "outer_steps": steps,
        "support_updates": steps,
        "query_weight_updates": steps,
        "query_weight_learning_rate": config["query_weight_learning_rate"],
        "actual_neural_cell_updates": updates,
        "surrogate_scalar_evaluations": 2 * updates,
        "parameter_count": 57,
        "neural_parameter_count": 57,
        "trainable_surrogate_parameters": 3 if arm == "meta_theta" else 0,
        "total_trainable_scalars": 60 if arm == "meta_theta" else 57,
        "weight_change_l2": change,
        "parameter_sha256": parameter_digest(parameters),
        "initial_theta": dict(zip(PARAMETER_NAMES, original_theta.tolist())),
        "final_theta": dict(zip(PARAMETER_NAMES, theta.tolist())),
        "physical_theta_change": dict(
            zip(PARAMETER_NAMES, (theta - original_theta).tolist())
        ),
        "checkpoint_sha256": checkpoint_sha,
        "neural_sha256": sha(directory / "neural.json"),
        "outer_optimizer": {
            "kind": "adam",
            "beta1": ADAM_BETA1,
            "beta2": ADAM_BETA2,
            "epsilon": ADAM_EPSILON,
            "learning_rate": config["outer_learning_rate"],
        },
    }
    require(
        all(summary.get(key) == value for key, value in expected_summary.items()),
        "training summary disagrees with actual checkpoint/history/work",
    )
    for item, fields in (
        (summary, ("training_wall_seconds", "training_cpu_seconds")),
        (complete, ("fit_wall_seconds", "fit_cpu_seconds")),
    ):
        require(
            all(np.isfinite(item[key]) and item[key] >= 0 for key in fields),
            "invalid recorded computation cost",
        )
    inputs = {
        f"{relative}/{name}": digest for name, digest in complete["files"].items()
    }
    inputs[f"{relative}/COMPLETE.json"] = record["complete_sha256"]
    return (
        {
            "seed": seed,
            "arm": arm,
            "weight_change_l2": change,
            "theta_change": (theta - original_theta).tolist(),
            "actual_neural_cell_updates": updates,
            "history_rows_verified": len(rows),
            "checkpoint_sha256": checkpoint_sha,
        },
        parameters,
        raw,
        inputs,
    )


def audit_phase(root, source_seal, output):
    started, cpu_started = time.perf_counter(), time.process_time()
    source = verify(source_seal)
    root = Path(root)
    protocol = read(PROTOCOL_PATH)
    validate_protocol(protocol)
    index, start = read(root / "INDEX.json"), read(root / "START.json")
    phase = index["phase"]
    require(
        phase in ("screening", "confirmation") and index.get("complete") is True,
        "incomplete or unregistered learning phase",
    )
    identity = {
        "phase": phase,
        "source_seal_sha256": sha(source_seal),
        "protocol_sha256": sha(PROTOCOL_PATH),
    }
    check_identity(index, identity)
    check_identity(start, identity)
    require(
        start["seeds"] == protocol[f"{phase}_seeds"] and start["arms"] == list(ARMS),
        "phase start roster changed",
    )
    roster = [(seed, arm) for seed in protocol[f"{phase}_seeds"] for arm in ARMS]
    require(
        [(row["seed"], row["arm"]) for row in index["fits"]] == roster
        and index["fit_count"] == len(roster)
        and start["expected_fits"] == len(roster),
        "missing, duplicate or reordered registered fit roster",
    )
    expected = {
        seed: expected_schedule(seed, protocol) for seed in protocol[f"{phase}_seeds"]
    }
    records, hyper_checks = [], []
    original_files = {name: sha(root / name) for name in ("START.json", "INDEX.json")}
    for record in index["fits"]:
        result, parameters, raw, inputs = audit_fit(
            root, record, identity, protocol, expected[record["seed"]]
        )
        original_files.update(inputs)
        records.append(result)
        if record["arm"] == "meta_theta":
            config = protocol["audit"]
            batches = [
                make_batch(
                    record["seed"],
                    config["hypergradient_probe_task_index"],
                    split,
                    config["hypergradient_probe_context"],
                    config["hypergradient_probe_episodes"],
                )
                for split in ("support", "query")
            ]
            checks = [
                check_hypergradient(
                    parameters,
                    raw,
                    *batches,
                    epsilon=epsilon,
                    inner_rate=protocol["training"]["inner_learning_rate"],
                    clip=protocol["training"]["gradient_norm_clip"],
                )
                for epsilon in config["hypergradient_epsilons"]
            ]
            require(
                all(
                    item["max_scaled_error"] <= config["hypergradient_max_scaled_error"]
                    for item in checks
                ),
                "final-checkpoint full-resolve hypergradient check failed",
            )
            hyper_checks.append(
                {
                    "seed": record["seed"],
                    "checkpoint_sha256": result["checkpoint_sha256"],
                    "checks": checks,
                }
            )
    final_source = verify(source_seal)
    require(
        source == final_source and sha(PROTOCOL_PATH) == identity["protocol_sha256"],
        "source/protocol changed during checkpoint audit",
    )
    require(
        all(sha(root / name) == digest for name, digest in original_files.items()),
        "original training evidence changed during audit",
    )
    result = {
        "schema": "hepta.adaptive-neuron.learning-audit.v2",
        **identity,
        "source": final_source,
        "training_index_sha256": original_files["INDEX.json"],
        "passed": True,
        "fits_verified": len(records),
        "fit_records": records,
        "shared_causal_schedule_verified": True,
        "optimizer_and_history_verified": True,
        "deployed_models_rebuilt_from_checkpoints": True,
        "raw_files_unchanged": True,
        "raw_files_verified": len(original_files),
        "hypergradient_checks": hyper_checks,
        "hypergradient_probe_cell_updates": sum(
            check["actual_neural_cell_updates"]
            for seed in hyper_checks
            for check in seed["checks"]
        ),
        "audit_wall_seconds": time.perf_counter() - started,
        "audit_cpu_seconds": time.process_time() - cpu_started,
        "scope": "Independent raw-data hash and optimizer-history reconstruction, checkpoint/model/work checks and full-update derivative probes. Does not rerun the training trajectory or establish efficacy superiority. Timing includes these computations and source verification, excluding process import/startup and final receipt write.",
    }
    write_json_exclusive(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_phase(args.root, args.source_seal, args.output)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "fits_verified": result["fits_verified"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
