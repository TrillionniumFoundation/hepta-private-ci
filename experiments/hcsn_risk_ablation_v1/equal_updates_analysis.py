"""Verify fixed update128 exposure and apply the frozen paired contrasts."""

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


def analyze(protocol_path, study, output, equal_cpu_analysis=None):
    study, output = Path(study), Path(output)
    if output.exists():
        raise FileExistsError("Preserve prior analysis")
    torch.set_num_threads(1)
    protocol = verify(protocol_path)
    digest = training._sha256(protocol_path)
    complete = read_json(study / "COMPLETE.json")
    assert complete["status"] == "completed" and complete["failures"] == 0
    assert complete["protocol_sha256"] == digest
    key = lambda row: (row["task"], row["model"], row["seed"])
    ledger = {key(row["job"]): row for row in complete["records"]}
    assert len(ledger) == len(complete["records"]) == 112
    assert set(ledger) == {key(job) for job in protocol["jobs"]}
    data = {task: arrays(ROOT / row["path"]) for task, row in protocol["data"].items()}
    results, shared = [], {}
    for job in protocol["jobs"]:
        name = "__".join(map(str, key(job)))
        folder = study / "runs" / name
        execution = read_json(folder / "EXECUTION.json")
        assert execution == ledger[key(job)] and execution["returncode"] == 0
        assert execution["stdout_sha256"] == training._sha256(study / "process_logs" / (name + ".log"))
        summary, identity = (read_json(folder / filename) for filename in ("summary.json", "IDENTITY.json"))
        assert summary["status"] == identity["status"] == "completed" and summary["job"] == job
        assert identity["protocol_sha256"] == summary["protocol_sha256"] == digest
        assert identity["source_files_sha256"] == protocol["source_files_sha256"]
        assert identity["dataset_sha256"] == protocol["data"][job["task"]]["sha256"]
        assert summary["updates"] == 128 and summary["stopping_reason"] == "fixed_128_updates"
        assert 0 < summary["training_cpu_seconds"] <= 900
        assert execution["child_total_cpu_seconds"] >= summary["training_cpu_seconds"]
        dataset = data[job["task"]]
        model = build_model(job["model"], dataset["train_x"].shape[-1], int(dataset["train_y"].max())+1,
                            width=32, depth=1, seed=job["seed"])
        assert model.config == summary["config"] and model.counts() == summary["counts"]
        initial = arrays(folder / "initial.npz")
        expected = {name: value.detach().numpy() for name, value in model.state_dict().items()}
        assert set(initial) == set(expected) and all(np.array_equal(initial[n], expected[n]) for n in initial)
        assert training._sha256(folder / "initial.npz") == summary["initial_sha256"]
        pair, common = (job["task"], job["seed"]), common_hash(initial)
        assert shared.setdefault(pair, common) == common
        logs = [json.loads(line) for line in (folder / "updates.jsonl").read_text().splitlines()]
        assert len(logs) == 128
        generator, prefix = torch.Generator().manual_seed(job["seed"]+200003), hashlib.sha256()
        for step, row in enumerate(logs, 1):
            raw = torch.randint(len(dataset["train_x"]), (32,), generator=generator).numpy().tobytes()
            prefix.update(raw)
            assert row["step"] == step and row["batch_sha256"] == hashlib.sha256(raw).hexdigest()
            assert row["prefix_sha256"] == prefix.hexdigest()
            assert all(g["finite"] and g["missing_elements"] == 0 for g in row["gradients"].values())
            assert row["max_probability_mass_error"] <= 1e-6
            assert row["max_projection_l1"] <= 260*np.finfo(np.float32).eps
            if "min_first_event_probability" in row:
                assert row["min_first_event_probability"] >= -1e-9
                assert row["max_first_event_probability"] <= 1 + 2e-6
        assert prefix.hexdigest() == summary["batch_prefix_sha256"]
        assert logs[-1]["training_cpu_seconds"] == summary["training_cpu_seconds"]
        selection = read_json(folder / "selection.json")
        assert selection == summary["selection"] and selection["selected_step"] == 128
        assert selection["rule"] == "fixed_update_128_no_validation_selection"
        assert selection["selected_learning_rate"] == .001
        assert selection["selected_checkpoint_sha256"] == training._sha256(folder / "step_000128.npz")
        assert not list(folder.glob("step_0000*.npz")), "Unexpected earlier selectable checkpoint"
        access = summary["access_log"]
        locks = [i for i, row in enumerate(access) if row["event"] == "selection_locked"]
        assert len(locks) == 1 and access[locks[0]]["step"] == 128
        assert access[locks[0]]["validation_seen"] is False
        assert all(i > locks[0] for i, row in enumerate(access) if row.get("split") in ("val", "test", "ood"))
        selected = arrays(folder / "step_000128.npz")
        physical = {name: float(np.max(np.abs(value-initial[name]))) for name, value in selected.items()
            if any(part in name for part in ("mu_bias", "raw_sigma", "raw_rho", "raw_K", "raw_reset", "raw_refractory", "raw_boundary"))}
        assert all(value > 0 for value in physical.values())
        evaluation = {}
        for split in ("val", "test", "ood"):
            if split + "_y" not in dataset:
                assert summary["evaluation"][split] is None
                continue
            checked = audit_predictions(folder / (split + "_predictions.npz"), dataset[split + "_y"], summary["evaluation"][split])
            checked.pop("archive")
            evaluation[split] = checked
        training.load_weights(folder / "step_000128.npz", model)
        model.eval()
        with torch.no_grad():
            replay = model(torch.from_numpy(dataset["test_x"][:4]).float(),
                torch.from_numpy(dataset["test_dt"][:4]).float(), return_sequence=True, return_aux=False).numpy()
        predictions = arrays(folder / "test_predictions.npz")
        keep = predictions["sample_indices"] < 4
        error = float(np.max(np.abs(replay[predictions["sample_indices"][keep], predictions["step_indices"][keep]]-predictions["logits"][keep])))
        assert error <= 5e-5
        results.append(dict(**job, evaluation=evaluation, physical_tensor_changes=physical,
            replay_max_abs_error=error, training_cpu_seconds=summary["training_cpu_seconds"],
            worker_cpu_seconds=execution["child_total_cpu_seconds"], updates=128))
    lookup, contrasts = {key(row): row for row in results}, []
    primary_count = len(protocol["mechanism"]["contrasts"])
    all_contrasts = protocol["mechanism"]["contrasts"] + protocol["mechanism"]["secondary_contrasts"]
    for index, comparison in enumerate(all_contrasts):
        a, b = comparison["treatment"], comparison["control"]
        differences = [float(np.mean([lookup[(task,a,seed)]["evaluation"]["test"]["accuracy"] -
            lookup[(task,b,seed)]["evaluation"]["test"]["accuracy"] for task in protocol["data"]]))
            for seed in protocol["seeds"]]
        mean = float(np.mean(differences))
        half = float(student_t.ppf(.975, 7)*np.std(differences, ddof=1)/np.sqrt(8))
        contrasts.append(dict(**comparison, differences=differences, mean_accuracy_gain=mean,
            family="primary" if index < primary_count else "descriptive_secondary",
            nominal_t95=[mean-half, mean+half], exact_sign_flip_p=exact_sign_flip(differences)))
    primary = contrasts[:primary_count]
    for row, adjusted in zip(primary, holm([r["exact_sign_flip_p"] for r in primary]), strict=True):
        row.update(holm_p=adjusted, gate_passed=row["mean_accuracy_gain"] >= .01 and adjusted <= .05 and row["nominal_t95"][0] > 0)
    for row in contrasts[primary_count:]:
        row.update(holm_p=None, gate_passed=None)
    joint, cpu_analysis_hash = None, None
    if equal_cpu_analysis is not None:
        equal_cpu_analysis = Path(equal_cpu_analysis)
        cpu = read_json(equal_cpu_analysis)
        assert cpu["integrity_passed"] and cpu["protocol_sha256"] == protocol["model_identity"]["equal_cpu_protocol_sha256"]
        cpu_analysis_hash = training._sha256(equal_cpu_analysis)
        previous = {(row["treatment"], row["control"]): row for row in cpu["contrasts"]}
        joint = [dict(treatment=row["treatment"], control=row["control"],
            equal_updates_gate=row["gate_passed"], equal_cpu_gate=previous[(row["treatment"],row["control"])]["gate_passed"],
            both_gates_passed=bool(row["gate_passed"] and previous[(row["treatment"],row["control"])]["gate_passed"]))
            for row in primary]
    worker_cpu = sum(row["child_total_cpu_seconds"] for row in complete["records"])
    assert abs(worker_cpu-complete["complete_child_cpu_seconds"]) < 1e-7
    result = dict(schema="hcsn-risk-equal-updates-analysis.v1", integrity_passed=True, protocol_sha256=digest,
        searches=112, optimizer_updates=14336, all_registered_runs=results, contrasts=contrasts,
        gates_passed=sum(bool(r["gate_passed"]) for r in primary), primary_gates=primary_count,
        training_cpu_seconds=sum(row["training_cpu_seconds"] for row in results),
        complete_worker_cpu_seconds=worker_cpu, coordinator_cpu_seconds=complete["coordinator_cpu_seconds"],
        joint_gates=joint, equal_cpu_analysis_sha256=cpu_analysis_hash, joint_inference=protocol["joint_inference"],
        any_specific_predeclared_contrast_passes_both=False if joint is None else any(row["both_gates_passed"] for row in joint),
        architecture_wide_superiority_established=False,
        energy_measured=False, scientific_scope=protocol["outcome_scope"])
    output.mkdir(parents=True, exist_ok=False)
    training._write_json(output / "RESULTS.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "EQUAL_UPDATES_PROTOCOL.json")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--equal-cpu-analysis", type=Path)
    arguments = parser.parse_args()
    result = analyze(arguments.protocol, arguments.study, arguments.output, arguments.equal_cpu_analysis)
    print(json.dumps({key: result[key] for key in ("integrity_passed", "searches", "gates_passed")}))
