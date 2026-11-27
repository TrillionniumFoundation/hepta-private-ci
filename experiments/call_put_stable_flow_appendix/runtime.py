"""Pre-registered CPU full-sequence inference appendix, separate from core.

Registration may run during training. Actual timing requires all training and
the precision appendix to be complete and an explicit idle scheduling assertion.
No timing run loads validation/test examples or primary test score files. It
uses sealed validation-selection identities without filtering them by quality.
Quality is joined afterward without changing the measurement matrix.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import torch

from experiments.call_put_stable_flow import study
from experiments.call_put_stable_flow_appendix import checkpoints

PACKAGE = Path(__file__).resolve().parent
SPECIFICATION = PACKAGE / "RUNTIME_SPEC.json"
sha = checkpoints.sha
write_json = checkpoints.write_json
save_arrays = checkpoints.save_arrays


def sources():
    return {name: sha(PACKAGE / name) for name in ("runtime.py", "RUNTIME_SPEC.json")}


def register(formal, numerical, output):
    numerical_protocol, core = checkpoints.verify_registration(formal, numerical)
    if any((formal / name).exists() for name in ("selection.json", "results.json")):
        raise RuntimeError(
            "Runtime rules must be registered before validation/test scoring"
        )
    specification = json.loads(SPECIFICATION.read_text())
    output.mkdir(parents=True, exist_ok=False)
    (output / "source_snapshot").mkdir()
    for name in sources():
        shutil.copy2(PACKAGE / name, output / "source_snapshot" / name)
    (output / "diagnostic_data").mkdir()
    data_binding = {}
    for task in specification["scope"]["tasks"]:
        data = study._verified_data(formal, task, "train")
        arrays = {name: tensor[:32].numpy() for name, tensor in data.items()}
        path = output / "diagnostic_data" / f"{task}.npz"
        save_arrays(path, arrays)
        data_binding[task] = {
            "file": str(path.relative_to(output)),
            "sha256": sha(path),
            "formal_train_sha256": sha(formal / "data" / task / "train.npz"),
            "episode_indices": list(range(32)),
        }
    registered = {
        **specification,
        "registered_unix": time.time(),
        "formal_protocol_sha256": sha(formal / "protocol.json"),
        "formal_source_sha256": core["source_sha256"],
        "formal_freeze_seal_sha256": sha(formal / "freeze_seal.json"),
        "numerical_protocol_sha256": sha(numerical / "protocol.json"),
        "numerical_registration_seal_sha256": sha(numerical / "registration_seal.json"),
        "numerical_appendix_source_sha256": numerical_protocol[
            "appendix_source_sha256"
        ],
        "runtime_source_sha256": sources(),
        "data_binding": data_binding,
        "candidate_weights_existed_at_registration": any(
            (formal / "candidates").glob("*/*.npz")
        ),
        "selection_or_test_scores_existed_at_registration": False,
    }
    write_json(output / "protocol.json", registered)
    write_json(
        output / "registration_seal.json",
        {
            "protocol_sha256": sha(output / "protocol.json"),
            "registered_before_validation_test_scoring": True,
            "registered_before_runtime_execution": True,
            "does_not_modify_existing_precision_registration": True,
            "created_unix": time.time(),
        },
    )
    return {
        "status": "runtime_registered_not_executed",
        "protocol_sha256": sha(output / "protocol.json"),
        "registration_seal_sha256": sha(output / "registration_seal.json"),
        "output": str(output),
    }


def verify(formal, numerical, output):
    checkpoints.verify_registration(formal, numerical)
    seal = json.loads((output / "registration_seal.json").read_text())
    if sha(output / "protocol.json") != seal["protocol_sha256"]:
        raise RuntimeError("Runtime registration changed")
    registered = json.loads((output / "protocol.json").read_text())
    checks = {
        "formal_protocol_sha256": formal / "protocol.json",
        "formal_freeze_seal_sha256": formal / "freeze_seal.json",
        "numerical_protocol_sha256": numerical / "protocol.json",
        "numerical_registration_seal_sha256": numerical / "registration_seal.json",
    }
    if any(sha(path) != registered[name] for name, path in checks.items()):
        raise RuntimeError("A bound study/precision seal changed")
    if sources() != registered["runtime_source_sha256"]:
        raise RuntimeError("Runtime implementation changed after registration")
    for row in registered["data_binding"].values():
        if sha(output / row["file"]) != row["sha256"]:
            raise RuntimeError("Registered runtime inputs changed")
    return registered, study._verify_protocol(formal)


def state_payload(model, batch):
    """Count declared recurrent scalars, not allocator or peak-memory usage."""
    accounting = model.accounting()
    dtype = next(model.parameters()).dtype
    element_bytes = torch.empty((), dtype=dtype).element_size()
    float_bytes = accounting["persistent_float_state_per_episode"] * element_bytes
    type_bytes = {
        "int64": torch.empty((), dtype=torch.int64).element_size(),
        "bool": torch.empty((), dtype=torch.bool).element_size(),
    }
    discrete = {
        entry.split(":")[0]: {
            "dtype": entry.split(":")[1],
            "bytes": type_bytes[entry.split(":")[1]],
        }
        for entry in accounting["discrete_state_dtypes"]
    }
    discrete_bytes = sum(row["bytes"] for row in discrete.values())
    return {
        "model_accounting": accounting,
        "float_dtype": str(dtype),
        "float_element_bytes": element_bytes,
        "float_payload_bytes_per_episode": float_bytes,
        "discrete_components": discrete,
        "discrete_payload_bytes_per_episode": discrete_bytes,
        "total_counted_payload_bytes_per_episode": float_bytes + discrete_bytes,
        "batch_size": batch,
        "total_counted_payload_bytes_per_batch": batch * (float_bytes + discrete_bytes),
        "parameter_tensor_bytes": sum(
            p.numel() * p.element_size() for p in model.parameters()
        ),
        "not_a_measured_peak_memory_or_streaming_cache": True,
    }


def distribution(samples):
    samples = np.asarray(samples, dtype=np.float64)
    return {
        "mean": float(samples.mean()),
        "median": float(np.median(samples)),
        "sample_standard_deviation": float(samples.std(ddof=1)),
        "minimum": float(samples.min()),
        "maximum": float(samples.max()),
        "p25": float(np.quantile(samples, 0.25)),
        "p75": float(np.quantile(samples, 0.75)),
    }


def tensor_digest(tensor):
    array = tensor.detach().cpu().contiguous().numpy()
    if not np.isfinite(array).all():
        raise FloatingPointError("Nonfinite inference output")
    return hashlib.sha256(array.tobytes()).hexdigest()


def environment():
    cpu_model = platform.processor()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        cpu_model = next(
            (
                line.partition(":")[2].strip()
                for line in cpuinfo.read_text().splitlines()
                if line.startswith("model name")
            ),
            cpu_model,
        )
    return {
        "python": sys.version,
        "torch": torch.__version__,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "cpu_model": cpu_model,
        "os_cpu_count": os.cpu_count(),
        "allowed_cpu_affinity": sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "timers": {
            name: vars(time.get_clock_info(name))
            for name in ("process_time", "perf_counter")
        },
    }


def run(formal, numerical, output, idle_cpu_attested):
    if not idle_cpu_attested:
        raise RuntimeError(
            "Run only when the root scheduler attests idle CPU after all training and numerical checks"
        )
    registered, core = verify(formal, numerical, output)
    training_seal = json.loads((formal / "all_training_complete_seal.json").read_text())
    if len(training_seal["complete_sha256"]) != core["candidate_count"]:
        raise RuntimeError("Incomplete formal training set")
    for identifier, digest in training_seal["complete_sha256"].items():
        if sha(formal / "candidates" / identifier / "complete.json") != digest:
            raise RuntimeError("Training completion seal mismatch")
    selection_seal = json.loads((formal / "selection_seal.json").read_text())
    if sha(formal / "selection.json") != selection_seal["selection_sha256"]:
        raise RuntimeError("Validation selection seal mismatch")
    numerical_summary_path = numerical / "execution" / "summary.json"
    numerical_summary = json.loads(numerical_summary_path.read_text())
    if (
        numerical_summary["registered_aliases"] != 24
        or numerical_summary["execution_errors"] != 0
    ):
        raise RuntimeError("Precision appendix is not complete")
    numerical_binding = json.loads(
        (numerical / "execution" / "execution_binding.json").read_text()
    )
    if numerical_binding["selection_sha256"] != selection_seal["selection_sha256"]:
        raise RuntimeError("Precision and runtime selections differ")
    selected = json.loads((formal / "selection.json").read_text())["selected"]
    scope = registered["scope"]
    aliases = [
        row
        for row in selected
        if row["seed"] == scope["seed"] and row["arm"] in scope["arms"]
    ]
    expected = {
        (task, arm, regime)
        for task in scope["tasks"]
        for arm in scope["arms"]
        for regime in scope["regimes"]
    }
    if {(r["task"], r["arm"], r["regime"]) for r in aliases} != expected or len(
        aliases
    ) != scope["expected_aliases"]:
        raise RuntimeError("Runtime alias coverage differs from registration")
    grouped = {}
    for alias in aliases:
        grouped.setdefault(
            (alias["task"], alias["arm"], alias["checkpoint_sha256"]), []
        ).append(alias)
    data = {
        task: checkpoints.read_arrays(output / row["file"])
        for task, row in registered["data_binding"].items()
    }
    cases, models, tensors = [], {}, {}
    for index, (identity, linked) in enumerate(sorted(grouped.items())):
        alias = min(
            linked, key=lambda row: (row["id"], row["checkpoint"], row["regime"])
        )
        checkpoint = formal / "candidates" / alias["id"] / f"{alias['checkpoint']}.npz"
        if sha(checkpoint) != alias["checkpoint_sha256"]:
            raise RuntimeError("Runtime checkpoint bytes differ from selection")
        model = checkpoints.make_model(alias, core, checkpoint).cpu().eval()
        models[index] = model
        for batch in registered["inputs"]["batch_sizes"]:
            case_id = f"physical_{index:03d}_batch_{batch}"
            inputs = torch.from_numpy(data[alias["task"]]["inputs"][:batch])
            dt = torch.from_numpy(data[alias["task"]]["dt"][:batch])
            tensors[case_id] = inputs, dt
            cases.append(
                {
                    "case_id": case_id,
                    "physical_index": index,
                    "identity": list(identity),
                    "aliases": linked,
                    "batch_size": batch,
                    "sequence_length": inputs.shape[1],
                    "checkpoint_relative_path": str(checkpoint.relative_to(formal)),
                    "checkpoint_sha256": sha(checkpoint),
                    "registered_input_file_sha256": registered["data_binding"][
                        alias["task"]
                    ]["sha256"],
                    "input_tensor_sha256": hashlib.sha256(
                        inputs.numpy().tobytes()
                    ).hexdigest(),
                    "dt_tensor_sha256": hashlib.sha256(
                        dt.numpy().tobytes()
                    ).hexdigest(),
                    "state_payload": state_payload(model, batch),
                }
            )
    execution = output / "execution"
    execution.mkdir(exist_ok=False)
    warmups = registered["execution"]["warmups_per_case"]
    repetitions = registered["execution"]["timed_repetitions_per_case"]
    warm_rng, timed_rng = (
        np.random.default_rng(20261029),
        np.random.default_rng(20261030),
    )
    warm_orders = [warm_rng.permutation(len(cases)).tolist() for _ in range(warmups)]
    timed_orders = [
        timed_rng.permutation(len(cases)).tolist() for _ in range(repetitions)
    ]
    write_json(
        execution / "plan.json",
        {
            "registered_protocol_sha256": sha(output / "protocol.json"),
            "selection_sha256": selection_seal["selection_sha256"],
            "all_training_complete_seal_sha256": sha(
                formal / "all_training_complete_seal.json"
            ),
            "numerical_summary_sha256": sha(numerical_summary_path),
            "numerical_execution_errors_retained": numerical_summary[
                "execution_errors"
            ],
            "idle_cpu_scheduling_asserted": True,
            "test_scores_read_for_timing": False,
            "test_scores_file_existed_at_start": (formal / "results.json").exists(),
            "started_unix": time.time(),
            "environment": environment(),
            "cases": cases,
            "warmup_orders": warm_orders,
            "timed_orders": timed_orders,
        },
    )
    cpu_ns = np.full((len(cases), repetitions), -1, dtype=np.int64)
    wall_ns = np.full_like(cpu_ns, -1)
    output_hashes = {}
    with (
        torch.no_grad(),
        (execution / "raw_events.jsonl").open("x", encoding="utf-8") as events,
    ):
        for order in warm_orders:
            for case_index in order:
                case = cases[case_index]
                inputs, dt = tensors[case["case_id"]]
                logits = models[case["physical_index"]](inputs, dt)
                digest = tensor_digest(logits)
                previous = output_hashes.setdefault(case["case_id"], digest)
                if digest != previous:
                    raise RuntimeError(
                        "Repeated fresh-reset warmup produced a different output"
                    )
        for repetition, order in enumerate(timed_orders):
            for position, case_index in enumerate(order):
                case = cases[case_index]
                inputs, dt = tensors[case["case_id"]]
                model = models[case["physical_index"]]
                wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
                logits = model(inputs, dt)
                cpu_end, wall_end = time.process_time_ns(), time.perf_counter_ns()
                cpu_ns[case_index, repetition] = cpu_end - cpu_start
                wall_ns[case_index, repetition] = wall_end - wall_start
                if tensor_digest(logits) != output_hashes[case["case_id"]]:
                    raise RuntimeError(
                        "Timed forward changed a warmed deterministic output"
                    )
                events.write(
                    json.dumps(
                        {
                            "case_index": case_index,
                            "case_id": case["case_id"],
                            "repetition": repetition,
                            "position": position,
                            "cpu_nanoseconds": int(cpu_ns[case_index, repetition]),
                            "wall_nanoseconds": int(wall_ns[case_index, repetition]),
                        }
                    )
                    + "\n"
                )
                events.flush()
    save_arrays(
        execution / "raw_times.npz",
        {"cpu_nanoseconds": cpu_ns, "wall_nanoseconds": wall_ns},
    )
    summaries = []
    for index, case in enumerate(cases):
        cpu = distribution(cpu_ns[index] * 1e-9)
        wall = distribution(wall_ns[index] * 1e-9)
        summaries.append(
            {
                **case,
                "cpu_seconds": cpu,
                "wall_seconds": wall,
                "sequences_per_second_from_median_wall": case["batch_size"]
                / wall["median"],
                "external_tokens_per_second_from_median_wall": case["batch_size"]
                * case["sequence_length"]
                / wall["median"],
                "amortized_wall_seconds_per_sequence": wall["median"]
                / case["batch_size"],
                "deterministic_output_sha256": output_hashes[case["case_id"]],
            }
        )
    verify(formal, numerical, output)
    if sha(formal / "selection.json") != selection_seal["selection_sha256"]:
        raise RuntimeError("Selection changed during timing")
    summary = {
        "status": "complete",
        "alias_count": len(aliases),
        "physical_checkpoint_count": len(grouped),
        "case_count": len(cases),
        "timed_repetitions_per_case": repetitions,
        "warmups_per_case": warmups,
        "cases": summaries,
        "quality_used_to_select_timing_cases": False,
        "raw_times_sha256": sha(execution / "raw_times.npz"),
        "raw_events_sha256": sha(execution / "raw_events.jsonl"),
        "execution_plan_sha256": sha(execution / "plan.json"),
    }
    write_json(execution / "summary.json", summary)
    return {
        "status": "runtime_complete_all_cases_retained",
        "summary_sha256": sha(execution / "summary.json"),
        "aliases": len(aliases),
        "cases": len(cases),
    }


def empirical_band(left, right, rules):
    gaps = {
        "test_accuracy": abs(left["test"]["accuracy"] - right["test"]["accuracy"]),
        "test_cross_entropy": abs(
            left["test"]["cross_entropy"] - right["test"]["cross_entropy"]
        ),
    }
    checks = {
        "both_validation_floor": min(
            left["validation"]["accuracy"], right["validation"]["accuracy"]
        )
        >= rules["both_validation_accuracy_min"],
        "both_test_floor": min(left["test"]["accuracy"], right["test"]["accuracy"])
        >= rules["both_test_accuracy_min"],
        "test_accuracy_band": gaps["test_accuracy"]
        <= rules["absolute_test_accuracy_gap_max"],
        "test_cross_entropy_band": gaps["test_cross_entropy"]
        <= rules["absolute_test_cross_entropy_gap_max"],
    }
    return {
        "empirical_quality_band_eligible": all(checks.values()),
        "checks": checks,
        "absolute_score_gaps": gaps,
        "not_a_statistical_equivalence_test": True,
    }


def join_quality(formal, numerical, output):
    registered, _ = verify(formal, numerical, output)
    summary = json.loads((output / "execution" / "summary.json").read_text())
    if summary["status"] != "complete":
        raise RuntimeError("Runtime cases must all finish before the quality join")
    primary = json.loads((formal / "results.json").read_text())
    primary_map = {
        (row["task"], row["arm"], row["seed"], row["regime"]): row
        for row in primary["results"]
    }
    timing = {}
    for case in summary["cases"]:
        for alias in case["aliases"]:
            key = (alias["task"], alias["arm"], alias["seed"], alias["regime"])
            scored = primary_map[key]
            if (
                scored["checkpoint_sha256"] != alias["checkpoint_sha256"]
                or scored["id"] != alias["id"]
            ):
                raise RuntimeError(
                    "Primary quality and timed checkpoint identities differ"
                )
            timing[key, case["batch_size"]] = case
    rules, rows = registered["quality_join"], []
    for task in registered["scope"]["tasks"]:
        for regime in registered["scope"]["regimes"]:
            left_key = (task, rules["reference_arm"], rules["timed_seed"], regime)
            for arm in rules["comparators"]:
                right_key = (task, arm, rules["timed_seed"], regime)
                left, right = primary_map[left_key], primary_map[right_key]
                eligibility = empirical_band(left, right, rules)
                ratios = {}
                if eligibility["empirical_quality_band_eligible"]:
                    for batch in registered["inputs"]["batch_sizes"]:
                        a, b = timing[left_key, batch], timing[right_key, batch]
                        ratios[str(batch)] = {
                            "analytic_to_comparator_cpu_median_ratio": a["cpu_seconds"][
                                "median"
                            ]
                            / b["cpu_seconds"]["median"],
                            "analytic_to_comparator_wall_median_ratio": a[
                                "wall_seconds"
                            ]["median"]
                            / b["wall_seconds"]["median"],
                            "analytic_case": a["case_id"],
                            "comparator_case": b["case_id"],
                        }
                rows.append(
                    {
                        "task": task,
                        "regime": regime,
                        "seed": rules["timed_seed"],
                        "comparator": arm,
                        **eligibility,
                        "analytic_scores": {
                            name: left[name] for name in ("validation", "test")
                        },
                        "comparator_scores": {
                            name: right[name] for name in ("validation", "test")
                        },
                        "matched_band_cost_ratios": ratios,
                        "all_individual_timings_remain_in_runtime_summary": True,
                    }
                )
    result = {
        "primary_results_sha256": sha(formal / "results.json"),
        "runtime_summary_sha256": sha(output / "execution" / "summary.json"),
        "registered_protocol_sha256": sha(output / "protocol.json"),
        "not_a_statistical_equivalence_test": True,
        "timed_cases_reselected": False,
        "comparisons": rows,
    }
    write_json(output / "quality_join.json", result)
    return {
        "status": "descriptive_quality_join_complete",
        "comparisons": len(rows),
        "eligible_pairs": sum(row["empirical_quality_band_eligible"] for row in rows),
        "quality_join_sha256": sha(output / "quality_join.json"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("register", "run", "join-quality"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--numerics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--idle-cpu-attested", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    if args.phase == "register":
        result = register(args.study, args.numerics, args.output)
    elif args.phase == "run":
        result = run(args.study, args.numerics, args.output, args.idle_cpu_attested)
    else:
        result = join_quality(args.study, args.numerics, args.output)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
