"""Independent, completion-gated AV actor/seed, bootstrap and cost audit.

This reader imports neither AV study/analysis/metrics nor Torch. It cannot open
study evidence until a retained GitHub run receipt identifies the completed run.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import resource
import sys
import tempfile
import time
import traceback

import numpy as np


EXPECTED_RUN = 41158089224
EXPECTED_SEAL = "6469cc94a72aed214c5c9d2ff2fba14cdb146626"
EXPECTED_DESIGN_SHA = "c722f33475adacb8711e4044cbd988f4a529303d06f2d2d7ec20f1aca7c0ae35"
EXPECTED_DELIVERY_SHA = "a517a71dff4512edbd2d5e516bda6db73f9689f6b8973815f675fab9713c7b24"
BASE = Path(__file__).resolve().parents[1]
MODELS = ("value_jg", "two_gates", "transformer", "lif_snn", "mamba1")
SEEDS = tuple(range(882101, 882109))
STAGES = ("development", "fixed", "equal_cpu")


def digest(path):
    state = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            state.update(block)
    return state.hexdigest()


def emit(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def emit_bounded_audit(path, value):
    """Retain every check and input fingerprint without oversized Git blobs."""
    path = Path(path)
    for field in ("checks", "input_files", "errors"):
        items = value.pop(field)
        if isinstance(items, dict):
            items = [dict(path=key, **row) for key, row in sorted(items.items())]
        shards = []
        for index, start in enumerate(range(0, len(items), 160)):
            target = path.with_name(path.stem + "_" + field + f"_{index:04d}.json")
            emit(target, items[start:start + 160])
            if target.stat().st_size > 480000:
                raise ValueError("Independent audit shard exceeds the bounded publication limit")
            shards.append(dict(file=target.name, rows=min(160, len(items) - start),
                               bytes=target.stat().st_size, sha256=digest(target)))
        value[field + "_count"] = len(items)
        value[field + "_shards"] = shards
    emit(path, value)
    if path.stat().st_size > 480000:
        raise ValueError("Independent audit headline exceeds the bounded publication limit")


def classification(logits, labels):
    logits = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    if logits.shape != (len(labels), 6) or not np.isfinite(logits).all():
        raise ValueError("Six finite class logits per recording are required")
    if np.any(labels < 0) or np.any(labels >= 6):
        raise ValueError("Class identity outside the declared six classes")
    centered = logits - logits.max(axis=1, keepdims=True)
    log_normalizer = np.log(np.exp(centered).sum(axis=1))
    probabilities = np.exp(centered - log_normalizer[:, None])
    predictions = logits.argmax(axis=1)
    correct = predictions == labels
    confidence = probabilities.max(axis=1)
    targets = np.eye(6)[labels]
    bins = np.clip(np.searchsorted(np.arange(11) / 10., confidence, side="right") - 1, 0, 9)
    correct_mass = np.bincount(bins, weights=correct.astype(float), minlength=10)
    confidence_mass = np.bincount(bins, weights=confidence, minlength=10)
    ece = np.abs(correct_mass - confidence_mass).sum() / len(labels)
    return dict(accuracy=float(correct.mean()),
        cross_entropy=float((log_normalizer - centered[np.arange(len(labels)), labels]).mean()),
        brier=float(((probabilities - targets) ** 2).sum(axis=1).mean()), ece=float(ece))


def crossed_bootstrap(matrix, random_seed):
    """Use multinomial frequency weights, independently of the study index gather."""
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (8, 8):
        raise ValueError("The primary contrast requires exactly eight paired seeds and eight actors")
    rng = np.random.default_rng(random_seed)
    distribution = []
    basis = np.eye(8, dtype=np.float64)
    for _ in range(20):
        seed_draws = rng.integers(8, size=(1000, 8))
        actor_draws = rng.integers(8, size=(1000, 8))
        seed_frequency = basis[seed_draws].sum(axis=1) / 8.
        actor_frequency = basis[actor_draws].sum(axis=1) / 8.
        distribution.extend(np.einsum("bi,ij,bj->b", seed_frequency, matrix, actor_frequency).tolist())
    lower, upper = np.quantile(distribution, [.025, .975])
    return dict(mean=float(matrix.mean()), percentile95=[float(lower), float(upper)],
        one_sided_bonferroni_lower=float(np.quantile(distribution, .05 / 8)))


class Audit:
    def __init__(self):
        self.inputs, self.checks, self.errors = {}, [], []

    def check(self, name, condition, detail=None):
        self.checks.append(dict(name=name, passed=bool(condition), detail=detail))
        if not condition:
            self.errors.append(name)

    def touch(self, path):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Expected a regular evidence file: " + str(path))
        path = path.resolve()
        self.inputs[str(path)] = dict(bytes=path.stat().st_size, sha256=digest(path))
        return path

    def bounded(self, root, relative):
        part = Path(relative)
        if part.is_absolute() or ".." in part.parts:
            raise ValueError("Evidence path escapes its declared root")
        candidate = root / part
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError("Evidence path escapes its declared root")
        return candidate

    def read(self, path):
        return json.loads(self.touch(path).read_text())

    def array(self, path, keys):
        with np.load(self.touch(path), allow_pickle=False) as archive:
            return {key: np.array(archive[key], copy=True) for key in keys}

    def near(self, name, actual, expected, tolerance=2e-10):
        self.check(name, np.allclose(actual, expected, rtol=tolerance, atol=tolerance),
                   dict(actual=np.asarray(actual).tolist(), expected=np.asarray(expected).tolist()))


def gate_completed_run(audit, receipt_path):
    receipt = audit.read(receipt_path)
    expected = (receipt.get("id") == EXPECTED_RUN
                and receipt.get("head_sha") == EXPECTED_SEAL
                and receipt.get("status") == "completed"
                and receipt.get("repository", {}).get("full_name") == "TrillionniumFoundation/hepta-private-ci")
    audit.check("completed_exact_run_before_any_study_output_access", expected,
                {key: receipt.get(key) for key in ("id", "head_sha", "status", "conclusion", "updated_at")})
    if not expected:
        raise PermissionError("Refuse study-output access before the exact current run is completed")
    return receipt


def complete_runner_wall(audit, receipt_path, run):
    jobs = audit.read(receipt_path)
    records = jobs["jobs"]
    audit.check("complete_workflow_job_metadata", jobs["total_count"] == len(records) == 2
                and {row["name"] for row in records} == {"experiments", "publish"}
                and all(row["run_id"] == EXPECTED_RUN and row["head_sha"] == EXPECTED_SEAL
                        and row["status"] == "completed" for row in records))

    def stamp(value):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))

    times, rows = [], []
    for row in records:
        start, end = stamp(row["started_at"]), stamp(row["completed_at"])
        seconds = (end - start).total_seconds()
        audit.check("workflow_job_wall:" + row["name"], seconds >= 0)
        times.append((start, end))
        rows.append(dict(id=row["id"], name=row["name"], conclusion=row["conclusion"],
                         started_at=row["started_at"], completed_at=row["completed_at"],
                         occupied_runner_seconds=seconds))
    return dict(jobs=rows, total_occupied_runner_seconds=sum(row["occupied_runner_seconds"] for row in rows),
        execution_span_seconds=(max(end for _, end in times) - min(start for start, _ in times)).total_seconds(),
        creation_to_final_job_completion_seconds=(max(end for _, end in times) - stamp(run["created_at"])).total_seconds(),
        scope="Server-reported complete training/publication job wall times include setup, dependency installation, checkout, artifact I/O and cleanup. Queue time is included only in creation-to-final completion. Data acquisition was a different run.",
        complete_platform_cpu_seconds=None, complete_platform_energy_joules=None)


def expected_jobs(stage, choices):
    if stage == "development":
        return [dict(stage=stage, arm=arm, seed=882001, learning_rate=lr, updates=96,
                     id=f"{arm}__lr{lr:g}") for arm in MODELS for lr in (.001, .003)]
    return [dict(stage=stage, arm=arm, seed=seed, learning_rate=choices[arm]["learning_rate"],
                 updates=256, id=f"{arm}__seed{seed}") for arm in MODELS for seed in SEEDS]


def inspect(study, driver, receipt_path, jobs_receipt, source_root, audit):
    run = gate_completed_run(audit, receipt_path)
    runner_wall = complete_runner_wall(audit, jobs_receipt, run)
    protocol = audit.read(study / "PROTOCOL.json")
    protocol_sha = digest(study / "PROTOCOL.json")
    analysis = audit.read(study / "ANALYSIS.json")
    design_path = source_root / "experiments/hcsn_blocker_closure_v1/av/AV_DESIGN.json"
    audit.check("predeclared_design_bytes", digest(design_path) == EXPECTED_DESIGN_SHA)
    design = audit.read(design_path)
    delivery_path = design_path.with_name("AV_DELIVERY.json")
    delivery = audit.read(delivery_path)
    audit.check("pre-outcome_frozen_delivery_and_source_map", digest(delivery_path) == EXPECTED_DELIVERY_SHA
                and delivery["preflight_source_sha256"] == protocol["source_sha256"])
    audit.check("protocol_design_and_execution_seal", protocol["design"] == design
                and protocol["public_execution_commit"] == EXPECTED_SEAL
                and analysis["protocol_sha256"] == protocol_sha)
    manifest_path = audit.touch(study / "DATA_TRANSPORT_MANIFEST.json")
    transport_bytes = manifest_path.read_bytes()
    transport = json.loads(transport_bytes)
    transport_blob = hashlib.sha1(b"blob " + str(len(transport_bytes)).encode() + b"\0" + transport_bytes).hexdigest()
    dataset_path = study / "data/DATASET.json"
    dataset = audit.read(dataset_path)
    audit.check("immutable_published_cohort_identity", transport_blob == design["data_binding"]["transport_git_blob_sha1"]
                and transport["execution_seal"] == design["data_binding"]["acquisition_execution_seal"]
                and digest(dataset_path) == design["data_binding"]["dataset_sha256"]
                and protocol["data_evidence_commit"] == design["data_binding"]["commit"]
                and protocol["dataset"] == dataset)
    declared_files = {row["path"]: row for row in transport["files"]}
    audit.check("committed_transport_exact_input_inventory", len(declared_files) == len(transport["files"])
                == len(protocol["input_files"]) and set(declared_files) == {row["file"] for row in protocol["input_files"]}
                and set(declared_files) == {path.name for path in (study / "data").iterdir() if path.is_file()})
    for relative, expected in protocol["source_sha256"].items():
        path = audit.touch(audit.bounded(source_root, relative))
        audit.check("source_bytes:" + relative, digest(path) == expected)
    for row in protocol["input_files"]:
        path = audit.touch(audit.bounded(study / "data", row["file"]))
        original = declared_files[row["file"]]
        audit.check("data_bytes:" + row["file"], path.stat().st_size == row["bytes"] == original["bytes"]
                    and digest(path) == row["sha256"] == original["sha256"])
    lock = audit.read(study / "SELECTION_LOCK.json")
    audit.check("global_lock_bound_to_protocol", lock["protocol_sha256"] == protocol_sha
                and set(lock["choices"]) == set(MODELS))
    datasets = {}
    for split, count, actor_count in (("validation", 144, 6), ("test", 192, 8)):
        split_row = protocol["dataset"]["splits"][split]
        values = audit.array(audit.bounded(study / "data", split_row["path"]), ("y", "actor", "clip"))
        actors, sizes = np.unique(values["actor"], return_counts=True)
        audit.check(split + "_exact_actor_and_clip_population", len(values["y"]) == count
                    and len(set(values["clip"])) == count and len(actors) == actor_count
                    and np.all(sizes == 24) and set(actors.tolist()) == set(split_row["actors"]))
        audit.check(split + "_six_balanced_classes_within_every_actor", all(
            np.array_equal(np.bincount(values["y"][values["actor"] == actor], minlength=6), np.full(6, 4))
            for actor in actors))
        datasets[split] = values
    actors = sorted(np.unique(datasets["test"]["actor"]).tolist())
    records, costs, attempts = [], [], []

    def evaluation(job_dir, row, split):
        path = audit.bounded(job_dir, row["file"])
        audit.check(str(path.relative_to(study)) + "_bytes", digest(path) == row["sha256"])
        values = audit.array(path, ("labels", "actor", "clip", "audio_logits", "video_logits", "fused_logits"))
        truth = datasets[split]
        audit.check(str(path.relative_to(study)) + "_identities", all(np.array_equal(values[k], truth[v])
                    for k, v in (("labels", "y"), ("actor", "actor"), ("clip", "clip"))))
        audit.check(str(path.relative_to(study)) + "_additive_fusion", np.array_equal(
            values["fused_logits"], .5 * (values["audio_logits"] + values["video_logits"])))
        computed = {}
        for channel in ("audio", "video", "fused"):
            computed[channel] = classification(values[channel + "_logits"], values["labels"])
            for metric, actual in computed[channel].items():
                audit.near(str(path.relative_to(study)) + ":" + channel + ":" + metric,
                           actual, row["classification"][channel][metric])
        return values, computed

    for stage in STAGES:
        jobs = audit.read(study / ("jobs_" + stage + ".json"))
        ledger = audit.read(study / ("RUN_" + stage + ".json"))
        expected = expected_jobs(stage, lock["choices"])
        audit.check(stage + "_unique_exact_registered_matrix", len({job["id"] for job in jobs}) == len(expected)
                    and sorted(jobs, key=lambda x: x["id"]) == sorted(expected, key=lambda x: x["id"]))
        executed = {row["id"]: row for row in ledger["jobs"]}
        audit.check(stage + "_exact_attempt_inventory", len(executed) == len(ledger["jobs"]) == len(expected)
                    and set(executed) == {job["id"] for job in expected}
                    and all(executed[job["id"]]["job"] == job for job in expected if job["id"] in executed))
        audit.check(stage + "_all_attempts_complete", ledger["complete"] is True and ledger["failed"] == 0
                    and all(row["exit_code"] == 0 for row in ledger["jobs"]))
        for row in ledger["jobs"]:
            audit.check(stage + "/" + row["id"] + "_finite_whole_worker_cost", all(
                np.isfinite(row[key]) and row[key] > 0 for key in ("child_cpu_seconds", "wall_seconds", "maxrss_bytes")))
            attempts.append(dict(stage=stage, **row))
        audit.near(stage + "_ledger_cpu_sum", sum(row["child_cpu_seconds"] for row in ledger["jobs"]),
                   ledger["child_cpu_seconds"])
        for job in expected:
            if job["id"] not in executed or executed[job["id"]]["exit_code"] != 0:
                continue
            directory = study / stage / job["id"]
            result = audit.read(directory / "RESULT.json")
            audit.check(stage + "/" + job["id"] + "_result_identity", result["status"] == "complete"
                        and result["job"] == job and result["protocol_sha256"] == protocol_sha
                        and result["public_execution_commit"] == EXPECTED_SEAL and result["dt_override"] is None)
            selected = audit.read(directory / "selection.json")
            val_scores = []
            for validation in result["validations"]:
                _, measured = evaluation(directory, validation, "validation")
                val_scores.append((measured["fused"]["cross_entropy"], validation["step"], validation))
            best = min(val_scores, key=lambda value: value[:2])
            audit.check(stage + "/" + job["id"] + "_validation_selection", selected["step"] == best[1]
                        and selected["validation_sha256"] == best[2]["sha256"])
            audit.near(stage + "/" + job["id"] + "_selected_ce", selected["cross_entropy"], best[0])
            trajectory = audit.read(directory / "trajectory.json")
            clocks = np.array([row["training_cpu_seconds"] for row in trajectory])
            audit.check(stage + "/" + job["id"] + "_exact_updates_and_clock", len(trajectory) == result["updates"]
                        and [row["step"] for row in trajectory] == list(range(1, result["updates"] + 1))
                        and np.isfinite(clocks).all() and np.all(np.diff(np.r_[0., clocks]) > 0))
            audit.near(stage + "/" + job["id"] + "_training_clock", clocks[-1], result["training_cpu_seconds"])
            if stage == "equal_cpu":
                before = clocks[-2] if len(clocks) > 1 else 0.
                audit.check(stage + "/" + job["id"] + "_first_cpu_crossing", before < 60. <= clocks[-1])
            else:
                audit.check(stage + "/" + job["id"] + "_fixed_updates", result["updates"] == job["updates"])
            arrays, metrics = None, None
            if stage != "development":
                audit.check(stage + "/" + job["id"] + "_after_global_lock", result["started_utc"] >= lock["locked_utc"])
                arrays, metrics = evaluation(directory, result["test"], "test")
            else:
                audit.check(job["id"] + "_development_never_evaluated_test", result["test"] is None)
            whole = executed[job["id"]]
            audit.check(stage + "/" + job["id"] + "_training_nested_inside_worker", whole["child_cpu_seconds"] + .05
                        >= result["training_cpu_seconds"])
            audit.check(stage + "/" + job["id"] + "_worker_self_clock_nested", whole["child_cpu_seconds"] + .05
                        >= result["complete_process_cpu_seconds"])
            inference = result["inference"]
            audit.check(stage + "/" + job["id"] + "_inference_scope", inference["batch"] == 16
                        and inference["length"] == 32 and inference["warmup"] == 1 and inference["repetitions"] == 5
                        and len(inference["samples"]) == 5)
            for clock in ("cpu_seconds", "wall_seconds"):
                audit.near(stage + "/" + job["id"] + "_inference_median_" + clock,
                           np.median([sample[clock] for sample in inference["samples"]]), inference["median_" + clock])
            records.append(dict(job=job, result=result, selected=selected, validation_ce=best[0], arrays=arrays, metrics=metrics))
            costs.append(dict(stage=stage, arm=job["arm"], seed=job["seed"], updates=result["updates"],
                training_cpu_seconds=result["training_cpu_seconds"], worker_cpu_seconds=whole["child_cpu_seconds"],
                worker_wall_seconds=whole["wall_seconds"], peak_rss_bytes=whole["maxrss_bytes"],
                inference_cpu_median=result["inference"]["median_cpu_seconds"],
                inference_wall_median=result["inference"]["median_wall_seconds"]))

    for arm in MODELS:
        development = [row for row in records if row["job"]["stage"] == "development" and row["job"]["arm"] == arm]
        audit.check(arm + "_two_development_candidates", len(development) == 2)
        if len(development) != 2:
            continue
        winner = min(development, key=lambda row: (row["validation_ce"], row["selected"]["step"], row["job"]["learning_rate"]))
        choice = lock["choices"][arm]
        path = study / "development" / winner["job"]["id"] / "RESULT.json"
        audit.check(arm + "_independent_lr_argmin", choice["learning_rate"] == winner["job"]["learning_rate"]
                    and choice["result_file"] == str(path.relative_to(study)) and choice["result_sha256"] == digest(path)
                    and all(row["result"]["completed_utc"] <= lock["locked_utc"] for row in development))
        audit.near(arm + "_independent_dev_ce", choice["development_cross_entropy"], winner["validation_ce"])

    matrices, contrasts = {}, []
    reported_contrasts = {(row["stage"], row["control"]): row for row in analysis["primary_contrasts"]}
    audit.check("unique_eight_reported_primary_contrasts", len(reported_contrasts) == len(analysis["primary_contrasts"]) == 8)
    for stage in ("fixed", "equal_cpu"):
        matrices[stage] = {}
        for arm in MODELS:
            group = sorted([row for row in records if row["job"]["stage"] == stage and row["job"]["arm"] == arm],
                           key=lambda row: row["job"]["seed"])
            audit.check(stage + "/" + arm + "_exact_eight_seed_pairing", [row["job"]["seed"] for row in group] == list(SEEDS))
            if len(group) != 8:
                continue
            matrix = np.array([[float(np.mean((row["arrays"]["fused_logits"].argmax(axis=1) == row["arrays"]["labels"])
                              [row["arrays"]["actor"] == actor])) for actor in actors] for row in group])
            matrices[stage][arm] = matrix
            reported = analysis["summaries"][stage][arm]
            audit.check(stage + "/" + arm + "_actor_seed_order", reported["actor_order"] == actors
                        and reported["seed_order"] == list(SEEDS))
            audit.near(stage + "/" + arm + "_independent_actor_matrix", matrix, reported["actor_accuracy_matrix"])
            budget_rows = [row for row in costs if row["stage"] == stage and row["arm"] == arm]
            for original, summarized in (("updates", "mean_updates"),
                    ("training_cpu_seconds", "mean_training_cpu_seconds"),
                    ("worker_cpu_seconds", "mean_whole_worker_cpu_seconds"),
                    ("worker_wall_seconds", "mean_whole_worker_wall_seconds"),
                    ("inference_cpu_median", "mean_inference_median_cpu_seconds")):
                audit.near(stage + "/" + arm + ":cost:" + summarized,
                           np.mean([row[original] for row in budget_rows]), reported[summarized])
            for channel in ("audio", "video", "fused"):
                for metric in ("accuracy", "cross_entropy", "brier", "ece"):
                    audit.near(stage + "/" + arm + ":" + channel + ":" + metric,
                        np.mean([row["metrics"][channel][metric] for row in group]), reported["classification"][channel][metric])
        if len(matrices[stage]) != 5:
            continue
        for control in MODELS[1:]:
            interval = crossed_bootstrap(matrices[stage]["value_jg"] - matrices[stage][control], 883901 + len(contrasts))
            row = reported_contrasts[(stage, control)]
            for key, value in interval.items():
                audit.near(stage + "/" + control + ":bootstrap:" + key, value, row[key])
            a = analysis["summaries"][stage]["value_jg"]["classification"]["fused"]
            b = analysis["summaries"][stage][control]["classification"]["fused"]
            calibration = a["brier"] - b["brier"] <= .01 and a["ece"] - b["ece"] <= .02
            independent_gate = interval["mean"] >= .02 and interval["one_sided_bonferroni_lower"] > 0 and calibration
            published_gate = row["mean"] >= .02 and row["one_sided_bonferroni_lower"] > 0 and calibration
            ambiguity = (abs(interval["one_sided_bonferroni_lower"]) <= 2e-12
                         and abs(row["one_sided_bonferroni_lower"]) <= 2e-12
                         and (interval["one_sided_bonferroni_lower"] > 0) != (row["one_sided_bonferroni_lower"] > 0))
            audit.check(stage + "/" + control + "_unchanged_published_scientific_gate", row["passes_conditional_on_integrity"] == published_gate)
            audit.check(stage + "/" + control + "_independent_scientific_gate", independent_gate == published_gate or ambiguity,
                        dict(numerical_zero_boundary_ambiguity=bool(ambiguity),
                             published_lower=row["one_sided_bonferroni_lower"],
                             independent_lower=interval["one_sided_bonferroni_lower"]))
            audit.check(stage + "/" + control + "_integrity_qualified_scientific_gate", row["passes"] == (analysis["complete"] and published_gate))
            contrasts.append(dict(stage=stage, control=control, **interval,
                independent_conditional_scientific_pass=bool(independent_gate),
                published_conditional_scientific_pass=bool(published_gate), numerical_zero_boundary_ambiguity=bool(ambiguity)))

    audit.check("overall_predeclared_scientific_gate", analysis["external_net_benefit_pass"] == (analysis["complete"]
                and len(contrasts) == 8 and all(row["published_conditional_scientific_pass"] for row in contrasts)))

    measured_workers = sum(row["child_cpu_seconds"] for row in attempts)
    measured_training = sum(row["training_cpu_seconds"] for row in costs)
    audit.near("all_attempt_whole_worker_cpu", measured_workers, analysis["measured_worker_cpu_seconds"])
    audit.near("all_valid_training_cpu_is_nested", measured_training, analysis["measured_training_cpu_seconds"])
    audit.near("maximum_worker_rss", max(row["maxrss_bytes"] for row in attempts), analysis["max_worker_rss_bytes"])
    full_pipeline, decoder = [], []
    for stage in ("prepare", "train", "finalize"):
        path = driver / stage / ("RUNNER_" + stage.upper() + "_RESULT.json")
        value = audit.read(path)
        child = sum(row["complete_child_cpu_seconds"] for row in value["subprocesses"])
        audit.check(stage + "_all_driver_children_accounted", value["all_child_costs_known"] is True)
        audit.near(stage + "_disjoint_driver_child_sum", child, value["direct_child_cpu_seconds"])
        full_pipeline.append(dict(stage=stage, direct_child_cpu_seconds=child,
            coordinator_body_cpu_seconds=value["coordinator_self_cpu_seconds"],
            nonoverlap_cpu_seconds=child + value["coordinator_self_cpu_seconds"], wall_seconds=value["stage_wall_seconds"]))
    audit.check("training_stage_contains_complete_worker_cpu", next(row for row in full_pipeline if row["stage"] == "train")
                ["direct_child_cpu_seconds"] + .05 >= measured_workers)
    for name in ("REGISTER_COST.json", "ACQUIRE_COST.json", "PREPARE_COST.json"):
        value = audit.read(study / "data" / name)
        decoder.append(dict(file=name, python_cpu_seconds=value["python_cpu_seconds"],
            child_cpu_seconds=value["direct_children_cpu_seconds"],
            nonoverlap_cpu_seconds=value["python_cpu_seconds"] + value["direct_children_cpu_seconds"],
            wall_seconds=value["wall_seconds"], success=value["success"]))
    nested = audit.read(study / "data/PREPARATION_COST.json")
    outer_prepare = next(row for row in decoder if row["file"] == "PREPARE_COST.json")
    audit.check("decoder_detail_nested_in_prepare", outer_prepare["nonoverlap_cpu_seconds"] + .05 >= nested["total_cpu_seconds"])
    audit.check("energy_and_gpu_not_fabricated", analysis["direct_energy_joules"] is None and analysis["gpu_executed"] is False)
    audit.check("exact_ninety_valid_jobs", len(records) == len(attempts) == 90 and analysis["valid_jobs"] == 90
                and analysis["complete"] is True and analysis["errors"] == [])
    return dict(run={key: run.get(key) for key in ("id", "head_sha", "status", "conclusion", "updated_at")},
        valid_jobs=len(records), attempted_jobs=len(attempts), failed_attempts=sum(row["exit_code"] != 0 for row in attempts),
        actor_order=actors, seed_order=list(SEEDS), actor_seed_matrices={stage: {arm: value.tolist() for arm, value in arms.items()}
            for stage, arms in matrices.items()}, contrasts=contrasts,
        independent_positive_claim_confirmed=not audit.errors and len(contrasts) == 8 and all(
            row["independent_conditional_scientific_pass"] and not row["numerical_zero_boundary_ambiguity"] for row in contrasts),
        numerical_boundary_rule="Keep the frozen published strict >0 gate unchanged; a sign disagreement with both bounds within2e-12 of zero is explicitly ambiguous and cannot independently confirm a positive claim.",
        cost_rows=costs, measured_worker_cpu_seconds=measured_workers, nested_training_cpu_seconds=measured_training,
        complete_training_and_publication_runner_wall=runner_wall,
        shared_pipeline_stages=full_pipeline, acquisition_stages=decoder,
        measured_nonoverlap_cpu_lower_bound=sum(row["nonoverlap_cpu_seconds"] for row in full_pipeline + decoder),
        excluded_from_lower_bound=["Launcher imports before RunBook construction", "Dependency installation and workflow checkout",
            "Acquisition process imports and data-transport packaging", "Artifact upload/download, final packaging and publication",
            "Any earlier failed acquisition or training attempt absent from these receipts"],
        accounting="Worker, optimizer, inference and decoder detail clocks are nested; never add them to the measured disjoint outer stages.",
        energy_joules=None, gpu_executed=False,
        narrow_scope="Actor/seed population, raw classification, selection, crossed bootstrap and measured costs only. Does not re-audit every retrieval rank, kernel proof or checkpoint tensor.")


def selfcheck(output):
    checks = []
    labels = np.arange(12) % 6
    uniform = classification(np.zeros((12, 6)), labels)
    assert np.isclose(uniform["cross_entropy"], np.log(6.))
    assert np.isclose(uniform["accuracy"], 1. / 6.) and np.isclose(uniform["brier"], 5. / 6.)
    assert np.isclose(uniform["ece"], 0.)
    checks.append("uniform_six_class_closed_form")
    confident = np.full((12, 6), -1000.)
    confident[np.arange(12), labels] = 1000.
    good = classification(confident, labels)
    assert good == dict(accuracy=1., cross_entropy=0., brier=0., ece=0.)
    checks.append("perfect_six_class_closed_form")
    matrix = np.linspace(-.2, .2, 64).reshape(8, 8)
    frequency = crossed_bootstrap(matrix, 992031)
    rng, direct = np.random.default_rng(992031), []
    for _ in range(20):
        seeds = rng.integers(8, size=(1000, 8))
        actors = rng.integers(8, size=(1000, 8))
        direct.extend(matrix[seeds[:, :, None], actors[:, None, :]].mean(axis=(1, 2)).tolist())
    assert np.allclose(frequency["percentile95"], np.quantile(direct, [.025, .975]), atol=1e-14)
    assert np.isclose(frequency["one_sided_bonferroni_lower"], np.quantile(direct, .05 / 8), atol=1e-14)
    checks.append("frequency_weight_bootstrap_equals_independent_explicit_draws")
    zeros = crossed_bootstrap(np.zeros((8, 8)), 992033)
    assert zeros == dict(mean=0., percentile95=[0., 0.], one_sided_bonferroni_lower=0.)
    checks.append("zero_effect_bootstrap_is_exactly_zero")
    with tempfile.TemporaryDirectory(prefix="hcsn-av-audit-guard-") as temporary:
        temporary = Path(temporary)
        for name, status, seal in (("pending", "in_progress", EXPECTED_SEAL),
                                   ("wrong_seal", "completed", "0" * 40)):
            path = temporary / (name + ".json")
            emit(path, dict(id=EXPECTED_RUN, head_sha=seal, status=status,
                            repository=dict(full_name="TrillionniumFoundation/hepta-private-ci")))
            guarded = Audit()
            try:
                gate_completed_run(guarded, path)
            except PermissionError:
                pass
            else:
                raise AssertionError("Noncompleted or wrong-seal run was accepted")
            assert list(guarded.inputs) == [str(path.resolve())]
            checks.append(name + "_run_rejected_before_other_file_access")
        bundle = temporary / "synthetic_bundle.json"
        emit_bounded_audit(bundle, dict(checks=[dict(name=str(i), passed=True) for i in range(321)],
                                       input_files={}, errors=[]))
        index = json.loads(bundle.read_text())
        assert index["checks_count"] == 321 and len(index["checks_shards"]) == 3
        restored = []
        for part in index["checks_shards"]:
            path = temporary / part["file"]
            assert digest(path) == part["sha256"] and path.stat().st_size == part["bytes"]
            restored.extend(json.loads(path.read_text()))
        assert restored == [dict(name=str(i), passed=True) for i in range(321)]
        checks.append("bounded_audit_shards_are_losslessly_reconstructible")
        jobs_path = temporary / "synthetic_jobs.json"
        emit(jobs_path, dict(total_count=2, jobs=[dict(id=index + 1, name=name,
            run_id=EXPECTED_RUN, head_sha=EXPECTED_SEAL, status="completed", conclusion="success",
            started_at=start, completed_at=end) for index, (name, start, end) in enumerate((
                ("experiments", "2026-10-31T02:00:00Z", "2026-10-31T02:01:00Z"),
                ("publish", "2026-10-31T02:01:30Z", "2026-10-31T02:02:00Z")))]))
        wall_audit = Audit()
        wall = complete_runner_wall(wall_audit, jobs_path, dict(created_at="2026-10-31T01:59:00Z"))
        assert not wall_audit.errors and wall["total_occupied_runner_seconds"] == 90.
        assert wall["execution_span_seconds"] == 120. and wall["creation_to_final_job_completion_seconds"] == 180.
        checks.append("complete_job_wall_keeps_queue_gaps_and_cpu_distinct")
    emit(output, dict(schema="hcsn-av-independent-outcome-selfcheck.v1", passed=True, checks=checks,
        source_sha256=digest(__file__), test_outputs_read=False, real_data_arrays_loaded=False,
        process_cpu_seconds=time.process_time(), peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "selfcheck"))
    parser.add_argument("--study", type=Path)
    parser.add_argument("--driver", type=Path)
    parser.add_argument("--run-receipt", type=Path, help="Retained raw GitHub REST run JSON, with completed status")
    parser.add_argument("--jobs-receipt", type=Path, help="Retained complete GitHub REST jobs JSON for the same completed run")
    parser.add_argument("--source-root", type=Path, default=BASE.parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Do not overwrite an independent audit attempt")
    if args.command == "selfcheck":
        selfcheck(args.output)
        return
    audit, started = Audit(), time.process_time()
    result = {}
    try:
        if args.study is None or args.run_receipt is None or args.jobs_receipt is None:
            raise ValueError("Completed-run and job receipts and the restored study directory are required")
        driver = args.driver or args.study.parent / "hosted_driver001"
        result = inspect(args.study, driver, args.run_receipt, args.jobs_receipt, args.source_root, audit)
    except Exception as error:
        audit.errors.append(repr(error))
        result["exception"] = traceback.format_exc()
    passed = not audit.errors
    result.update(schema="hcsn-av-independent-outcome-audit.v1", passed=passed,
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), checks=audit.checks,
        errors=audit.errors, input_files=audit.inputs, audit_source_sha256=digest(__file__),
        process_cpu_seconds=time.process_time(), audit_body_cpu_seconds=time.process_time() - started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    emit_bounded_audit(args.output, result)
    print(json.dumps(dict(passed=passed, checks=len(audit.checks), errors=audit.errors)))
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
