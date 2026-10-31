"""Raw-evidence validation and crossed actor/paired-seed audiovisual analysis."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from . import study
from .metrics import evaluation_arrays


def tensor_hash(path):
    value = hashlib.sha256()
    with np.load(path, allow_pickle=False) as archive:
        for key in sorted(archive.files):
            array = archive[key]
            value.update(json.dumps([key, str(array.dtype), list(array.shape)]).encode())
            value.update(array.tobytes())
    return value.hexdigest()


def close_tree(actual, expected, path=""):
    errors = []
    if isinstance(expected, dict):
        for key, value in expected.items():
            if key not in actual:
                errors.append(path+"/"+key+": missing")
            else:
                errors.extend(close_tree(actual[key], value, path+"/"+key))
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        if not np.isclose(actual, expected, rtol=2e-10, atol=2e-10):
            errors.append(path+": numerical mismatch")
    elif actual != expected:
        errors.append(path+": mismatch")
    return errors


def checked_evaluation(job_dir, row, split, dataset):
    path = job_dir/row["file"]
    if study.digest(path) != row["sha256"]:
        raise ValueError("Raw evaluation identity mismatch")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: np.array(archive[key], copy=True) for key in archive.files}
    for key, source in (("labels", "y"), ("actor", "actor"), ("clip", "clip")):
        if not np.array_equal(arrays[key], dataset[source]):
            raise ValueError("Raw evaluation labels or actor/clip identities differ from the registered split")
    logits = [arrays[key] for key in ("audio_logits", "video_logits", "fused_logits")]
    if not all(np.isfinite(value).all() for value in logits):
        raise ValueError("Nonfinite evaluation logits")
    if not np.array_equal(arrays["fused_logits"], .5*(arrays["audio_logits"]+arrays["video_logits"])):
        raise ValueError("Fused logits are not the registered arithmetic late fusion")
    outputs = {key: arrays[key] for key in ("audio_embedding", "video_embedding", "audio_logits", "video_logits", "fused_logits")}
    recomputed, metrics = evaluation_arrays(outputs, arrays["labels"], arrays["actor"], arrays["clip"], split)
    for key, value in recomputed.items():
        if not np.array_equal(arrays[key], value):
            raise ValueError("Raw retrieval or derangement evidence mismatch: "+key)
    errors = close_tree(row, metrics)
    if errors:
        raise ValueError("Evaluation summary mismatch: "+"; ".join(errors[:4]))
    return arrays


def crossed_interval(matrix, seed, repetitions=20000, family_size=8):
    rng = np.random.default_rng(seed)
    count_seed, count_actor = matrix.shape
    values = np.empty(repetitions)
    for start in range(0, repetitions, 1000):
        n = min(1000, repetitions-start)
        seeds = rng.integers(count_seed, size=(n, count_seed))
        actors = rng.integers(count_actor, size=(n, count_actor))
        values[start:start+n] = matrix[seeds[:, :, None], actors[:, None, :]].mean((1, 2))
    return dict(mean=float(matrix.mean()), seed_count=count_seed, actor_count=count_actor,
        percentile95=np.quantile(values, [.025, .975]).tolist(),
        one_sided_bonferroni_lower=float(np.quantile(values, .05/family_size)),
        bootstrap_replicates=repetitions,
        scope="Approximate crossed actor and paired-initialization bootstrap; not clip-independent inference")


def job_matrix(design, choices, stage):
    if stage == "development":
        return [dict(stage=stage, arm=arm, seed=design["development_seed"], learning_rate=lr,
                     updates=design["development_updates"], id=f"{arm}__lr{lr:g}")
                for arm in design["models"] for lr in design["learning_rates"]]
    if choices is None:
        raise ValueError("No formal matrix without locked learning rates")
    return [dict(stage=stage, arm=arm, seed=seed,
                 learning_rate=choices["choices"][arm]["learning_rate"],
                 updates=design["formal_updates"], id=f"{arm}__seed{seed}")
            for arm in design["models"] for seed in design["formal_seeds"]]


def validate_trajectory(path, result, design):
    rows = study.read(path)
    count = result["updates"]
    if len(rows) != count or [row["step"] for row in rows] != list(range(1, count+1)):
        raise ValueError("Training trajectory does not contain every exact update")
    previous = 0.
    for row in rows:
        clock = row["training_cpu_seconds"]
        if not np.isfinite(clock) or clock <= previous or not np.isfinite(row["loss"]):
            raise ValueError("Nonfinite loss or invalid training clock")
        expected_loss = (row["components"]["fused_ce"]+.25*(row["components"]["audio_ce"]+
            row["components"]["video_ce"])+.5*row["components"]["symmetric_infonce"])
        if not np.isclose(row["loss"], expected_loss, rtol=2e-6, atol=2e-6):
            raise ValueError("The recorded multi-task loss components do not add up")
        for gradient in row["gradient_groups"].values():
            if any(not np.isfinite(value) or value < 0 for value in gradient.values()):
                raise ValueError("Nonfinite gradient diagnostics")
        for physical in row["physical"].values():
            if physical and (not all(np.isfinite(value) for value in physical.values())
                    or physical["minimum"] < 0 or physical["maximum_mass_defect"] > 1e-5):
                raise ValueError("A training probability contract failed")
        previous = clock
    if previous != result["training_cpu_seconds"]:
        raise ValueError("Final training clock differs from the complete trajectory")
    if result["job"]["stage"] == "equal_cpu":
        budget = design["equal_cpu_seconds"]
        previous_clock = rows[-2]["training_cpu_seconds"] if len(rows)>1 else 0.
        if not previous_clock < budget <= previous or result["training_cpu_budget_overrun_seconds"] != previous-budget:
            raise ValueError("Equal-CPU worker did not stop at the first complete crossing update")
        midpoint = next(row["step"] for row in rows if row["training_cpu_seconds"] >= budget/2)
        expected_steps = sorted({midpoint, count})
    else:
        expected_steps = [result["job"]["updates"]//2, result["job"]["updates"]]
    if [row["step"] for row in result["validations"]] != expected_steps:
        raise ValueError("Validation checkpoints differ from the registered midpoint/end rule")
    for validation in result["validations"]:
        if validation["training_cpu_seconds"] != rows[validation["step"]-1]["training_cpu_seconds"]:
            raise ValueError("Checkpoint training clock changed")


def analyze(output):
    output = Path(output).resolve()
    cpu, wall = time.process_time(), time.perf_counter()
    protocol = study.verify(output)
    design, errors, records, attempted = protocol["design"], [], [], []
    choices = study.read(output/"SELECTION_LOCK.json") if (output/"SELECTION_LOCK.json").exists() else None
    datasets = {}
    for split in ("validation", "test"):
        row = protocol["dataset"]["splits"][split]
        with np.load(output/"data"/row["path"], allow_pickle=False) as archive:
            datasets[split] = {key: np.array(archive[key], copy=True) for key in ("y", "actor", "clip")}
    for stage in ("development", "fixed", "equal_cpu"):
        jobs_path, ledger_path = output/("jobs_"+stage+".json"), output/("RUN_"+stage+".json")
        if not jobs_path.exists() or not ledger_path.exists():
            errors.append(stage+": job list or run ledger missing")
            continue
        jobs, ledger = study.read(jobs_path), study.read(ledger_path)
        try:
            expected = job_matrix(design, choices, stage)
            if (len({row["id"] for row in jobs}) != len(jobs)
                    or sorted(jobs, key=lambda row: row["id"]) != sorted(expected, key=lambda row: row["id"])):
                errors.append(stage+": registered jobs differ from the exact unique design matrix")
        except (KeyError, ValueError) as error:
            errors.append(stage+": invalid job matrix: "+repr(error))
        if len(jobs) != design["expected_jobs"][stage] or not ledger["complete"] or ledger["failed"]:
            errors.append(stage+": incomplete or failed job ledger")
        attempts = {row["id"]: row for row in ledger["jobs"]}
        attempted.extend(dict(stage=stage, **row) for row in ledger["jobs"])
        if (len(attempts) != len(ledger["jobs"]) or set(attempts) != {row["id"] for row in jobs}
                or any(attempts[row["id"]]["job"] != row for row in jobs if row["id"] in attempts)):
            errors.append(stage+": attempted job set differs from registration")
        for job in jobs:
            job_dir = output/stage/job["id"]
            try:
                if attempts[job["id"]]["exit_code"] != 0:
                    raise ValueError("Worker exited nonzero")
                result = study.read(job_dir/"RESULT.json")
                if result["status"] != "complete" or result["job"] != job or result["protocol_sha256"] != study.digest(output/"PROTOCOL.json"):
                    raise ValueError("Result identity differs from the registered job")
                if result["dt_override"] is not None:
                    raise ValueError("Real elapsed duration was overridden")
                if stage != "equal_cpu" and result["updates"] != job["updates"]:
                    raise ValueError("Registered update count was not reached")
                if stage == "equal_cpu" and result["training_cpu_seconds"] < design["equal_cpu_seconds"]:
                    raise ValueError("Registered complete-update training CPU budget was not reached")
                validate_trajectory(job_dir/"trajectory.json", result, design)
                selected = study.read(job_dir/"selection.json")
                if any(selected[key] != value for key, value in result["selected"].items()):
                    raise ValueError("Durable selection identity changed")
                if study.digest(job_dir/"selected_state.npz") != selected["state_sha256"] or tensor_hash(job_dir/"selected_state.npz") != selected["tensor_hash"]:
                    raise ValueError("Selected checkpoint bytes or tensors changed")
                if study.digest(job_dir/"final_state.npz") != result["final_state_sha256"] or tensor_hash(job_dir/"final_state.npz") != result["final_tensor_hash"]:
                    raise ValueError("Final checkpoint identity changed")
                accesses = [json.loads(line) for line in (job_dir/"access.jsonl").read_text().splitlines()]
                expected_access = ["train", "validation"] + ([] if stage == "development" else ["test"])
                if [row["split"] for row in accesses] != expected_access:
                    raise ValueError("Unexpected data access order")
                if stage != "development" and (not accesses[-1]["durable_selection_exists"] or accesses[-1]["utc"] < selected["locked_utc"]):
                    raise ValueError("Test arrays opened before durable checkpoint choice")
                if stage != "development" and (choices is None or result["started_utc"] < choices["locked_utc"]
                        or accesses[-1]["utc"] < choices["locked_utc"]):
                    raise ValueError("Formal training or test access preceded the global learning-rate lock")
                for validation in result["validations"]:
                    checked_evaluation(job_dir, validation, "validation", datasets["validation"])
                chosen = min(result["validations"], key=lambda row: (row["classification"]["fused"]["cross_entropy"], row["step"]))
                if (chosen["step"] != selected["step"] or chosen["sha256"] != selected["validation_sha256"]
                        or chosen["classification"]["fused"]["cross_entropy"] != selected["cross_entropy"]):
                    raise ValueError("Checkpoint choice did not follow validation CE")
                arrays = None
                if stage == "development":
                    if result["test"] is not None:
                        raise ValueError("Development worker evaluated heldout clips")
                else:
                    arrays = checked_evaluation(job_dir, result["test"], "test", datasets["test"])
                if job["arm"] == "value_jg":
                    for modality in ("audio", "video"):
                        if any(result["selected_modality_update_groups"][modality][group]["nonzero"] == 0
                               for group in ("content", "dynamics", "boundary", "reset", "refractory")):
                            raise ValueError("A modality's physical/content component did not learn")
                records.append(dict(job=job, report=result, arrays=arrays, execution=attempts[job["id"]]))
            except Exception as error:
                errors.append(stage+"/"+job["id"]+": "+repr(error))
    if choices is None:
        errors.append("No learning-rate selection lock")
    else:
        if choices["protocol_sha256"] != study.digest(output/"PROTOCOL.json") or set(choices["choices"]) != set(design["models"]):
            errors.append("Learning-rate lock does not bind this protocol and exact model set")
        for arm in design["models"]:
            dev = [row for row in records if row["job"]["stage"] == "development" and row["job"]["arm"] == arm]
            if len(dev) == 2:
                best = min(dev, key=lambda row: (row["report"]["selected"]["cross_entropy"],
                    row["report"]["selected"]["step"], row["job"]["learning_rate"]))
                selected = choices["choices"][arm]
                expected_path = "development/"+best["job"]["id"]+"/RESULT.json"
                if (selected["learning_rate"] != best["job"]["learning_rate"]
                        or selected["result_file"] != expected_path
                        or selected["development_cross_entropy"] != best["report"]["selected"]["cross_entropy"]
                        or study.digest(output/expected_path) != selected["result_sha256"]
                        or any(row["report"]["completed_utc"] > choices["locked_utc"] for row in dev)):
                    errors.append(arm+": learning-rate selection mismatch")
                for row in records:
                    if row["job"]["arm"] == arm and row["job"]["stage"] != "development" and row["job"]["learning_rate"] != selected["learning_rate"]:
                        errors.append(arm+": formal worker used an unselected learning rate")
    counts = {row["job"]["arm"]: row["report"]["counts"] for row in records}
    if len(counts) == len(design["models"]):
        backbones = [row["backbone"] for row in counts.values()]
        if (max(backbones)-min(backbones))/max(backbones) > .03:
            errors.append("Active backbone parameter mismatch exceeds3%")
    for stage in ("fixed", "equal_cpu"):
        for seed in design["formal_seeds"]:
            group = [row for row in records if row["job"]["stage"] == stage and row["job"]["seed"] == seed]
            if len(group) == 5:
                if len({row["report"]["common_initial_hash"] for row in group}) != 1:
                    errors.append(stage+": common initialization mismatch")
                if stage == "fixed" and len({row["report"]["batch_stream_sha256"] for row in group}) != 1:
                    errors.append(stage+": paired batch stream mismatch")
    actors = sorted(np.unique(datasets["test"]["actor"]).tolist())
    summaries, matrices, primary = {}, {}, []
    for stage in ("fixed", "equal_cpu"):
        summaries[stage], matrices[stage] = {}, {}
        for arm in design["models"]:
            group = sorted([row for row in records if row["job"]["stage"] == stage and row["job"]["arm"] == arm],
                           key=lambda row: row["job"]["seed"])
            if (len(group) != len(design["formal_seeds"])
                    or [row["job"]["seed"] for row in group] != sorted(design["formal_seeds"])):
                continue
            matrix = np.array([[np.mean((row["arrays"]["fused_logits"].argmax(1) == row["arrays"]["labels"])[row["arrays"]["actor"] == actor])
                                for actor in actors] for row in group])
            matrices[stage][arm] = matrix
            classification = {channel: {metric: float(np.mean([row["report"]["test"]["classification"][channel][metric] for row in group]))
                for metric in ("accuracy", "cross_entropy", "brier", "ece")}
                for channel in group[0]["report"]["test"]["classification"]}
            retrieval = {channel: {metric: float(np.mean([row["report"]["test"]["retrieval"][channel][metric] for row in group]))
                for metric in ("recall_at1", "recall_at5", "mean_reciprocal_rank", "median_rank")}
                for channel in group[0]["report"]["test"]["retrieval"]}
            summaries[stage][arm] = dict(classification=classification, retrieval=retrieval,
                actor_accuracy_matrix=matrix.tolist(), actor_order=actors,
                seed_order=[row["job"]["seed"] for row in group],
                mean_updates=float(np.mean([row["report"]["updates"] for row in group])),
                mean_training_cpu_seconds=float(np.mean([row["report"]["training_cpu_seconds"] for row in group])),
                mean_whole_worker_cpu_seconds=float(np.mean([row["execution"]["child_cpu_seconds"] for row in group])),
                mean_whole_worker_wall_seconds=float(np.mean([row["execution"]["wall_seconds"] for row in group])),
                mean_inference_median_cpu_seconds=float(np.mean([row["report"]["inference"]["median_cpu_seconds"] for row in group])))
        if "value_jg" not in matrices[stage]:
            continue
        for control in design["models"][1:]:
            if control not in matrices[stage]:
                continue
            interval = crossed_interval(matrices[stage]["value_jg"]-matrices[stage][control],
                design["primary_statistics"]["bootstrap_seed"]+len(primary),
                design["primary_statistics"]["bootstrap_replicates"], design["primary_statistics"]["contrasts"])
            a, b = summaries[stage]["value_jg"]["classification"]["fused"], summaries[stage][control]["classification"]["fused"]
            calibration = a["brier"]-b["brier"] <= .01 and a["ece"]-b["ece"] <= .02
            primary.append(dict(stage=stage, control=control, **interval,
                brier_difference=a["brier"]-b["brier"], ece_difference=a["ece"]-b["ece"],
                point_calibration_guard_pass=calibration,
                passes_conditional_on_integrity=interval["mean"] >= .02 and interval["one_sided_bonferroni_lower"] > 0 and calibration))
    complete = len(records) == sum(design["expected_jobs"].values()) and not errors
    for row in primary:
        row["passes"] = complete and row["passes_conditional_on_integrity"]
    shared = {}
    for name in ("REGISTER_COST.json", "ACQUIRE_COST.json", "PREPARE_COST.json", "PREPARATION_COST.json"):
        path = output/"data"/name
        if path.exists():
            shared[name] = study.read(path)
    result = dict(schema="hcsn-blocker-av-analysis.v1", complete=complete, errors=errors,
        expected_jobs=sum(design["expected_jobs"].values()), valid_jobs=len(records),
        attempted_jobs=len(attempted), failures=sum(row["exit_code"] != 0 for row in attempted),
        protocol_sha256=study.digest(output/"PROTOCOL.json"), data_evidence_commit=protocol["data_evidence_commit"],
        counts=counts, summaries=summaries, primary_contrasts=primary,
        external_net_benefit_pass=complete and len(primary) == 8 and all(row["passes"] for row in primary),
        actors=actors, actor_count=len(actors), test_clips=len(datasets["test"]["y"]),
        seed_count=len(design["formal_seeds"]), source_bound_real_time=True,
        measured_worker_cpu_seconds=sum(row["child_cpu_seconds"] for row in attempted),
        measured_training_cpu_seconds=sum(row["report"]["training_cpu_seconds"] for row in records),
        max_worker_rss_bytes=max([row["maxrss_bytes"] for row in attempted], default=None),
        stages={stage: study.read(output/("RUN_"+stage+".json")) if (output/("RUN_"+stage+".json")).exists() else None
                for stage in ("development", "fixed", "equal_cpu")},
        acquisition_decoder_costs=shared,
        nonoverlap_warning="Training/evaluation clocks are inside worker wait4; coordinator/prepare/run/finalize may contain workers. PREPARATION_COST is nested inside PREPARE_COST. Do not sum nested receipts.",
        analysis_cpu_seconds=time.process_time()-cpu, analysis_wall_seconds=time.perf_counter()-wall,
        direct_energy_joules=None, gpu_executed=False,
        interpretation="Fresh-actor small offline audiovisual encoder study; no foundation-model or causal-streaming claim. Independent encoders plus a shared linear mean head are an additive fusion probe; degradation under shuffled pairs shows mispairing sensitivity, not by itself cross-modal synergy.")
    study.write(output/"ANALYSIS.json", result)
    lines = ["# Fresh-actor audiovisual closure study", "",
             f"Valid jobs: {len(records)}/{result['expected_jobs']}; complete: {complete}.",
             f"Passed external contrasts: {sum(row['passes'] for row in primary)}/8.", "",
             "The population unit is one of eight heldout actors. The analysis resamples paired seeds and actors in a crossed design; clips are not independent actor replicates.", "",
             "| Budget | Model | Fused accuracy | Audio | Video | Brier | ECE | Whole-worker CPU s |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for stage, arms in summaries.items():
        for arm, values in arms.items():
            c = values["classification"]
            lines.append(f"| {stage} | {arm} | {c['fused']['accuracy']:.4f} | {c['audio']['accuracy']:.4f} | {c['video']['accuracy']:.4f} | {c['fused']['brier']:.4f} | {c['fused']['ece']:.4f} | {values['mean_whole_worker_cpu_seconds']:.4f} |")
    lines += ["", "Raw embeddings, logits, within-actor and whole-pool retrieval ranks, mispairing interventions, checkpoints, failed attempts and cost receipts remain in this attempt. Training CPU is a nested cost; media decoding and registration are separate.", "",
              "Eight actors and two learning-rate candidates limit the claims. A failed superiority criterion remains a negative result."]
    if errors:
        lines += ["", "## Integrity errors", ""]+["- "+error for error in errors]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")
    return dict(complete=complete, valid_jobs=len(records), expected_jobs=result["expected_jobs"],
                external_contrasts_passed=sum(row["passes"] for row in primary), errors=errors)
