"""Read-only second review of the frozen adaptive-neuron training evidence.

This is review evidence, outside the registered source closure. No training is
rerun. Registered derivative probe objectives are reevaluated at final weights.
"""

import time

STARTED = time.perf_counter()
CPU_STARTED = time.process_time()

import hashlib
import json
import math
import os
from pathlib import Path
import sys
import traceback

import numpy as np


REPO = Path(__file__).resolve().parents[4]
RUN = Path("/dev/shm/hepta-adaptive-v2-batch001/scientific001")
DEST = Path(__file__).resolve().parent / "training"
SEAL = REPO / "experiments/adaptive_neuron_v2/results/registration001/SOURCE_SEAL.json"
PROTOCOL = REPO / "experiments/adaptive_neuron_v2/PROTOCOL.json"
INPUTS = {}
NAMES = ("mu", "sigma", "lambda")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    value = path.read_bytes()
    INPUTS[str(path)] = hashlib.sha256(value).hexdigest()
    return json.loads(value)


def publish(path, value):
    data = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    if len(data) > 512000:
        raise ValueError("bounded review artifact exceeded")
    with Path(path).open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def close(first, second, message, atol=2e-12):
    a, b = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    require(
        a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), message
    )
    require(np.all(np.abs(a - b) <= atol * (1 + np.abs(b))), message)


def physical(raw):
    return np.array(
        [
            1.25 * math.tanh(raw[0]),
            0.35 + 1.65 / (1 + math.exp(-raw[1])),
            0.01 + 0.99 / (1 + math.exp(-raw[2])),
        ]
    )


def vector(parameters):
    require(set(parameters) == {"weights", "readout", "bias"}, "parameter fields")
    require(np.shape(parameters["weights"]) == (6, 8), "weight shape")
    require(np.shape(parameters["readout"]) == (8,), "readout shape")
    require(np.shape(parameters["bias"]) == (1,), "bias shape")
    result = np.concatenate(
        [np.asarray(parameters[k]).ravel() for k in sorted(parameters)]
    )
    require(len(result) == 57 and np.isfinite(result).all(), "finite 57 scalars")
    return result


def parameter_digest(parameters):
    h = hashlib.sha256()
    for key in sorted(parameters):
        h.update(key.encode())
        h.update(np.asarray(parameters[key], dtype=np.float64).tobytes())
    return h.hexdigest()


def review():
    cfg = read(PROTOCOL)
    seal = read(SEAL)
    seal_sha = digest(SEAL)
    require(
        seal["source_commit"] == "58c1f6caabd28ad99f2d425cfaa5c4e050f7a19a",
        "source commit",
    )
    for name, identity in seal["inputs"].items():
        path = REPO / name
        require(
            path.stat().st_size == identity["bytes"]
            and digest(path) == identity["sha256"],
            f"source {name}",
        )
        INPUTS[str(path)] = identity["sha256"]
    train = cfg["training"]
    records, phase_records, gradients = [], [], []
    shared_schedule = {}
    meta_checkpoints = []
    for phase in ("screening", "confirmation"):
        phase_root = RUN / "learning" / phase
        index = read(phase_root / "INDEX.json")
        audit_path = RUN / f"LEARNING_AUDIT_{phase}.json"
        audit = read(audit_path)
        seeds = cfg[f"{phase}_seeds"]
        require(index["complete"] and audit["passed"], "complete registered phase")
        require(
            [(r["seed"], r["arm"]) for r in index["fits"]]
            == [(s, a) for s in seeds for a in train["arms"]],
            "fit roster",
        )
        require(
            audit["training_index_sha256"] == digest(phase_root / "INDEX.json"),
            "audit/index binding",
        )
        require(
            index["source_seal_sha256"] == audit["source_seal_sha256"] == seal_sha,
            "phase source binding",
        )
        require(
            index["protocol_sha256"] == audit["protocol_sha256"] == digest(PROTOCOL),
            "protocol binding",
        )
        audit_fits = {(r["seed"], r["arm"]): r for r in audit["fit_records"]}
        audit_gradients = {g["seed"]: g for g in audit["hypergradient_checks"]}
        require(set(audit_gradients) == set(seeds), "gradient seed roster")
        for entry in index["fits"]:
            seed, arm = entry["seed"], entry["arm"]
            directory = phase_root / entry["directory"]
            complete = read(directory / "COMPLETE.json")
            require(
                complete["complete"]
                and digest(directory / "COMPLETE.json") == entry["complete_sha256"],
                "fit complete binding",
            )
            for name, expected in complete["files"].items():
                path = directory / name
                require(digest(path) == expected, f"immutable fit artifact {path}")
                INPUTS[str(path)] = expected
            start = read(directory / "START.json")
            check = read(directory / "checkpoint.json")
            neural = read(directory / "neural.json")
            summary = read(directory / "TRAINING.json")
            require(
                check == read(directory / "progress/step_0128.json"),
                "last progress checkpoint",
            )
            require(
                check["completed_step"] == train["outer_steps"] == 128,
                "full update budget",
            )
            require(
                check["seed"] == seed
                and check["arm"] == arm
                and check["phase"] == phase,
                "checkpoint identity",
            )
            require(
                digest(directory / "checkpoint.json") == entry["checkpoint_sha256"],
                "checkpoint digest",
            )
            require(
                parameter_digest(check["parameters"]) == check["parameter_sha256"],
                "parameter byte digest",
            )
            require(
                digest(directory / "neural.json") == entry["neural_sha256"],
                "neural digest",
            )
            require(
                neural["training_checkpoint_sha256"] == entry["checkpoint_sha256"],
                "deployed checkpoint identity",
            )
            for name in ("weights", "readout"):
                require(neural[name] == check["parameters"][name], f"neural {name}")
            require(neural["bias"] == check["parameters"]["bias"][0], "neural bias")
            close(neural["thresholds"], np.linspace(0.7, 1.4, 8), "thresholds")
            rows = []
            for block in sorted((directory / "history").glob("*.json")):
                rows.extend(read(block)["rows"])
            require(len(rows) == 128, "full raw history")
            raw = np.array(start["initial_raw_theta"])
            initial_physical = physical(raw)
            close(initial_physical, [0.25, 1, 0.1], "registered initial theta")
            initial_parameters = vector(start["initial_parameters"])
            final_parameters = vector(check["parameters"])
            first = np.zeros(3)
            second = np.zeros(3)
            cell_updates, changed_steps = 0, np.zeros(3, dtype=int)
            hyperclips, projections, innerclips, queryclips = 0, 0, 0, 0
            min_jacobian, max_inverse_delta = math.inf, 0.0
            for t, row in enumerate(rows, 1):
                require(row["step"] == t, "ordered raw history")
                close(row["raw_before"], raw, "optimizer continuity")
                signature = [
                    row[k]
                    for k in (
                        "context",
                        "support_dataset_sha256",
                        "query_dataset_sha256",
                    )
                ]
                key = (phase, seed, t)
                if key in shared_schedule:
                    require(
                        signature == shared_schedule[key],
                        "same training information across arms",
                    )
                else:
                    shared_schedule[key] = signature
                hyper = np.array(row["hypergradient"])
                require(
                    hyper.shape == (3,) and np.isfinite(hyper).all(),
                    "finite three-component hypergradient",
                )
                norm = math.sqrt(sum(float(x * x) for x in hyper))
                close(norm, row["hypergradient_norm"], "hypergradient norm")
                require(
                    row["hypergradient_clipped"] == (norm > 1.0),
                    "hypergradient clip condition",
                )
                hyperclips += row["hypergradient_clipped"]
                innerclips += row["inner_update"]["gradient_clipped"]
                queryclips += row["query_weight_update"]["gradient_clipped"]
                direction = np.zeros(3)
                after = raw.copy()
                if arm == "meta_theta":
                    g = hyper * min(1.0, 1.0 / max(norm, 1e-300))
                    first = 0.9 * first + (1 - 0.9) * g
                    second = 0.999 * second + (1 - 0.999) * g * g
                    direction = (first / (1 - 0.9**t)) / (
                        np.sqrt(second / (1 - 0.999**t)) + 1e-8
                    )
                    proposed = raw - 0.02 * direction
                    projections += int(np.sum(np.abs(proposed) >= 6))
                    after = np.clip(proposed, -6, 6)
                else:
                    require(
                        np.array_equal(hyper, np.zeros(3)), "non-meta hypergradient"
                    )
                close(row["outer_first_moment"], first, "Adam first moment")
                close(row["outer_second_moment"], second, "Adam second moment")
                close(
                    row["outer_bias_corrected_direction"],
                    direction,
                    "Adam bias correction",
                )
                close(row["raw_after"], after, "Adam/projected raw update")
                changed_steps += np.abs(after - raw) > 0
                raw = after
                theta = physical(raw)
                close(
                    [row["physical_after"][n] for n in NAMES],
                    theta,
                    "physical parameter transform",
                )
                min_jacobian = min(
                    min_jacobian, row["minimum_parameterization_jacobian"]
                )
                max_inverse_delta = max(
                    max_inverse_delta, row["inverse_diffusion_discriminant"]
                )
                for split, count in [("support", 64), ("query", 64)]:
                    work = row[f"{split}_work"]
                    expected = count * int(row["context"][2]) * 8
                    require(work["cell_updates"] == expected, "actual cell count")
                    require(
                        work["soft_forward"] == (split == "query"),
                        "hard support / soft query",
                    )
                    cell_updates += expected
                require(
                    row["query_weight_learning_rate"] == 0.01,
                    "same query training rule",
                )
                require(
                    math.isfinite(row["support_hard_bce"])
                    and math.isfinite(row["query_fixed_soft_bce"]),
                    "finite losses",
                )
            close(raw, check["raw_theta"], "final raw checkpoint")
            theta = physical(check["raw_theta"])
            change = theta - initial_physical
            close(
                [neural["surrogate"][n] for n in NAMES],
                theta,
                "exported physical theta",
            )
            close([summary["final_theta"][n] for n in NAMES], theta, "summary theta")
            weight_change = float(np.linalg.norm(final_parameters - initial_parameters))
            require(weight_change > 0, "trained weights changed")
            close(weight_change, summary["weight_change_l2"], "summary weight change")
            require(
                cell_updates == summary["actual_neural_cell_updates"],
                "summary actual work",
            )
            if arm == "meta_theta":
                require(
                    np.all(np.abs(change) > 1e-8), "all three meta parameters changed"
                )
                meta_checkpoints.append((seed, check, audit_gradients[seed]))
            else:
                require(
                    np.array_equal(
                        np.array(check["raw_theta"]),
                        np.array(start["initial_raw_theta"]),
                    ),
                    "fixed theta unchanged",
                )
            ar = audit_fits[seed, arm]
            close(ar["theta_change"], change, "audit theta change")
            close(ar["weight_change_l2"], weight_change, "audit weight change")
            require(
                ar["checkpoint_sha256"] == entry["checkpoint_sha256"],
                "audit checkpoint binding",
            )
            records.append(
                {
                    "phase": phase,
                    "seed": seed,
                    "arm": arm,
                    "checkpoint_sha256": entry["checkpoint_sha256"],
                    "physical_initial": initial_physical.tolist(),
                    "physical_final": theta.tolist(),
                    "physical_change": change.tolist(),
                    "weight_change_l2": weight_change,
                    "step_count": len(rows),
                    "parameter_update_steps": changed_steps.tolist(),
                    "actual_neural_cell_updates": cell_updates,
                    "hypergradient_clips": hyperclips,
                    "raw_projection_scalars": projections,
                    "support_gradient_clips": innerclips,
                    "query_gradient_clips": queryclips,
                    "minimum_recorded_transform_jacobian": min_jacobian,
                    "maximum_recorded_inverse_discriminant": max_inverse_delta,
                }
            )
        phase_records.append(
            {
                "phase": phase,
                "fit_count": len(index["fits"]),
                "index_sha256": digest(phase_root / "INDEX.json"),
                "audit_sha256": digest(audit_path),
            }
        )
    # The following probe repeats the registered objective, bypassing both the
    # audit and check_hypergradient helpers. Analytic values are the bound raw
    # audit artifacts; finite differences are recomputed from support adaptation.
    sys.path.insert(0, str(REPO))
    from experiments.adaptive_neuron_v2.learning.network import loss_gradient
    from experiments.adaptive_neuron_v2.learning.task import make_batch

    probe_cells = 0
    for seed, checkpoint, recorded in meta_checkpoints:
        require(
            recorded["checkpoint_sha256"]
            == next(
                r["checkpoint_sha256"]
                for r in records
                if r["seed"] == seed and r["arm"] == "meta_theta"
            ),
            "gradient/checkpoint binding",
        )
        require(
            [c["epsilon"] for c in recorded["checks"]]
            == cfg["audit"]["hypergradient_epsilons"],
            "epsilon roster",
        )
        parameters = {
            k: np.array(v, dtype=float) for k, v in checkpoint["parameters"].items()
        }
        raw = np.array(checkpoint["raw_theta"])
        support = make_batch(seed, 900001, "support", [0.68, 0.06, 10], 8)
        query = make_batch(seed, 900001, "query", [0.68, 0.06, 10], 8)
        for check in recorded["checks"]:
            eps = check["epsilon"]
            analytic = np.array(check["analytic"])
            recorded_fd = np.array(check["full_update_difference"])
            recorded_error = float(
                np.max(np.abs(analytic - recorded_fd) / (1 + np.abs(recorded_fd)))
            )
            close(
                recorded_error,
                check["max_scaled_error"],
                "reported FD error",
                atol=1e-18,
            )
            require(recorded_error <= 2e-7, "registered gradient tolerance")
            finite = np.zeros(3)
            for dimension in range(3):
                objectives = []
                for sign in (-1, 1):
                    shifted = raw.copy()
                    shifted[dimension] += sign * eps
                    _, g, _, support_work = loss_gradient(
                        parameters,
                        support,
                        shifted,
                        family="first_passage",
                        soft=False,
                        mixed=False,
                    )
                    norm = math.sqrt(sum(float(np.sum(v * v)) for v in g.values()))
                    scale = min(1.0, 5.0 / max(norm, 1e-300))
                    adapted = {
                        k: np.clip(
                            parameters[k] - 0.03 * scale * g[k],
                            -6 if k == "bias" else -3,
                            6 if k == "bias" else 3,
                        )
                        for k in parameters
                    }
                    loss, _, _, query_work = loss_gradient(
                        adapted,
                        query,
                        shifted,
                        family="standard",
                        soft=True,
                        mixed=False,
                    )
                    objectives.append(loss)
                    probe_cells += (
                        support_work["cell_updates"] + query_work["cell_updates"]
                    )
                finite[dimension] = (objectives[1] - objectives[0]) / (2 * eps)
            close(
                finite,
                recorded_fd,
                "independently reevaluated objective derivative",
                atol=3e-10,
            )
            error = float(np.max(np.abs(analytic - finite) / (1 + np.abs(finite))))
            require(error <= 2e-7, "recomputed full adaptation derivative")
            gradients.append(
                {
                    "seed": seed,
                    "checkpoint_sha256": recorded["checkpoint_sha256"],
                    "epsilon": eps,
                    "analytic": analytic.tolist(),
                    "reevaluated_finite_difference": finite.tolist(),
                    "max_scaled_error": error,
                    "reported_error": recorded_error,
                    "same_component_signs": bool(
                        np.all(np.sign(analytic) == np.sign(finite))
                    ),
                }
            )
    require(
        len(records) == 45 and len(meta_checkpoints) == 15 and len(gradients) == 45,
        "complete frozen roster",
    )
    require(
        all(digest(p) == h for p, h in INPUTS.items()),
        "read evidence and source unchanged during review",
    )
    meta = [r for r in records if r["arm"] == "meta_theta"]
    return {
        "schema": "hepta.adaptive-neuron.independent-training-review.v1",
        "passed": True,
        "source_commit": seal["source_commit"],
        "source_seal_sha256": seal_sha,
        "protocol_sha256": digest(PROTOCOL),
        "phase_records": phase_records,
        "fits": records,
        "meta_fit_count": len(meta),
        "gradient_checks": gradients,
        "minimum_absolute_meta_change_by_parameter": np.min(
            np.abs([r["physical_change"] for r in meta]), axis=0
        ).tolist(),
        "maximum_gradient_scaled_error": max(g["max_scaled_error"] for g in gradients),
        "independent_probe_full_adaptations": 270,
        "independent_probe_actual_cell_updates": probe_cells,
        "evidence_unchanged": True,
        "same_information_across_arms": True,
        "scope": "Independent raw history, checkpoint, optimizer and physical-transform reconstruction for all 45 fits. Reevaluate 270 support-update/query objectives at the 15 frozen final checkpoints, using frozen network/task primitives but neither audit nor check_hypergradient. This does not rerun training, prove hard-step differentiability, verify a different kernel implementation, or establish efficacy.",
    }


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=False)
    publish(
        DEST / "START.json",
        {
            "script_sha256": digest(__file__),
            "run": str(RUN),
            "scope": "From first script statements before substantive imports; excludes Python interpreter startup, prior interactive inspection and script authoring.",
        },
    )
    try:
        result = review()
        publish(DEST / "REVIEW.json", result)
        publish(DEST / "INPUT_HASHES.json", INPUTS)
        publish(
            DEST / "COMPLETE.json",
            {
                "passed": True,
                "review_sha256": digest(DEST / "REVIEW.json"),
                "input_hashes_sha256": digest(DEST / "INPUT_HASHES.json"),
                "wall_seconds": time.perf_counter() - STARTED,
                "cpu_seconds": time.process_time() - CPU_STARTED,
                "scope": "Own Python process including imports, raw verification and repeated registered derivative objectives. Excludes final receipt write; not additive to original science costs.",
            },
        )
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "passed",
                        "meta_fit_count",
                        "minimum_absolute_meta_change_by_parameter",
                        "maximum_gradient_scaled_error",
                        "independent_probe_actual_cell_updates",
                    )
                }
            )
        )
    except BaseException:
        publish(
            DEST / "FAILED.json",
            {
                "passed": False,
                "traceback": traceback.format_exc(),
                "wall_seconds": time.perf_counter() - STARTED,
                "cpu_seconds": time.process_time() - CPU_STARTED,
            },
        )
        raise
