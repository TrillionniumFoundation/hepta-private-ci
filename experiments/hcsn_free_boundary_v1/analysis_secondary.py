"""Predeclared, separate evaluation of exactly-128-update snapshots.

No new training is performed. Both prespecified LR snapshots must exist for a
run to be eligible; a missing snapshot is reported, never extrapolated. This
module does not overwrite primary selections, predictions, or analysis.
"""

import math
from pathlib import Path
import time

from .analysis import (PACKAGE, REPOSITORY, _write_json, digest, expected_jobs,
                       inspect_dataset, read_json, require_complete)


def choose_128_candidate(candidates, required_learning_rates):
    by_lr = {c["learning_rate"]: c for c in candidates}
    if len(by_lr) != len(candidates):
        raise ValueError("Duplicated LR candidate.")
    available, missing = [], []
    for learning_rate in required_learning_rates:
        candidate = by_lr.get(learning_rate)
        snapshots = [] if candidate is None else [c for c in candidate["checkpoints"] if c["step"] == 128 and c["fixed_step_128"]]
        if len(snapshots) != 1:
            missing.append(dict(learning_rate=learning_rate, reason="exactly one 128-update snapshot required"))
            continue
        snapshot = snapshots[0]
        if not math.isfinite(snapshot["validation"]["cross_entropy"]):
            raise ValueError("Nonfinite 128-update validation criterion.")
        available.append(dict(learning_rate=learning_rate, directory=candidate["directory"], checkpoint=snapshot))
    if missing:
        return dict(status="incomplete", missing=missing, available=available, selected=None)
    selected = min(available, key=lambda c: (c["checkpoint"]["validation"]["cross_entropy"], c["learning_rate"]))
    return dict(status="eligible", missing=[], available=available, selected=selected,
                rule="minimum validation CE at exactly128 across all predeclared LRs; tie smaller LR")


def evaluate_secondary128(study, data_directory, protocol_path, output=None, partial=False):
    require_complete(study, partial)
    import torch
    from .benchmark_models import build_model
    from .training import evaluate, load_split, load_weights

    torch.set_num_threads(1)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    study, data_directory = Path(study), Path(data_directory)
    protocol = read_json(protocol_path)
    output = Path(output) if output is not None else study / "secondary128"
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Secondary evidence exists; use a fresh output directory.")
    identity = read_json(study / "IDENTITY.json")
    if identity["files"].get(identity.get("protocol_path")) != digest(protocol_path):
        raise ValueError("Secondary protocol is not bound to the frozen protocol bytes.")
    if {(r["task"], r["model"], r["seed"]) for r in identity["jobs"]} != set(expected_jobs(protocol)):
        raise ValueError("Secondary job declaration differs from the frozen matrix.")
    for path, expected in identity["files"].items():
        if not (REPOSITORY / path).is_file() or digest(REPOSITORY / path) != expected:
            raise ValueError(f"Frozen source/data changed before secondary evaluation: {path}")
    datasets = {task: inspect_dataset(data_directory, task) for task in protocol["core"]["tasks"]}
    for task, dataset in datasets.items():
        prefix = identity["data_directory"] + "/" + task
        if (identity["files"].get(prefix + ".npz") != dataset["sha256"]
                or identity["files"].get(prefix + ".json") != dataset["audit"]["manifest_sha256"]):
            raise ValueError("Secondary data/metadata is not bound to frozen bytes.")
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for task, name, seed in expected_jobs(protocol):
        source = study / "runs" / task / name / str(seed)
        destination = output / "runs" / task / name / str(seed)
        destination.mkdir(parents=True, exist_ok=True)
        row = dict(task=task, model=name, seed=seed, status="incomplete")
        try:
            if not (source / "summary.json").exists() or not (source / "EXECUTION.json").exists():
                row["reason"] = "primary search/complete execution receipt unavailable"
                _write_json(destination / "summary.json", row)
                records.append(row)
                continue
            primary = read_json(source / "summary.json")
            execution = read_json(source / "EXECUTION.json")
            if primary["status"] != "completed" or execution["returncode"] != 0:
                raise ValueError("Primary search failed; no secondary rescue selection.")
            eligibility = choose_128_candidate(primary["candidates"], protocol["optimization"]["learning_rates"])
            row["eligibility"] = eligibility
            if eligibility["status"] != "eligible":
                _write_json(destination / "summary.json", row)
                records.append(row)
                continue
            if primary["selection"]["dataset_sha256"] != datasets[task]["sha256"]:
                raise ValueError("Secondary dataset differs from the primary frozen data.")
            for available in eligibility["available"]:
                checkpoint = source / available["directory"] / available["checkpoint"]["weights"]
                if digest(checkpoint) != available["checkpoint"]["sha256"]:
                    raise ValueError("A 128-update candidate checkpoint hash changed.")
            selected = eligibility["selected"]
            selection = dict(step=128, selected_learning_rate=selected["learning_rate"],
                              selected_validation=selected["checkpoint"]["validation"],
                              selected_sha256=selected["checkpoint"]["sha256"],
                              dataset_sha256=datasets[task]["sha256"], rule=eligibility["rule"],
                              original_primary_sha256=primary["selection"]["selected_checkpoint_sha256"],
                              primary_selection_changed=False)
            # Durable selection is written before any heldout inference.
            _write_json(destination / "SELECTION.json", selection)
            row_start = time.process_time()
            config = protocol["optimization"]
            manifest = datasets[task]["manifest"]
            model = build_model(name, manifest["input_dim"], manifest["output_dim"],
                                width=config["width"], depth=config["depth"], seed=seed)
            load_weights(source / selected["directory"] / selected["checkpoint"]["weights"], model)
            metrics = {}
            for split in ("test", "ood"):
                data = load_split(data_directory / f"{task}.npz", split)
                metrics[split] = None if data is None else evaluate(model, data, config["evaluation_batch_size"],
                                                                  destination / f"{split}_predictions.npz")
            if digest(source / "selected.npz") != primary["selection"]["selected_checkpoint_sha256"]:
                raise ValueError("Primary selection unexpectedly changed during secondary evaluation.")
            row.update(status="evaluated", selection=selection, metrics=metrics,
                       additional_secondary_cpu_seconds=time.process_time() - row_start,
                       measured_training_cpu_to_128_all_lrs=sum(c["checkpoint"]["training_cpu_seconds"] for c in eligibility["available"]),
                       original_complete_search_child_cpu_seconds=execution.get("child_cpu_seconds"),
                       cost_interpretation="existing full searches remain charged; prefix CPU describes this snapshot, not a new cheaper completed search")
        except Exception as error:
            row.update(status="invalid", error=dict(type=type(error).__name__, message=str(error)))
        _write_json(destination / "summary.json", row)
        records.append(row)
    expected = len(expected_jobs(protocol))
    available = sum(row["status"] == "evaluated" for row in records)
    coverage = []
    for task in protocol["core"]["tasks"]:
        for seed in protocol["core"]["seeds"]:
            subset = [r for r in records if r["task"] == task and r["seed"] == seed and r["model"] in protocol["core"]["models"]]
            coverage.append(dict(task=task, seed=seed, all_core_arms_available=all(r["status"] == "evaluated" for r in subset)
                                  and len(subset) == len(protocol["core"]["models"]),
                                 missing_or_invalid_models=[r["model"] for r in subset if r["status"] != "evaluated"]))
    report = dict(schema="hcsn.exactly128-secondary.v1", status="complete" if available == expected else "incomplete",
                  expected_runs=expected, available_runs=available, records=records, core_paired_coverage=coverage,
                  primary_results_changed=False, extrapolation_performed=False, additional_training_performed=False,
                  no_new_significance_claim=True, partial=bool(partial),
                  additional_analysis_cpu_seconds=time.process_time() - start_cpu,
                  additional_analysis_wall_seconds=time.perf_counter() - start_wall,
                  source_sha256={"analysis_secondary.py": digest(__file__), "protocol": digest(protocol_path)})
    _write_json(output / "SECONDARY128.json", report)
    return report
