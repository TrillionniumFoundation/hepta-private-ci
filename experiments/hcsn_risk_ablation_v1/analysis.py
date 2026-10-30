"""Independent complete-matrix audit and predeclared paired risk contrasts."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t
import torch

from experiments.hcsn_free_boundary_v1 import training
from experiments.hcsn_distributional_v2.content_analysis import (
    arrays, audit_predictions, common_hash, exact_sign_flip, holm, read_json)
from .model import build_model
from .study import ROOT, PACKAGE, verify


def analyze(protocol_path, study, output):
    study, output = Path(study), Path(output)
    if output.exists():
        raise FileExistsError("Use a new analysis directory")
    torch.set_num_threads(1)
    protocol = verify(protocol_path)
    digest = training._sha256(protocol_path)
    complete = read_json(study / "COMPLETE.json")
    assert complete["status"] == "completed" and complete["failures"] == 0
    assert complete["protocol_sha256"] == digest
    key = lambda row: (row["task"], row["model"], row["seed"])
    ledger = {key(row["job"]): row for row in complete["records"]}
    assert len(ledger) == len(complete["records"]) == len(protocol["jobs"])
    assert set(ledger) == {key(job) for job in protocol["jobs"]}
    data = {task: arrays(ROOT / record["path"]) for task, record in protocol["data"].items()}
    results, shared, total_training = [], {}, 0.0
    for job in protocol["jobs"]:
        identifier = "__".join(map(str, key(job)))
        folder = study / "runs" / identifier
        execution = read_json(folder / "EXECUTION.json")
        assert execution == ledger[key(job)] and execution["returncode"] == 0
        assert execution["stdout_sha256"] == training._sha256(study / "process_logs" / (identifier + ".log"))
        identity, summary = (read_json(folder / name) for name in ("IDENTITY.json", "summary.json"))
        assert identity["protocol_sha256"] == digest and identity["job"] == job
        assert identity["source_files_sha256"] == protocol["source_files_sha256"]
        assert identity["dataset_sha256"] == protocol["data"][job["task"]]["sha256"]
        assert summary["status"] == "completed" and len(summary["candidates"]) == 1
        candidate = summary["candidates"][0]
        assert candidate["learning_rate"] == protocol["optimization"]["learning_rates"][0]
        assert candidate["stopping_reason"] == "cpu_budget" and candidate["training_cpu_seconds"] >= 20
        total_training += candidate["training_cpu_seconds"]
        assert execution["child_total_cpu_seconds"] >= candidate["training_cpu_seconds"]
        dataset = data[job["task"]]
        model = build_model(job["model"], dataset["train_x"].shape[-1], int(dataset["train_y"].max())+1,
                            width=32, depth=1, seed=job["seed"])
        assert model.config == summary["selected_model_config"] and model.counts() == summary["counts"]
        directory = folder / candidate["directory"]
        assert read_json(directory / "candidate.json") == {k: v for k, v in candidate.items() if k != "directory"}
        initial = arrays(directory / "initial.npz")
        expected = {name: value.detach().numpy() for name, value in model.state_dict().items()}
        assert set(initial) == set(expected) and all(np.array_equal(initial[name], expected[name]) for name in initial)
        assert training._sha256(directory / "initial.npz") == candidate["initial_sha256"]
        common = common_hash(initial)
        pair = (job["task"], job["seed"])
        assert shared.setdefault(pair, common) == common
        updates = [json.loads(line) for line in (directory / "updates.jsonl").read_text().splitlines()]
        assert len(updates) == candidate["updates"]
        generator, prefix = torch.Generator().manual_seed(job["seed"]+200003), hashlib.sha256()
        for index, row in enumerate(updates, 1):
            indices = torch.randint(len(dataset["train_x"]), (32,), generator=generator).numpy().tobytes()
            prefix.update(indices)
            assert row["step"] == index and row["batch_sha256"] == hashlib.sha256(indices).hexdigest()
            assert row["prefix_sha256"] == prefix.hexdigest()
            assert all(g["finite"] and g["missing_elements"] == 0 for g in row["gradients"].values())
        assert prefix.hexdigest() == candidate["batch_prefix_sha256"]
        checkpoints = read_json(directory / "checkpoints.json")
        assert checkpoints == candidate["checkpoints"]
        assert [gate for row in checkpoints for gate in row["crossed_cpu_targets"]] == [5., 10., 20.]
        assert {p.name for p in directory.glob("*.npz")} == {"initial.npz"} | {row["weights"] for row in checkpoints}
        for row in checkpoints:
            assert training._sha256(directory / row["weights"]) == row["sha256"]
            if not row["crossed_cpu_targets"]:
                assert row["fixed_step_128"] and not row["primary_eligible"]
        best = min((row for row in checkpoints if row["primary_eligible"]), key=lambda row:
                   (row["validation"]["cross_entropy"], row["training_cpu_seconds"], row["step"]))
        assert candidate["best"] == best
        selection = read_json(folder / "selection.json")
        assert selection == summary["selection"] and selection["completed_lr_candidates"] == 1
        assert selection["selected_checkpoint_sha256"] == best["sha256"] == training._sha256(folder / "selected.npz")
        access = summary["access_log"]
        locks = [i for i, row in enumerate(access) if row["event"] == "selection_locked"]
        assert len(locks) == 1 and access[locks[0]]["completed_lr_candidates"] == 1
        assert all(i > locks[0] for i, row in enumerate(access) if row.get("split") in ("test", "ood"))
        selected = arrays(folder / "selected.npz")
        physical_changes = {name: float(np.max(np.abs(value-initial[name]))) for name, value in selected.items()
            if any(part in name for part in ("mu_bias", "raw_sigma", "raw_rho", "raw_K", "raw_reset", "raw_refractory", "raw_boundary"))}
        assert all(value > 0 for value in physical_changes.values())
        holdout = {}
        for split in ("test", "ood"):
            if split + "_y" not in dataset:
                assert summary["holdout"][split] is None
                continue
            checked = audit_predictions(folder / (split + "_predictions.npz"), dataset[split + "_y"], summary["holdout"][split])
            checked.pop("archive")
            holdout[split] = checked
        training.load_weights(folder / "selected.npz", model)
        model.eval()
        with torch.no_grad():
            replay = model(torch.from_numpy(dataset["test_x"][:4]).float(),
                torch.from_numpy(dataset["test_dt"][:4]).float(), return_sequence=True, return_aux=False).numpy()
        predictions = arrays(folder / "test_predictions.npz")
        keep = predictions["sample_indices"] < 4
        error = float(np.max(np.abs(replay[predictions["sample_indices"][keep], predictions["step_indices"][keep]]-predictions["logits"][keep])))
        assert error <= 5e-5
        results.append(dict(**job, holdout=holdout, physical_tensor_changes=physical_changes,
            replay_max_abs_error=error, updates=candidate["updates"], selected_step=best["step"],
            training_cpu_seconds=candidate["training_cpu_seconds"], worker_cpu_seconds=execution["child_total_cpu_seconds"]))
    lookup = {key(row): row for row in results}
    contrasts = []
    primary_count = len(protocol["mechanism"]["contrasts"])
    all_contrasts = protocol["mechanism"]["contrasts"] + protocol["mechanism"]["secondary_contrasts"]
    for index, contrast in enumerate(all_contrasts):
        treatment, control = contrast["treatment"], contrast["control"]
        differences = [float(np.mean([lookup[(task,treatment,seed)]["holdout"]["test"]["accuracy"] -
            lookup[(task,control,seed)]["holdout"]["test"]["accuracy"] for task in protocol["data"]]))
            for seed in protocol["seeds"]]
        mean = float(np.mean(differences))
        half = float(student_t.ppf(.975, len(differences)-1)*np.std(differences, ddof=1)/np.sqrt(len(differences)))
        contrasts.append(dict(**contrast, family="primary" if index < primary_count else "descriptive_secondary",
            differences=differences, mean_accuracy_gain=mean,
            nominal_t95=[mean-half, mean+half], exact_sign_flip_p=exact_sign_flip(differences)))
    primary = contrasts[:primary_count]
    for row, adjusted in zip(primary, holm([row["exact_sign_flip_p"] for row in primary]), strict=True):
        row["holm_p"] = adjusted
        row["gate_passed"] = row["mean_accuracy_gain"] >= .01 and adjusted <= .05 and row["nominal_t95"][0] > 0
    for row in contrasts[primary_count:]:
        row.update(holm_p=None, gate_passed=None)
    worker_cpu = sum(row["child_total_cpu_seconds"] for row in complete["records"])
    assert abs(worker_cpu-complete["complete_child_cpu_seconds"]) < 1e-7
    result = dict(schema="hcsn-risk-analysis.v1", integrity_passed=True, protocol_sha256=digest,
        searches=len(results), candidates=len(results), all_registered_runs=results, contrasts=contrasts,
        gates_passed=sum(bool(row["gate_passed"]) for row in contrasts), primary_gates=primary_count,
        training_cpu_seconds=total_training,
        complete_worker_cpu_seconds=worker_cpu, coordinator_cpu_seconds=complete["coordinator_cpu_seconds"],
        energy_measured=False, scientific_scope=protocol["outcome_scope"],
        limitations=["Equal-CPU small-model mechanism diagnostic; not quality-matched cost or foundation scale",
                    "No new natural audiovisual data", "Common full physical information remains in every arm"])
    output.mkdir(parents=True, exist_ok=False)
    training._write_json(output / "RESULTS.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "PROTOCOL.json")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.protocol, args.study, args.output)
    print(json.dumps({key: result[key] for key in ("integrity_passed", "searches", "gates_passed")}))
