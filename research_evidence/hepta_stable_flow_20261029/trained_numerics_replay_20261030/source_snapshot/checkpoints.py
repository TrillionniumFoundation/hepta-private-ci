"""Register and execute a separate, read-only trained-checkpoint appendix.

Keep this package outside call_put_stable_flow: its production source set is
sealed by the formal study. This script never changes that source, weights,
selection or primary scores and never loads validation/test examples.
"""

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import scipy
import torch
from torch.nn import functional as F

from experiments.call_put_stable_flow import audit, study
from experiments.call_put_stable_flow.data import TaskConfig, generate
from experiments.call_put_stable_flow.models import ModelConfig, build_model

PACKAGE = Path(__file__).resolve().parent
SPECIFICATION = PACKAGE / "PROTOCOL_SPEC.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def save_arrays(path, arrays):
    with Path(path).open("xb") as stream:
        np.savez_compressed(stream, **arrays)


def appendix_sources():
    return {
        name: sha(PACKAGE / name) for name in ("checkpoints.py", "PROTOCOL_SPEC.json")
    }


def register(formal, output):
    protocol = study._verify_protocol(formal)
    if any((formal / name).exists() for name in ("selection.json", "results.json")):
        raise RuntimeError(
            "Appendix must be registered before validation selection/test scores"
        )
    if any((formal / "candidates").glob("*/*.npz")):
        raise RuntimeError(
            "This registration contract requires registration before training"
        )
    specification = json.loads(SPECIFICATION.read_text())
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "source_snapshot"
    snapshot.mkdir()
    for name in appendix_sources():
        shutil.copy2(PACKAGE / name, snapshot / name)
    diagnostic = output / "diagnostic_data"
    diagnostic.mkdir()
    data_receipts = {}
    for task in specification["scope"]["tasks"]:
        data = study._verified_data(formal, task, "train")
        indices = specification["diagnostic_data"]["episode_indices"]
        arrays = {name: value[indices].numpy() for name, value in data.items()}
        save_arrays(diagnostic / f"{task}.npz", arrays)
        data_receipts[task] = {
            "registered_file": f"diagnostic_data/{task}.npz",
            "registered_sha256": sha(diagnostic / f"{task}.npz"),
            "formal_train_file_sha256": sha(formal / "data" / task / "train.npz"),
            "episode_indices": indices,
        }
    registered = {
        **specification,
        "registered_unix": time.time(),
        "formal_study": str(formal.resolve()),
        "formal_protocol_sha256": sha(formal / "protocol.json"),
        "formal_freeze_seal_sha256": sha(formal / "freeze_seal.json"),
        "formal_source_sha256": protocol["source_sha256"],
        "formal_registered_max_step": protocol["model_config"]["max_step"],
        "appendix_source_sha256": appendix_sources(),
        "registered_data": data_receipts,
        "environment": {
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "torch": torch.__version__,
        },
    }
    write_json(output / "protocol.json", registered)
    write_json(
        output / "registration_seal.json",
        {
            "protocol_sha256": sha(output / "protocol.json"),
            "registered_before_candidate_weights": True,
            "registered_before_selection": True,
            "registered_before_test_scores": True,
            "created_unix": time.time(),
        },
    )
    return {
        "status": "registered_before_training_selection_test",
        "output": str(output),
        "protocol_sha256": sha(output / "protocol.json"),
        "registration_seal_sha256": sha(output / "registration_seal.json"),
    }


def verify_registration(formal, output):
    seal = json.loads((output / "registration_seal.json").read_text())
    if sha(output / "protocol.json") != seal["protocol_sha256"]:
        raise RuntimeError("Registered appendix protocol changed")
    registration = json.loads((output / "protocol.json").read_text())
    core = study._verify_protocol(formal)
    if (
        sha(formal / "protocol.json") != registration["formal_protocol_sha256"]
        or sha(formal / "freeze_seal.json") != registration["formal_freeze_seal_sha256"]
        or appendix_sources() != registration["appendix_source_sha256"]
    ):
        raise RuntimeError("A core/appendix source or seal changed after registration")
    for row in registration["registered_data"].values():
        if sha(output / row["registered_file"]) != row["registered_sha256"]:
            raise RuntimeError("A registered diagnostic input changed")
    return registration, core


def read_arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name].copy() for name in archive.files}


def make_model(alias, core, checkpoint, dtype=torch.float32, max_step=None):
    model = build_model(
        alias["arm"],
        alias["seed"],
        ModelConfig(**core["model_config"]),
        TaskConfig(**core["task_contract"]["config"]),
    )
    study._load_weights(model, checkpoint)
    model = model.to(dtype=dtype).eval()
    if max_step is not None:
        model.flow.max_step = max_step
    return model


def full_observation(model, arrays):
    dtype = next(model.parameters()).dtype
    inputs = torch.from_numpy(arrays["inputs"]).to(dtype=dtype)
    dt = torch.from_numpy(arrays["dt"]).to(dtype=dtype)
    labels = torch.from_numpy(arrays["targets"])
    logits, diagnostic = model(inputs, dt, return_diagnostics=True)
    loss = F.cross_entropy(logits[labels != -100], labels[labels != -100])
    members = list(model.named_parameters())
    gradients = torch.autograd.grad(loss, tuple(parameter for _, parameter in members))
    groups = {
        name: group
        for group, items in model.parameter_groups().items()
        for name, _ in items
    }
    layout, cursor = [], 0
    for name, parameter in members:
        layout.append(
            {
                "name": name,
                "group": groups[name],
                "shape": list(parameter.shape),
                "start": cursor,
                "stop": cursor + parameter.numel(),
            }
        )
        cursor += parameter.numel()
    observations = {
        "loss": loss.detach().cpu().numpy(),
        "logits": logits.detach().cpu().numpy(),
        "flow_rate_trace": diagnostic["flow_rate_trace"].detach().cpu().numpy(),
        "final_flow_state": torch.stack(diagnostic["final_state"])
        .detach()
        .cpu()
        .numpy(),
        "final_memory": diagnostic["final_memory"].detach().cpu().numpy(),
        "gradient": torch.cat([value.flatten() for value in gradients])
        .detach()
        .cpu()
        .numpy(),
    }
    if not all(np.isfinite(value).all() for value in observations.values()):
        raise FloatingPointError("Nonfinite checkpoint diagnostic")
    return observations, layout


def vector_comparison(observed, reference, floor=1e-8):
    left, right = (
        np.asarray(observed, dtype=np.float64),
        np.asarray(reference, dtype=np.float64),
    )
    left_norm, right_norm = float(np.linalg.norm(left)), float(np.linalg.norm(right))
    absolute = float(np.linalg.norm(left - right))
    return {
        "observed_norm": left_norm,
        "reference_norm": right_norm,
        "absolute_l2_difference": absolute,
        "relative_l2_difference": absolute / max(floor, right_norm),
        "reference_below_denominator_floor": right_norm < floor,
        "cosine": float(np.dot(left, right) / (left_norm * right_norm))
        if min(left_norm, right_norm) >= floor
        else None,
    }


def compare_full(observed, reference, layout, gate, floor):
    groups = {
        "all": vector_comparison(observed["gradient"], reference["gradient"], floor)
    }
    for group in ("content", "boundary_input", "boundary_dynamics", "rate_head"):
        indices = np.concatenate(
            [
                np.arange(row["start"], row["stop"])
                for row in layout
                if row["group"] == group
            ]
        )
        groups[group] = vector_comparison(
            observed["gradient"][indices], reference["gradient"][indices], floor
        )
    difference = observed["logits"].astype(np.float64) - reference["logits"].astype(
        np.float64
    )
    scaled = float(np.max(np.abs(difference) / (1 + np.abs(reference["logits"]))))
    gradient_gate = gate["gradient_relative_l2_max_full_and_each_group"]
    result = {
        "gradient": groups,
        "logit_scaled_max": scaled,
        "logit_max_absolute_difference": float(np.max(np.abs(difference))),
        "loss_absolute_difference": abs(
            float(observed["loss"]) - float(reference["loss"])
        ),
        "loss_scaled_difference": abs(
            float(observed["loss"]) - float(reference["loss"])
        )
        / (1 + abs(float(reference["loss"]))),
        "all_group_gradients_passed": all(
            row["relative_l2_difference"] <= gradient_gate for row in groups.values()
        ),
        "logits_passed": scaled <= gate["scaled_logit_max"],
    }
    for name in ("flow_rate_trace", "final_flow_state", "final_memory"):
        result[name + "_scaled_max"] = float(
            np.max(
                np.abs(
                    observed[name].astype(np.float64)
                    - reference[name].astype(np.float64)
                )
                / (1 + np.abs(reference[name]))
            )
        )
    result["passed"] = result["all_group_gradients_passed"] and result["logits_passed"]
    return result


def full_checkpoint(alias, core, checkpoint, data, folder, specification):
    h = core["model_config"]["max_step"]
    records, layout = {}, None
    for label, dtype, step in [
        ("fp32_h", torch.float32, h),
        ("fp64_h", torch.float64, h),
        ("fp64_h_over_2", torch.float64, h / 2),
        ("fp64_h_over_4", torch.float64, h / 4),
    ]:
        model = make_model(alias, core, checkpoint, dtype, step)
        records[label], current_layout = full_observation(model, data)
        if layout is not None and layout != current_layout:
            raise RuntimeError(
                "Parameter layout changed between precision/mesh evaluations"
            )
        layout = current_layout
        save_arrays(folder / f"{label}.npz", records[label])
    configuration = specification["end_to_end"]
    floor = configuration["comparison_denominator_floor"]
    comparisons = {}
    for name, left, right, gate_name in [
        ("same_h_precision", "fp32_h", "fp64_h", "same_h_precision"),
        (
            "reference_consistency",
            "fp64_h_over_2",
            "fp64_h_over_4",
            "reference_consistency_h_over_2_vs_h_over_4",
        ),
        ("registered_h_mesh", "fp64_h", "fp64_h_over_4", "registered_h_vs_h_over_4"),
    ]:
        comparisons[name] = compare_full(
            records[left], records[right], layout, configuration[gate_name], floor
        )
    status = (
        "reference_unresolved"
        if not comparisons["reference_consistency"]["passed"]
        else "passed"
        if all(row["passed"] for row in comparisons.values())
        else "failed"
    )
    return {
        "status": status,
        "registered_h": h,
        "parameter_layout": layout,
        "comparisons": comparisons,
        "reference_is_finite_mesh_not_continuous_truth": True,
    }


def independent_flow(alias, core, checkpoint, data, folder, specification):
    model = make_model(alias, core, checkpoint, torch.float64)
    flow = model.flow
    values = audit.snapshot(flow)
    drives = data["inputs"][0].astype(np.float64)
    dts = data["dt"][0].astype(np.float64)
    config = specification["independent_flow"]
    dimension = sum(value.size for value in values.values())
    directions = np.random.default_rng(config["directions"]["seed"]).normal(
        size=(config["directions"]["count"], dimension)
    )
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    oracle = audit.oracle_trajectory(values, alias["arm"], drives, dts)
    tight = audit.oracle_trajectory(values, alias["arm"], drives, dts, tight=True)
    finite_differences = []
    for epsilon in config["finite_difference_epsilons"]:
        finite_differences.append(
            np.array(
                [
                    (
                        audit.numpy_loss(
                            audit.oracle_trajectory(
                                audit.perturb(values, direction, epsilon),
                                alias["arm"],
                                drives,
                                dts,
                                tight=True,
                            )
                        )
                        - audit.numpy_loss(
                            audit.oracle_trajectory(
                                audit.perturb(values, direction, -epsilon),
                                alias["arm"],
                                drives,
                                dts,
                                tight=True,
                            )
                        )
                    )
                    / (2 * epsilon)
                    for direction in directions
                ]
            )
        )
    trace64, gradient64 = audit.directional_gradient(
        flow, drives, dts, directions, prepared=True
    )
    trace32, gradient32 = audit.directional_gradient(
        flow.float(), drives, dts, directions, prepared=True
    )
    arrays = {
        "directions": directions,
        "inputs": drives,
        "dt": dts,
        "oracle": oracle,
        "oracle_tight": tight,
        "fd_coarse": finite_differences[0],
        "fd_fine": finite_differences[1],
        "trace_fp64": trace64,
        "directional_gradient_fp64": gradient64,
        "trace_fp32": trace32,
        "directional_gradient_fp32": gradient32,
    }
    arrays.update({"parameter__" + name: value for name, value in values.items()})
    save_arrays(folder / "independent_flow_raw.npz", arrays)
    metrics = {
        "scaled_state_max": audit.scaled_state_error(trace64, tight),
        "directional_gradient_relative_l2": audit.relative_gradient_error(
            gradient64, finite_differences[1]
        ),
        "oracle_scaled_state_change": audit.scaled_state_error(oracle, tight),
        "oracle_fd_gradient_relative_change": audit.relative_gradient_error(
            finite_differences[0], finite_differences[1]
        ),
        "same_h_precision_scaled_state": audit.scaled_state_error(trace32, trace64),
        "same_h_precision_directional_gradient_relative": audit.relative_gradient_error(
            gradient32, gradient64
        ),
    }
    thresholds = config["thresholds"]
    reference_passed = all(
        metrics[name] <= thresholds[name]
        for name in ("oracle_scaled_state_change", "oracle_fd_gradient_relative_change")
    )
    passed = all(metrics[name] <= thresholds[name] for name in thresholds)
    physical = audit.oracle_parameters(values, alias["arm"])
    margin = tight[:, 0] - tight[:, 1] - physical["log_beta"]
    return {
        "status": "reference_unresolved"
        if not reference_passed
        else "passed"
        if passed
        else "failed",
        "metrics": metrics,
        "reference_passed": reference_passed,
        "gradient_reference_norm": float(np.linalg.norm(finite_differences[1])),
        "gradient_observed_norm": float(np.linalg.norm(gradient64)),
        "parameter_order": list(values),
        "direction_count": len(directions),
        "sampled_endpoint_margin_range": [float(margin.min()), float(margin.max())],
        "sampled_endpoint_sign_changes": int(
            np.count_nonzero(margin[1:] * margin[:-1] < 0)
        ),
        "loss_is_flow_trace_function_not_end_to_end_ce": True,
    }


def run(formal, output):
    specification, core = verify_registration(formal, output)
    selection_seal = json.loads((formal / "selection_seal.json").read_text())
    if sha(formal / "selection.json") != selection_seal["selection_sha256"]:
        raise RuntimeError("Validation selection changed after sealing")
    selected = json.loads((formal / "selection.json").read_text())["selected"]
    scope = specification["scope"]
    aliases = [row for row in selected if row["arm"] in scope["arms"]]
    combinations = {(r["task"], r["arm"], r["seed"], r["regime"]) for r in aliases}
    expected = {
        (task, arm, seed, regime)
        for task in scope["tasks"]
        for arm in scope["arms"]
        for seed in scope["seeds"]
        for regime in scope["regimes"]
    }
    if combinations != expected or len(aliases) != scope["expected_selected_aliases"]:
        raise RuntimeError("Selected aliases differ from the registered scope")
    grouped = {}
    for alias in aliases:
        key = (alias["task"], alias["arm"], alias["checkpoint_sha256"])
        grouped.setdefault(key, []).append(alias)
    execution = output / "execution"
    execution.mkdir(exist_ok=False)
    write_json(
        execution / "execution_binding.json",
        {
            "protocol_sha256": sha(output / "protocol.json"),
            "selection_sha256": sha(formal / "selection.json"),
            "selection_seal_sha256": sha(formal / "selection_seal.json"),
            "test_results_file_existed_at_start": (formal / "results.json").exists(),
            "test_examples_or_scores_read": False,
            "started_unix": time.time(),
        },
    )
    data = {
        task: read_arrays(output / row["registered_file"])
        for task, row in specification["registered_data"].items()
    }
    records = []
    for index, (identity, linked) in enumerate(sorted(grouped.items())):
        alias = min(
            linked, key=lambda row: (row["id"], row["checkpoint"], row["regime"])
        )
        checkpoint = formal / "candidates" / alias["id"] / f"{alias['checkpoint']}.npz"
        if sha(checkpoint) != alias["checkpoint_sha256"]:
            raise RuntimeError("Selected checkpoint bytes do not match selection")
        folder = execution / f"checkpoint_{index:03d}_{alias['checkpoint_sha256'][:12]}"
        folder.mkdir()
        tick = time.process_time()
        record = {
            "identity": list(identity),
            "aliases": linked,
            "checkpoint_relative_path": str(checkpoint.relative_to(formal)),
            "checkpoint_sha256": sha(checkpoint),
        }
        try:
            record["end_to_end"] = full_checkpoint(
                alias, core, checkpoint, data[alias["task"]], folder, specification
            )
            if any(
                row["seed"] == specification["independent_flow"]["seed"]
                for row in linked
            ):
                record["independent_flow"] = independent_flow(
                    alias, core, checkpoint, data[alias["task"]], folder, specification
                )
        except (RuntimeError, FloatingPointError, ValueError) as error:
            record["execution_error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        record["cpu_seconds"] = time.process_time() - tick
        record["raw_artifacts_sha256"] = {p.name: sha(p) for p in folder.glob("*.npz")}
        record["checkpoint_unchanged"] = sha(checkpoint) == record["checkpoint_sha256"]
        write_json(folder / "receipt.json", record)
        records.append(
            {
                "folder": str(folder.relative_to(output)),
                "receipt_sha256": sha(folder / "receipt.json"),
                **record,
            }
        )
        print(
            json.dumps(
                {
                    "physical_checkpoint": index + 1,
                    "of": len(grouped),
                    "end_to_end_status": record.get("end_to_end", {}).get("status"),
                    "flow_status": record.get("independent_flow", {}).get("status"),
                    "execution_error": record.get("execution_error"),
                    "cpu_seconds": record["cpu_seconds"],
                }
            ),
            flush=True,
        )
    verify_registration(formal, output)
    if sha(formal / "selection.json") != selection_seal["selection_sha256"]:
        raise RuntimeError("Selection changed during the numerical appendix")
    summary = {
        "registered_aliases": len(aliases),
        "physical_checkpoints": len(records),
        "dop_aliases": sum(
            row["seed"] == specification["independent_flow"]["seed"] for row in aliases
        ),
        "dop_physical_checkpoints": sum("independent_flow" in row for row in records),
        "execution_errors": sum("execution_error" in row for row in records),
        "primary_scores_or_selection_modified": False,
        "test_data_or_scores_read": False,
        "records": records,
    }
    write_json(execution / "summary.json", summary)
    return {
        "status": "appendix_complete_report_flags_without_reselection",
        "summary_sha256": sha(execution / "summary.json"),
        **{
            name: summary[name]
            for name in (
                "registered_aliases",
                "physical_checkpoints",
                "dop_aliases",
                "dop_physical_checkpoints",
                "execution_errors",
            )
        },
    }


def self_check(output):
    """Exercise the appendix on new, explicitly untrained development tensors."""
    output.mkdir(parents=True, exist_ok=False)
    specification = json.loads(SPECIFICATION.read_text())
    core = {
        "model_config": {
            "heads": 1,
            "key_dim": 16,
            "value_dim": 8,
            "max_step": 0.0625,
            "initial_leak": 1 / 512,
            "initial_write": 1.0,
        },
        "task_contract": {
            "config": {
                "length": 32,
                "key_vocab": 16,
                "value_vocab": 8,
                "selected": 4,
                "bindings": 6,
                "overwrites": 2,
            }
        },
    }
    alias = {"arm": "analytic", "seed": 20261029, "task": "mqar"}
    data = generate("mqar", 4, 982031)
    model = build_model(
        alias["arm"], alias["seed"], ModelConfig(**core["model_config"])
    )
    checkpoint = output / "untrained_development_parameters.npz"
    study._save_weights(checkpoint, model.state_dict())
    write_json(
        output / "protocol.json",
        {
            "development_only": True,
            "untrained": True,
            "formal_data_or_checkpoints_read": False,
            "sources": appendix_sources(),
            "specification_sha256": sha(SPECIFICATION),
            "core_configuration": core,
        },
    )
    save_arrays(output / "development_inputs.npz", data)
    result = {
        "development_only": True,
        "untrained": True,
        "end_to_end": full_checkpoint(
            alias, core, checkpoint, data, output, specification
        ),
        "independent_flow": independent_flow(
            alias, core, checkpoint, data, output, specification
        ),
    }
    write_json(output / "receipt.json", result)
    return {
        "status": "development_pipeline_executed",
        "end_to_end_status": result["end_to_end"]["status"],
        "flow_status": result["independent_flow"]["status"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("register", "run", "self-check"))
    parser.add_argument("--study", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if args.phase == "self-check":
        result = self_check(args.output)
    else:
        if args.study is None:
            parser.error("--study is required for register and run")
        result = (
            register(args.study, args.output)
            if args.phase == "register"
            else run(args.study, args.output)
        )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
