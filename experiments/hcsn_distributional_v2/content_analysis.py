"""Independent integrity checks and predeclared comparisons for content002."""

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp
from scipy.stats import t as student_t
import torch

from experiments.hcsn_free_boundary_v1 import training
from .content_study import ROOT, PACKAGE, file_hash, verify, write_json
from .model import DISTRIBUTION_ARMS, build_model


def read_json(path):
    return json.loads(Path(path).read_bytes())


def arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: np.array(archive[key], copy=True) for key in archive.files}


def common_hash(weights):
    h = hashlib.sha256()
    for name in sorted(k for k in weights if k.startswith(("frontend.", "readout."))):
        value = weights[name]
        h.update(name.encode())
        h.update(str(value.shape).encode())
        h.update(str(value.dtype).encode())
        h.update(value.tobytes())
    return h.hexdigest()


def audit_predictions(path, y, stated):
    archive = arrays(path)
    samples, steps = np.nonzero(y != -100)
    labels = y[samples, steps]
    assert np.array_equal(archive["supervised"], y != -100), "supervision mask"
    assert np.array_equal(archive["sample_indices"], samples), "sample coordinates"
    assert np.array_equal(archive["step_indices"], steps), "time coordinates"
    assert np.array_equal(archive["labels"], labels), "labels"
    logits = archive["logits"].astype(np.float64)
    assert logits.shape[0] == len(labels) and np.isfinite(logits).all(), "logits"
    predictions = logits.argmax(-1)
    assert np.array_equal(predictions, archive["predictions"]), "argmax"
    accuracy = float((predictions == labels).mean())
    ce = float(np.mean(logsumexp(logits, axis=-1) - logits[np.arange(len(labels)), labels]))
    assert abs(accuracy - stated["accuracy"]) < 1e-12, "accuracy summary"
    assert abs(ce - stated["cross_entropy"]) < 2e-6, "cross entropy summary"
    assert int(stated["supervised_positions"]) == len(labels), "count summary"
    return dict(accuracy=accuracy, cross_entropy=ce, supervised_positions=len(labels),
                sha256=file_hash(path), archive=archive)


def audit_run(study, protocol, job, data):
    key = f"{job['task']}__{job['model']}__{job['seed']}"
    folder = study / "runs" / key
    execution, summary, identity = (read_json(folder / name) for name in
                                    ("EXECUTION.json", "summary.json", "IDENTITY.json"))
    assert execution["job"] == job and execution["returncode"] == 0, "worker completion"
    assert execution["protocol_sha256"] == protocol["_sha256"], "execution protocol"
    assert execution["stdout_sha256"] == file_hash(study / "process_logs" / f"{key}.log"), "worker stdout identity"
    assert identity["job"] == job and identity["status"] == "completed", "worker identity"
    assert identity["protocol_sha256"] == protocol["_sha256"], "protocol hash"
    assert identity["source_files_sha256"] == protocol["source_files_sha256"], "worker source identity"
    assert identity["dataset_sha256"] == protocol["data"][job["task"]]["sha256"], "worker data identity"
    assert summary["status"] == "completed", "summary completion"
    candidates = summary["candidates"]
    assert [c["learning_rate"] for c in candidates] == protocol["optimization"]["learning_rates"], "LR set"
    assert summary["selection"] == read_json(folder / "selection.json"), "selection record"
    assert summary["selection"]["dataset_sha256"] == protocol["data"][job["task"]]["sha256"], "data identity"
    expected_model = build_model(job["model"], data["input_dim"], data["classes"],
        width=protocol["optimization"]["width"], depth=protocol["optimization"]["depth"], seed=job["seed"])
    expected_state = {name: value.detach().numpy() for name, value in expected_model.state_dict().items()}
    expected_counts = expected_model.counts()
    assert summary["counts"] == expected_counts, "actual parameter count"
    assert summary["selected_model_config"] == expected_model.config, "selected model configuration"
    target_counts = build_model("distribution_free_dual", data["input_dim"], data["classes"],
        width=protocol["optimization"]["width"], depth=protocol["optimization"]["depth"],
        seed=job["seed"]).counts()
    assert abs(expected_counts["backbone"]-target_counts["backbone"])/target_counts["backbone"] <= .03, "active parameter tolerance"
    group_names = {group: [name for name, _ in entries]
                   for group, entries in expected_model.parameter_groups().items()}
    scalar_names = [name for name in expected_state if any(part in name for part in
                    ("mu_bias", "raw_sigma", "raw_rho", "raw_K", "raw_reset", "raw_refractory"))]
    candidate_audits, shared_hashes = [], []
    for candidate in candidates:
        assert candidate["counts"] == expected_counts, "candidate parameter count"
        assert candidate["config"] == expected_model.config, "candidate configuration"
        directory = folder / candidate["directory"]
        disk_candidate = read_json(directory / "candidate.json")
        assert disk_candidate == {k: v for k, v in candidate.items() if k != "directory"}, "candidate summary"
        initial = arrays(directory / "initial.npz")
        assert set(initial) == set(expected_state), "initial tensor set"
        assert all(np.array_equal(initial[k], expected_state[k]) for k in initial), "seed initialization"
        assert file_hash(directory / "initial.npz") == candidate["initial_sha256"], "initial hash"
        shared_hashes.append(common_hash(initial))
        log = [json.loads(line) for line in (directory / "updates.jsonl").read_text().splitlines()]
        assert len(log) == candidate["updates"], "update count"
        generator = torch.Generator().manual_seed(job["seed"]+200003)
        digest = hashlib.sha256()
        gradient_max = {group: 0.0 for group in group_names}
        for index, row in enumerate(log, 1):
            ids = torch.randint(data["train_count"], (protocol["optimization"]["batch_size"],), generator=generator)
            raw = ids.numpy().tobytes()
            digest.update(raw)
            assert row["step"] == index, "step order"
            assert row["batch_sha256"] == hashlib.sha256(raw).hexdigest(), "minibatch hash"
            assert row["prefix_sha256"] == digest.hexdigest(), "full minibatch prefix"
            for group in group_names:
                entry = row["gradients"][group]
                assert entry["finite"] and np.isfinite(entry["l2"]), "finite gradient"
                assert entry["missing_elements"] == 0, "missing gradient"
                if index <= candidate["best"]["step"]:
                    gradient_max[group] = max(gradient_max[group], entry["max_abs"])
            if row.get("max_probability_mass_error") is not None:
                assert row["max_probability_mass_error"] <= 1e-4, "training mass"
        assert digest.hexdigest() == candidate["batch_prefix_sha256"], "terminal prefix"
        assert candidate["stopping_reason"] == "cpu_budget", "update cap does not replace equal CPU budget"
        assert candidate["training_cpu_seconds"] >= protocol["optimization"]["training_cpu_seconds_per_lr"], "CPU budget"
        assert candidate["primary_cpu_targets"] == protocol["optimization"]["primary_cpu_checkpoints"], "CPU gates"
        checkpoints = candidate["checkpoints"]
        assert checkpoints == read_json(directory / "checkpoints.json"), "checkpoint manifest"
        seen_gates = []
        expected_npz = {"initial.npz"}
        for point in checkpoints:
            expected_npz.add(point["weights"])
            assert file_hash(directory / point["weights"]) == point["sha256"], "checkpoint hash"
            crossed = point["crossed_cpu_targets"]
            seen_gates.extend(crossed)
            if not crossed:
                assert point["fixed_step_128"] and not point["primary_eligible"], "extra selection opportunity"
        assert seen_gates == protocol["optimization"]["primary_cpu_checkpoints"], "all common checkpoints"
        assert {x.name for x in directory.glob("*.npz")} == expected_npz, "unexpected or missing checkpoint"
        best = min((c for c in checkpoints if c["primary_eligible"]),
                   key=lambda c: (c["validation"]["cross_entropy"], c["training_cpu_seconds"], c["step"]))
        assert candidate["best"] == best, "within LR selection"
        selected = arrays(directory / best["weights"])
        changes = {group: float(np.sqrt(sum(np.sum((selected[name].astype(np.float64)-
                       initial[name].astype(np.float64))**2) for name in names)))
                   for group, names in group_names.items()}
        assert all(value > 0 for value in gradient_max.values()), "effective group gradients"
        assert all(value > 0 for value in changes.values()), "actual group updates"
        scalars = {name: float(np.max(np.abs(selected[name]-initial[name]))) for name in scalar_names}
        if job["model"] in DISTRIBUTION_ARMS:
            assert all(value > 0 for value in scalars.values()), "individual physical tensor update"
        candidate_audits.append(dict(learning_rate=candidate["learning_rate"], updates=len(log),
            all_prefix_steps_checked=len(log), selected_step=best["step"],
            selected_group_change_l2=changes, observed_group_gradient_max=gradient_max,
            selected_physical_tensor_max_change=scalars,
            training_cpu_seconds=candidate["training_cpu_seconds"],
            fixed128_available=any(c["fixed_step_128"] for c in checkpoints)))
    assert shared_hashes[0] == shared_hashes[1], "LR paired common initialization"
    winner = min(candidates, key=lambda c: (c["best"]["validation"]["cross_entropy"], c["learning_rate"]))
    selection = summary["selection"]
    assert selection["selected_learning_rate"] == winner["learning_rate"], "across LR selection"
    assert selection["selected_step"] == winner["best"]["step"], "selected update"
    assert selection["selected_checkpoint_sha256"] == winner["best"]["sha256"], "selected identity"
    assert file_hash(folder / "selected.npz") == winner["best"]["sha256"], "selected file"
    log = summary["access_log"]
    lock = next(i for i, row in enumerate(log) if row["event"] == "selection_locked")
    assert log[lock]["completed_lr_candidates"] == 2, "two completed LRs before lock"
    assert all(i > lock for i, row in enumerate(log) if row.get("split") in ("test", "ood")), "heldout order"
    predictions = {}
    for split in ("test", "ood"):
        if split not in data["labels"]:
            assert summary["holdout"][split] is None, "unexpected OOD"
            continue
        checked = audit_predictions(folder / f"{split}_predictions.npz", data["labels"][split],
                                    summary["holdout"][split])
        if split == "test":
            training.load_weights(folder / "selected.npz", expected_model)
            expected_model.eval()
            with torch.no_grad():
                replay = expected_model(data["replay_x"], data["replay_dt"],
                                        return_sequence=True, return_aux=False).numpy()
            archive = checked["archive"]
            keep = archive["sample_indices"] < len(replay)
            actual = replay[archive["sample_indices"][keep], archive["step_indices"][keep]]
            difference = float(np.max(np.abs(actual-archive["logits"][keep])))
            assert difference <= 5e-5, "selected checkpoint inference replay"
            checked["replay_max_abs_logit_error"] = difference
            checked["replay_samples"] = len(replay)
        del checked["archive"]
        predictions[split] = checked
    return dict(job=job, valid=True, shared_initialization_sha256=shared_hashes[0],
        candidates=candidate_audits, predictions=predictions, counts=summary["counts"],
        complete_child_cpu_seconds=execution["child_total_cpu_seconds"],
        maximum_heldout_mass_error=max((r["max_mass_error"] for r in summary["holdout"].values()
                                       if r and r.get("distribution_audited")), default=None))


def exact_sign_flip(values):
    values = np.asarray(values, dtype=float)
    observed = abs(values.mean())
    means = [abs(np.mean(values*np.asarray(signs)))
             for signs in itertools.product((-1, 1), repeat=len(values))]
    return sum(x >= observed-1e-15 for x in means)/len(means)


def holm(values):
    result, running = [None]*len(values), 0.0
    order = np.argsort(values)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(values)-rank)*values[index]))
        result[index] = running
    return result


def analyze(protocol_path, study, output):
    protocol, study, output = verify(protocol_path), Path(study), Path(output)
    protocol["_sha256"] = file_hash(protocol_path)
    output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    completion = read_json(study / "COMPLETE.json")
    assert completion["protocol_sha256"] == protocol["_sha256"], "completion protocol"
    assert completion["status"] == "completed" and not completion.get("unstarted"), "completed full matrix"
    prior = protocol["prior_aborted_study"]
    assert file_hash(ROOT / prior["receipt"]) == prior["receipt_sha256"], "prior failed study retained"
    expected_jobs = {(j["task"], j["model"], j["seed"]) for j in protocol["jobs"]}
    completed_jobs = [(r["job"]["task"], r["job"]["model"], r["job"]["seed"])
                      for r in completion["records"]]
    assert len(completed_jobs) == len(expected_jobs) and set(completed_jobs) == expected_jobs, "completion coverage"
    assert completion["expected"] == len(expected_jobs) == completion["completed"], "completion counts"
    assert completion["complete_child_cpu_seconds"] == sum(r["child_total_cpu_seconds"]
                                                           for r in completion["records"]), "total worker cost"
    for record in completion["records"]:
        job = record["job"]
        name = f"{job['task']}__{job['model']}__{job['seed']}"
        assert read_json(study / "runs" / name / "EXECUTION.json") == record, "completion/worker ledger agreement"
        assert record["child_total_cpu_seconds"] == record["child_user_cpu_seconds"]+record["child_system_cpu_seconds"], "worker CPU components"
        assert np.isfinite(record["child_total_cpu_seconds"]) and record["child_total_cpu_seconds"] >= 0, "finite cost"
    torch.set_num_threads(1)
    datasets = {}
    for task, record in protocol["data"].items():
        with np.load(ROOT / record["path"], allow_pickle=False) as archive:
            datasets[task] = dict(train_count=archive["train_y"].shape[0], classes=record["output_dim"],
                input_dim=archive["train_x"].shape[-1],
                labels={split: np.array(archive[f"{split}_y"], copy=True) for split in ("test", "ood")
                        if f"{split}_y" in archive},
                replay_x=torch.as_tensor(np.array(archive["test_x"][:4], copy=True), dtype=torch.float32),
                replay_dt=torch.as_tensor(np.array(archive["test_dt"][:4], copy=True), dtype=torch.float32))
    audits = []
    for job in protocol["jobs"]:
        try:
            audit = audit_run(study, protocol, job, datasets[job["task"]])
        except Exception as error:
            audit = dict(job=job, valid=False, error=f"{type(error).__name__}: {error}")
        audits.append(audit)
    indexed = {(a["job"]["task"], a["job"]["model"], a["job"]["seed"]): a for a in audits}
    common_mismatches = []
    for task, seed in sorted({(j["task"], j["seed"]) for j in protocol["jobs"]}):
        rows = [row for row in audits if row["job"]["task"]==task and row["job"]["seed"]==seed]
        digests = {row["shared_initialization_sha256"] for row in rows if row["valid"]}
        if len(digests) > 1:
            common_mismatches.append(dict(task=task, seed=seed))
    core_rows = []
    for task in protocol["core"]["tasks"]:
        for model in protocol["core"]["models"]:
            rows = [indexed[(task, model, seed)] for seed in protocol["core"]["seeds"]]
            for split in ("test", "ood"):
                valid = all(row["valid"] and split in row["predictions"] for row in rows)
                values = [row["predictions"][split]["accuracy"] for row in rows] if valid else []
                core_rows.append(dict(task=task, model=model, split=split, complete=valid,
                    mean=float(np.mean(values)) if values else None,
                    sd=float(np.std(values, ddof=1)) if len(values)>1 else None,
                    values=values))
    mechanism = []
    for comparison in protocol["mechanism"]["contrasts"]:
        differences = []
        for seed in protocol["mechanism"]["seeds"]:
            paired = [(indexed[(task, protocol["mechanism"]["reference"], seed)], indexed[(task, comparison, seed)])
                      for task in protocol["mechanism"]["tasks"]]
            if all(a["valid"] and b["valid"] for a, b in paired):
                differences.append(float(np.mean([a["predictions"]["test"]["accuracy"]-
                                                  b["predictions"]["test"]["accuracy"] for a, b in paired])))
        complete = len(differences) == len(protocol["mechanism"]["seeds"])
        row = dict(comparison=comparison, complete=complete, seed_differences=differences)
        if complete:
            mean, sd = float(np.mean(differences)), float(np.std(differences, ddof=1))
            radius = float(student_t.ppf(.975, len(differences)-1)*sd/np.sqrt(len(differences)))
            row.update(mean=mean, interval=[mean-radius, mean+radius], p=exact_sign_flip(differences))
        mechanism.append(row)
    if all(row["complete"] for row in mechanism):
        for row, adjusted in zip(mechanism, holm([row["p"] for row in mechanism]), strict=True):
            row.update(holm_p=adjusted, positive_gate=(not common_mismatches and
                row["mean"]>=.01 and adjusted<=.05 and row["interval"][0]>0))
    screens = []
    for task in protocol["core"]["tasks"]:
        rows = {r["model"]: r for r in core_rows if r["task"] == task and r["split"] == "test"}
        names = ("legacy_free", "two_gates", "transformer")
        complete = all(rows[name]["complete"] for name in names+("distribution_free_dual",))
        if complete:
            best = max(names, key=lambda name: rows[name]["mean"])
            gap = rows["distribution_free_dual"]["mean"]-rows[best]["mean"]
            screens.append(dict(task=task, complete=True, best_external=best, gap=gap,
                                screen=(gap>=-.02 and not common_mismatches)))
        else:
            screens.append(dict(task=task, complete=False, screen=False))
    result = dict(schema="hcsn-distribution-content-analysis.v2", protocol_sha256=protocol["_sha256"],
        analyzer_sha256=file_hash(__file__), expected=len(protocol["jobs"]),
        valid=sum(a["valid"] for a in audits), invalid=sum(not a["valid"] for a in audits),
        common_initialization_mismatches=common_mismatches, audits=audits,
        core=core_rows, mechanism=mechanism, content_screens=screens,
        positive_mechanism_gates=sum(row.get("positive_gate", False) for row in mechanism),
        passed_content_screens=sum(row["screen"] for row in screens),
        complete_child_cpu_seconds=completion["complete_child_cpu_seconds"],
        coordinator_cpu_seconds=completion["coordinator_cpu_seconds"],
        prior_aborted_study_cost=prior["cost"],
        both_study_worker_cpu_seconds=completion["complete_child_cpu_seconds"]+prior["cost"]["complete_worker_cpu_seconds"],
        training_cpu_seconds=sum(c["training_cpu_seconds"] for a in audits if a["valid"] for c in a["candidates"]),
        analysis_body_cpu_seconds=time.process_time()-started,
        inference_replay="first4test samples every selected checkpoint, max_abs tolerance5e-5",
        statistical_scope="post-v1/content001 source-registered study; same previously observed test datasets; three-seed core descriptive")
    write_json(output / "ANALYSIS.json", result)
    with (output / "CORE_TABLE.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("task", "model", "split", "complete", "mean", "sd"))
        writer.writeheader()
        writer.writerows({k:r[k] for k in writer.fieldnames} for r in core_rows)
    lines = ["# Retained-distribution content study", "", f"Integrity: **{result['valid']}/{result['expected']} valid**, {result['invalid']} invalid.",
             f"Positive mechanism gates: **{result['positive_mechanism_gates']}/4**. Descriptive content screens: **{result['passed_content_screens']}/6**.", "",
             "## Three-seed core ID accuracy", "", "| Model | Copy | MQAR | Irregular | MNIST | FSDD | Multimodal |", "|---|---:|---:|---:|---:|---:|---:|"]
    for model in protocol["core"]["models"]:
        cells = []
        for task in protocol["core"]["tasks"]:
            r = next(r for r in core_rows if r["model"]==model and r["task"]==task and r["split"]=="test")
            cells.append(f"{100*r['mean']:.2f} ± {100*r['sd']:.2f}" if r["complete"] else "incomplete")
        lines.append("| "+model+" | "+" | ".join(cells)+" |")
    lines += ["", f"## {len(protocol['mechanism']['seeds'])}-seed paired mechanism comparisons", "", "Differences are free distribution dual minus comparison, averaged over the two fixed tasks within each seed. Intervals are nominal; four exact two-sided sign-flip p values share one Holm family.", "",
              "| Comparison | Difference pp | Nominal 95% interval pp | Holm p | Positive gate |", "|---|---:|---|---:|---|"]
    for row in mechanism:
        if row["complete"] and "holm_p" in row:
            lo, hi = row["interval"]
            lines.append(f"| {row['comparison']} | {100*row['mean']:.3f} | [{100*lo:.3f}, {100*hi:.3f}] | {row['holm_p']:.6f} | {row['positive_gate']} |")
        else:
            lines.append(f"| {row['comparison']} | incomplete | | | False |")
    lines += ["", "## Scope and costs", "", f"Complete search worker CPU: **{result['complete_child_cpu_seconds']:.6f} s**. Coordinator self CPU: **{result['coordinator_cpu_seconds']:.6f} s**. Training CPU inside valid workers: **{result['training_cpu_seconds']:.6f} s**, a nested component, not an additional charge.", "",
              f"The invalid-duration content001 registration remains sealed: {prior['started_searches']} searches started, {prior['completed_searches']} completed and {prior['failed_searches']} failed. Its complete worker cost was **{prior['cost']['complete_worker_cpu_seconds']:.6f} s**. Combined worker CPU across both studies is **{result['both_study_worker_cpu_seconds']:.6f} s**, before engineering, analysis or separate execution work. No content001 scores or weights enter these comparisons; its completed searches did expose heldout outcomes, and this rerun is not fresh-test confirmation.", "",
              "All seven models use the same frontend/readout initialization and actual paired minibatch sequence. Backbone counts differ by at most3%; conditional threshold adds16 active parameters. The ordinary physical-feature arm sees the complete probability and the same seven physical coefficients. The legacy comparator is the original mean-state mechanism with active projections and a re-matched internal width, retrained here.", "",
              "The ordinary-feature arm omits its unused J/G solve, so it is not charged for unnecessary value computation. Its active_center_variance feature is an active-mass-weighted conditional cell-center variance, excluding within-cell and refractory-position variance. The conditional threshold uses a bounded gap(.01,4) to preserve its grid's reset/initial-state validity; its two learned boundary coefficients are unchanged in number.", "",
              f"The {protocol['optimization']['training_cpu_seconds_per_lr']:g} training CPU second budget and common {protocol['optimization']['primary_cpu_checkpoints']} CPU checkpoints were fixed before this study's heldout evaluation, after train-only engineering probes. Both LR candidates finish before selection is locked; fixed128 snapshots add no primary selection opportunity. No failed search may disappear from comparisons.", "",
              "The registered neural numerical profile uses fixed uniformization rate8.1 and21Poisson terms per substep. Each token uses max(1,ceil(physical_dt/.36)) equal substeps with one boundary remapping; binary composition preserves all event/reward integrals and leaves completed neighboring tokens unchanged. The explicit resource cap is1048576substeps. Neither a future suffix nor a neighboring sample selects another token's numerical effort. This repairs content001's incorrect per-observation duration bound. Adaptive oracle profiles remain separate.", "",
              "The physical model retains eight spatial cells and two Erlang phases; it is not exact Brownian dynamics. The input-dependent analytic boundary uses the Brownian/Erlang optimum, while J/G evaluate its actual finite-generator policy. Neither value is a proved classification Bellman value. Active-mean collapse preserves every refractory phase and is not identical to the old v1 mean/cooldown implementation.", "",
              "Synthetic OOD doubles length32→64; irregular OOD additionally multiplies the dt distribution by3. Real tasks have no OOD split. FSDD uses600speaker-disjoint recordings with repeated episodes and offline features; this is not a foundation-model or broad speech benchmark. Core statistics use three seeds and are descriptive. The two mechanism tasks are fixed, not a random task population. Same test datasets were already observed during v1 and partial content001; this is a registered post-baseline study, not fresh-test confirmation.", "",
              "ANALYSIS.json records all prediction-coordinate/label/CE checks, complete minibatch prefixes, source/selection identities, actual parameter updates, checkpoint inference replay and available OOD results. Missing/invalid evidence makes the affected contrast incomplete. Energy was not measured."]
    (output / "REPORT.md").write_text("\n".join(lines)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "CONTENT002_PROTOCOL.json")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.protocol, args.study, args.output)
    print(json.dumps({k:result[k] for k in ("expected", "valid", "invalid", "positive_mechanism_gates", "passed_content_screens")}), flush=True)
