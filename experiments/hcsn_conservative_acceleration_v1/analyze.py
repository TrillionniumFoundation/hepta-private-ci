"""Independent saved-prediction, pairing, cost and selection audits.

The numerical-fidelity result and the equal-CPU quality result are separate.
Failure, missing jobs and low quality never become an architecture win.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

import numpy as np

from .study import PACKAGE, ROOT, digest, new_output, read, verify, write


def independent_metrics(logits, labels):
    values, target = np.asarray(logits, dtype=np.float64), np.asarray(labels, dtype=np.int64)
    if values.ndim != 2 or len(values) != len(target) or not np.isfinite(values).all():
        raise AssertionError("Invalid saved prediction arrays")
    losses = np.logaddexp.reduce(values, axis=1)-values[np.arange(len(target)), target]
    correct = int(np.count_nonzero(np.argmax(values, axis=1) == target))
    return dict(cross_entropy=float(losses.mean()), accuracy=correct/len(target),
                correct=correct, supervised_positions=len(target))


def verify_metrics(actual, expected):
    for key in ("cross_entropy", "accuracy"):
        if abs(actual[key]-expected[key]) > 1e-10:
            raise AssertionError("Saved-logit metric mismatch: " + key)
    for key in ("correct", "supervised_positions"):
        if actual[key] != expected[key]:
            raise AssertionError("Prediction count mismatch: " + key)


def array_state_digest(path, common_only=False):
    h = hashlib.sha256()
    with np.load(path, allow_pickle=False) as z:
        for name in sorted(z.files):
            if common_only and not any(part in name.split(".") for part in ("frontend", "readout", "head")):
                continue
            value = z[name]
            h.update(json.dumps([name, str(value.dtype), list(value.shape)]).encode())
            h.update(value.tobytes())
    return h.hexdigest()


def prediction_audit(path, source, task, expected):
    with np.load(path, allow_pickle=False) as z, np.load(source, allow_pickle=False) as data:
        labels, logits = z["labels"], z["logits"]
        if task == "cremad":
            if not np.array_equal(labels, data["y"]) or not np.array_equal(z["actors"], data["actor"]):
                raise AssertionError("Audiovisual target/source mismatch")
            if not np.array_equal(z["clips"], data["clip"]):
                raise AssertionError("Audiovisual recording identity mismatch")
            for modality in ("audio", "video"):
                verify_metrics(independent_metrics(z[modality+"_logits"], labels), expected["modalities"][modality])
            if not np.allclose(logits, (z["audio_logits"]+z["video_logits"])/2, atol=2e-6, rtol=2e-6):
                raise AssertionError("Registered late-fusion architecture changed")
        else:
            samples, steps = np.nonzero(data["y"] != -100)
            if (not np.array_equal(samples, z["sample_indices"])
                    or not np.array_equal(steps, z["step_indices"])
                    or not np.array_equal(labels, data["y"][samples, steps])):
                raise AssertionError("Supervised-token mask/label identity mismatch")
        if not np.array_equal(z["predictions"], logits.argmax(-1)):
            raise AssertionError("Saved argmax mismatch")
        verify_metrics(independent_metrics(logits, labels), expected)


def audit_job(protocol, output, execution):
    import torch
    folder = output / execution["directory"]
    summary = read(folder / "summary.json")
    p, job, opt = protocol, execution["job"], protocol["optimization"]
    index = execution["index"]
    if not isinstance(index, int) or not 0 <= index < len(p["jobs"]) or job != p["jobs"][index]:
        raise AssertionError("Execution does not match its registered job index")
    if summary["job"] != job or summary["status"] != "completed":
        raise AssertionError("Worker job mismatch")
    if job["model"].startswith("hcsn_"):
        configurations = ([summary["config"][name] for name in ("audio", "video")]
                          if job["task"] == "cremad" else [summary["config"]])
        for config in configurations:
            if (config["operator_backend"] != job["model"].removeprefix("hcsn_")
                    or config["probability_profile"] != "stable"):
                raise AssertionError("Registered backend/profile mismatch")
    request = read(folder / "request.json")
    if request["job"] != job or request["protocol_sha256"] != summary["protocol_sha256"]:
        raise AssertionError("Request identity mismatch")
    selection = read(folder / "selection.json")
    if selection != summary["selection"]:
        raise AssertionError("Selection receipt changed")
    checkpoints = read(folder / "checkpoints.json")
    for checkpoint in checkpoints:
        if digest(folder / checkpoint["weights"]) != checkpoint["sha256"]:
            raise AssertionError("Checkpoint checksum mismatch")
        if digest(folder / checkpoint["predictions"]) != checkpoint["predictions_sha256"]:
            raise AssertionError("Validation prediction checksum mismatch")
        prediction_audit(folder / checkpoint["predictions"],
            ROOT / p["data"][job["task"]]["splits"]["val"]["path"], job["task"], checkpoint["validation"])
    expected_selection = min(checkpoints, key=lambda row: (row["validation"]["cross_entropy"], row["step"]))
    if selection["checkpoint"] != expected_selection or selection["completed_candidates"] != 1:
        raise AssertionError("Validation-only selection rule mismatch")
    if digest(folder / "selected.npz") != expected_selection["sha256"]:
        raise AssertionError("Selected checkpoint mismatch")
    if digest(folder / "final.npz") != selection["final_checkpoint_sha256"]:
        raise AssertionError("Final checkpoint mismatch")
    if (array_state_digest(folder / "initial.npz") != summary["initial_state_sha256"]
            or array_state_digest(folder / "initial.npz", True) != summary["common_initial_state_sha256"]):
        raise AssertionError("Initial state receipt mismatch")
    accesses = read(folder / "access_log.json")
    if accesses != summary["access_log"]:
        raise AssertionError("Access log mismatch")
    signatures = [(row["event"], row.get("split")) for row in accesses]
    if signatures != [("load_split", "train"), ("load_split", "val"),
                      ("validation_selection_locked", None), ("load_split", "test")]:
        raise AssertionError("Heldout access order changed")
    if accesses[2]["sha256"] != digest(folder / "selection.json"):
        raise AssertionError("Selection lock identity mismatch")
    if digest(folder / "test_predictions.npz") != summary["predictions_sha256"]:
        raise AssertionError("Heldout prediction checksum mismatch")
    prediction_audit(folder / "test_predictions.npz",
        ROOT / p["data"][job["task"]]["splits"]["test"]["path"], job["task"], summary["test"])
    updates = [json.loads(row) for row in (folder / "updates.jsonl").read_text().splitlines()]
    if len(updates) != summary["updates"] or [r["step"] for r in updates] != list(range(1, len(updates)+1)):
        raise AssertionError("Training update log incomplete")
    generator = torch.Generator().manual_seed(job["seed"]+200003)
    prefix = hashlib.sha256()
    batch = opt["av_batch_size"] if job["task"] == "cremad" else opt["batch_size"]
    train_size = p["data"][job["task"]]["splits"]["train"]["examples"]
    permutation = torch.randperm(train_size, generator=generator) if job["task"] == "cremad" else None
    position = 0
    for row in updates:
        if job["task"] == "cremad":
            if position+batch > train_size:
                permutation, position = torch.randperm(train_size, generator=generator), 0
            indices = permutation[position:position+batch]
            position += batch
        else:
            indices = torch.randint(train_size, (batch,), generator=generator)
        raw = indices.numpy().tobytes()
        prefix.update(raw)
        if row["batch_sha256"] != hashlib.sha256(raw).hexdigest() or row["prefix_sha256"] != prefix.hexdigest():
            raise AssertionError("Minibatch stream does not replay")
        if not math.isfinite(row["loss"]) or any(not g["finite"] or g["missing_elements"] for g in row["gradients"].values()):
            raise AssertionError("Training gradient/loss audit failed")
        if row["probability"]["minimum"] < 0 or row["probability"]["max_mass_error"] > 1e-4:
            raise AssertionError("Logged probability audit failed")
    if prefix.hexdigest() != summary["minibatch_prefix_sha256"]:
        raise AssertionError("Final minibatch prefix mismatch")
    if updates[-1]["training_cpu_seconds"] != summary["training_cpu_seconds"]:
        raise AssertionError("Training CPU receipt mismatch")
    if job["family"] == "fixed":
        expected_updates = opt["supplementary_updates"] if job["supplementary"] else opt["fixed_updates"]
        milestones = opt["supplementary_validation_updates"] if job["supplementary"] else opt["fixed_validation_updates"]
        if len(updates) != expected_updates or [r["step"] for r in checkpoints] != milestones:
            raise AssertionError("Fixed update/selection opportunity mismatch")
    else:
        if ([target for row in checkpoints for target in row["crossed_cpu_targets"]] != opt["cpu_validation_seconds"]
                or summary["training_cpu_seconds"] < opt["cpu_seconds"]
                or (len(updates) > 1 and updates[-2]["training_cpu_seconds"] >= opt["cpu_seconds"])):
            raise AssertionError("CPU stopping or selection opportunity mismatch")
    if execution["whole_worker_cpu_seconds"] < summary["training_cpu_seconds"]:
        raise AssertionError("Whole-worker CPU cannot be below its training CPU")
    return dict(summary=summary, updates=updates, execution=execution, directory=folder)


def descriptive(values):
    values = list(values)
    n = len(values)
    result = dict(n=n, values=values, mean=statistics.mean(values) if n else None,
                  sample_sd=statistics.stdev(values) if n > 1 else None)
    if n in (2, 3):
        critical = {2: 12.706204736432095, 3: 4.302652729911275}[n]
        radius = critical * result["sample_sd"] / math.sqrt(n)
        result["descriptive_t95_interval"] = [result["mean"]-radius, result["mean"]+radius]
    else:
        result["descriptive_t95_interval"] = None
    return result


def final_parameter_comparison(left, right, tolerance):
    errors, passed = {}, True
    with np.load(left, allow_pickle=False) as first, np.load(right, allow_pickle=False) as second:
        if set(first.files) != set(second.files):
            raise AssertionError("Paired state_dict keys differ")
        for key in first.files:
            a, b = first[key], second[key]
            errors[key] = float(np.max(np.abs(a-b)))
            passed &= bool(np.allclose(a, b, atol=tolerance["trajectory_parameter_atol"],
                                       rtol=tolerance["trajectory_parameter_rtol"]))
    return dict(passed=bool(passed), maximum_absolute_error=max(errors.values()), tensors=errors)


def analyze(protocol, output, destination, allow_partial=False):
    process_start, wall_start = time.process_time(), time.perf_counter()
    p, output = verify(protocol), Path(output)
    if str(output.resolve().relative_to(ROOT)) != p["output"]:
        raise AssertionError("Analysis directory does not match registered output")
    if read(output / "REGISTRATION.json")["protocol_sha256"] != digest(protocol):
        raise AssertionError("Cohort registration checksum mismatch")
    terminal = output / "COMPLETE.json"
    if not terminal.exists():
        terminal = output / "ABORTED.json"
    if not terminal.exists():
        if not allow_partial:
            raise RuntimeError("Wait for a terminal study receipt before final analysis")
        terminal = output / "PROGRESS.json"
    receipt = read(terminal)
    if terminal.name != "PROGRESS.json" and receipt["protocol_sha256"] != digest(protocol):
        raise AssertionError("Terminal receipt protocol checksum mismatch")
    rows, errors, audit_records = {}, [], []
    indices = set()
    for execution in receipt["records"]:
        job = execution["job"]
        index = execution["index"]
        if (not isinstance(index, int) or not 0 <= index < len(p["jobs"])
                or index in indices or job != p["jobs"][index]):
            raise AssertionError("Duplicate, foreign or misindexed execution receipt")
        indices.add(index)
        key = (job["family"], job["task"], job["model"], job["seed"])
        if key in rows:
            raise AssertionError("Duplicate completed job")
        if execution["returncode"]:
            errors.append(dict(job=job, error="worker failed", execution=execution))
            continue
        try:
            row = audit_job(p, output, execution)
            if row["summary"]["protocol_sha256"] != digest(protocol):
                raise AssertionError("Wrong protocol hash")
            rows[key] = row
            audit_records.append(dict(job=job, passed=True))
        except Exception as error:
            errors.append(dict(job=job, error=str(error)))
    pairing, fixed_pairs = [], []
    for family in ("fixed", "cpu"):
        tasks = p["primary_tasks"] + (p["supplementary_tasks"] if family == "fixed" else [])
        for task in tasks:
            seeds = p["primary_seeds"] if task in p["primary_tasks"] else [p["supplementary_seed"]]
            for seed in seeds:
                group = {model: rows.get((family, task, model, seed)) for model in p["models"]}
                if any(value is None for value in group.values()):
                    continue
                common = {value["summary"]["common_initial_state_sha256"] for value in group.values()}
                left, right = group["hcsn_reference"], group["hcsn_accelerated"]
                paired_initial = left["summary"]["initial_state_sha256"] == right["summary"]["initial_state_sha256"]
                common_updates = min(row["summary"]["updates"] for row in group.values())
                prefixes = {value["updates"][common_updates-1]["prefix_sha256"] for value in group.values()}
                target = left["summary"]["counts"]["backbone"]
                gaps = {model: abs(value["summary"]["counts"]["backbone"]-target)/target for model, value in group.items()}
                valid = len(common) == 1 and paired_initial and len(prefixes) == 1 and max(gaps.values()) <= p["optimization"]["backbone_relative_parameter_tolerance"]
                item = dict(family=family, task=task, seed=seed, common_initialization=len(common)==1,
                    hcsn_initialization=paired_initial, minibatch_prefix_equal=len(prefixes)==1,
                    parameter_relative_gaps=gaps, passed=valid)
                pairing.append(item)
                if family == "fixed":
                    first, second = [u["loss"] for u in left["updates"]], [u["loss"] for u in right["updates"]]
                    loss_pass = len(first) == len(second) and np.allclose(first, second,
                        atol=p["fidelity"]["trajectory_loss_atol"], rtol=p["fidelity"]["trajectory_loss_rtol"])
                    parameters = final_parameter_comparison(left["directory"] / "final.npz",
                                                            right["directory"] / "final.npz", p["fidelity"])
                    fixed_pairs.append(dict(task=task, seed=seed,
                        passed=bool(valid and loss_pass and parameters["passed"]),
                        loss_trajectory_passed=bool(loss_pass),
                        maximum_loss_error=float(np.max(np.abs(np.asarray(first)-np.asarray(second)))),
                        final_parameters=parameters,
                        selected_updates_equal=left["summary"]["selection"]["checkpoint"]["step"] == right["summary"]["selection"]["checkpoint"]["step"],
                        training_cpu_speedup=left["summary"]["training_cpu_seconds"]/right["summary"]["training_cpu_seconds"],
                        whole_worker_cpu_speedup=left["execution"]["whole_worker_cpu_seconds"]/right["execution"]["whole_worker_cpu_seconds"],
                        inference_cpu_speedup=left["summary"]["inference"]["median_cpu_seconds"]/right["summary"]["inference"]["median_cpu_seconds"]))
    aggregation = []
    for family in ("fixed", "cpu"):
        for task in p["primary_tasks"] + p["supplementary_tasks"]:
            for model in p["models"]:
                selected = [value for (f, t, m, _), value in rows.items() if (f, t, m) == (family, task, model)]
                if not selected:
                    continue
                aggregation.append(dict(family=family, task=task, model=model,
                    accuracy=descriptive(row["summary"]["test"]["accuracy"] for row in selected),
                    cross_entropy=descriptive(row["summary"]["test"]["cross_entropy"] for row in selected),
                    updates=descriptive(row["summary"]["updates"] for row in selected),
                    training_cpu_seconds=descriptive(row["summary"]["training_cpu_seconds"] for row in selected),
                    whole_worker_cpu_seconds=descriptive(row["execution"]["whole_worker_cpu_seconds"] for row in selected),
                    peak_rss_bytes=descriptive(row["execution"]["peak_rss_bytes"] for row in selected),
                    inference_cpu_seconds=descriptive(row["summary"]["inference"]["median_cpu_seconds"] for row in selected)))
    cpu_pairs, quality = [], []
    for task in p["primary_tasks"]:
        pairs = [(rows.get(("cpu", task, "hcsn_reference", seed)), rows.get(("cpu", task, "hcsn_accelerated", seed))) for seed in p["primary_seeds"]]
        if all(left is not None and right is not None for left, right in pairs):
            cpu_pairs.append(dict(task=task,
                accuracy_difference_accelerated_minus_reference=descriptive(r["summary"]["test"]["accuracy"]-l["summary"]["test"]["accuracy"] for l, r in pairs),
                ce_difference_accelerated_minus_reference=descriptive(r["summary"]["test"]["cross_entropy"]-l["summary"]["test"]["cross_entropy"] for l, r in pairs),
                update_ratios=descriptive(r["summary"]["updates"]/l["summary"]["updates"] for l, r in pairs)))
        for control in ("two_gates", "transformer", "lif_snn"):
            for target in p["analysis"]["quality_targets"]:
                matching = [(rows.get(("cpu", task, "hcsn_accelerated", seed)), rows.get(("cpu", task, control, seed))) for seed in p["primary_seeds"]]
                valid = all(a is not None and b is not None
                    and min(a["summary"]["test"]["accuracy"], b["summary"]["test"]["accuracy"]) >= target
                    and abs(a["summary"]["test"]["accuracy"]-b["summary"]["test"]["accuracy"]) <= p["analysis"]["quality_pair_tolerance"] for a, b in matching)
                quality.append(dict(task=task, control=control, target=target, qualified=valid,
                    inference_speedup_control_over_accelerated=descriptive(b["summary"]["inference"]["median_cpu_seconds"]/a["summary"]["inference"]["median_cpu_seconds"] for a, b in matching) if valid else None,
                    reason="all three paired selected test qualities qualify" if valid else "missing pair or registered target/tolerance not reached"))
    primary_fixed = [row for row in fixed_pairs if row["task"] in p["primary_tasks"]]
    expected_pairs = len(p["primary_tasks"])*len(p["primary_seeds"])
    expected_keys = {(j["family"], j["task"], j["model"], j["seed"]) for j in p["jobs"]}
    if len(expected_keys) != len(p["jobs"]):
        raise AssertionError("Duplicate registered job")
    complete = bool(receipt.get("completed") is True and set(rows) == expected_keys
                    and indices == set(range(len(p["jobs"]))) and not errors
                    and all(row["passed"] for row in pairing))
    fidelity_pass = len(primary_fixed) == expected_pairs and all(row["passed"] for row in primary_fixed)
    geometric_speedup = math.exp(statistics.mean(math.log(row["training_cpu_speedup"]) for row in primary_fixed)) if primary_fixed else None
    speed_gate = bool(complete and fidelity_pass and geometric_speedup >= 1.10
                      and all(row["training_cpu_speedup"] > 1 for row in primary_fixed))
    result = dict(schema="hcsn-conservative-acceleration-analysis.v1", protocol_sha256=digest(protocol),
        complete=complete, valid_jobs=len(rows), expected_jobs=len(p["jobs"]), errors=errors,
        audits=audit_records, pairing=pairing, fixed_update_pairs=fixed_pairs,
        primary_fidelity_passed=fidelity_pass, primary_geometric_training_cpu_speedup=geometric_speedup,
        engineering_speed_gate_passed=speed_gate, aggregation=aggregation, equal_cpu_pairs=cpu_pairs,
        quality_conditioned_external_comparisons=quality,
        whole_child_cpu_seconds=sum(row["whole_worker_cpu_seconds"] for row in receipt["records"]),
        cost_scope="Cohort worker CPU only; preflight, kernel proof, data registration, coordinator and this analysis are separately reported and must not be added twice.",
        separate_costs=dict(registration=read(output / "REGISTRATION.json").get("cpu_seconds"),
            preflight=read(ROOT / p["preflight"]["path"]).get("cpu_seconds"),
            kernel_validation=read(ROOT / p["kernel_proof"]["path"]).get("cpu_seconds"),
            coordinator=receipt.get("coordinator_cpu_seconds"),
            unmeasured_development_cpu_seconds=None, separate_runtime_audit_cpu_seconds=None,
            analysis_cpu_seconds=time.process_time()-process_start,
            analysis_wall_seconds=time.perf_counter()-wall_start),
        scope=p["interpretation"], caveats=[
            "Shared-host CPU observations; wall time contention is uncontrolled.",
            "One common learning rate and short training do not establish each architecture's optimum.",
            "Classification gradients adapt physical parameters; the affine stopping reward remains a local surrogate.",
            "CREMA-D uses an observed actor split, offline fixed features and shared-head arithmetic late fusion.",
            "No measured energy, GPU cost, long-context content quality or foundation-model scaling evidence."])
    destination = new_output(destination)
    write(destination / "ANALYSIS.json", result)
    lines = ["# Conservative HCSN acceleration comparison", "", p["interpretation"], "",
        f"Audited jobs: {len(rows)}/{len(p['jobs'])}. Complete: {complete}. Primary fixed-update fidelity: {fidelity_pass}. Engineering speed gate: {speed_gate}.", "",
        "| Family | Task | Model | n | Test accuracy | CE | Updates | Training CPU s | Whole-worker CPU s |", "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in aggregation:
        lines.append(f"| {row['family']} | {row['task']} | {row['model']} | {row['accuracy']['n']} | {100*row['accuracy']['mean']:.2f}% | {row['cross_entropy']['mean']:.6f} | {row['updates']['mean']:.1f} | {row['training_cpu_seconds']['mean']:.2f} | {row['whole_worker_cpu_seconds']['mean']:.2f} |")
    lines += ["", "## Scope", ""] + ["- " + value for value in result["caveats"]]
    (destination / "REPORT.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(complete=complete, valid_jobs=len(rows), fidelity=fidelity_pass,
                          engineering_speed_gate=speed_gate, errors=errors)), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    analyze(args.protocol, args.study, args.output, args.allow_partial)


if __name__ == "__main__":
    main()
