"""Read-only study-integrity audit; called only after the registered queue ends.

This module never selects checkpoints, changes jobs, or repairs failed evidence.
Prediction archives are opened only by the explicitly authorized final analysis.
"""

import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np


PACKAGE = Path(__file__).resolve().parent


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024*1024):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    with Path(path).open() as stream:
        return json.load(stream)


def registered_jobs(study, protocol):
    entries = protocol.get("jobs")
    if isinstance(entries, dict):
        entries = [dict(value, id=key) for key, value in entries.items()]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Protocol must contain a nonempty jobs list or mapping")
    jobs, seen = [], set()
    for entry in entries:
        identity = entry if isinstance(entry, str) else entry.get("id", entry.get("job_id"))
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", identity):
            raise ValueError("Invalid registered job identity")
        if identity in seen:
            raise ValueError("Duplicate registered job identity: "+identity)
        seen.add(identity)
        path = Path(study)/"jobs"/(identity+".json")
        declared = entry.get("job", entry) if isinstance(entry, dict) else {}
        errors = []
        try:
            spec, actual_hash = read_json(path), digest(path)
        except (OSError, ValueError) as error:
            spec, actual_hash = {}, None
            errors.append(f"Registered job file unreadable: {type(error).__name__}: {error}")
        for key in ("id", "family", "task", "arm", "width", "seed", "updates", "batch_size",
                    "validate_every", "learning_rate", "training_cpu_budget", "source_hashes"):
            if key in declared and spec.get(key) != declared[key]:
                errors.append(f"Protocol/job disagreement: {key}")
        if declared.get("job_file_sha256") != actual_hash:
            errors.append("Registered job_file_sha256 mismatch or absent hash")
        if spec.get("source_hashes") != protocol.get("source_hashes"):
            errors.append("Job source/data hashes differ from global frozen manifest")
        expected = ({**{k: v for k, v in declared.items() if k != "job_file_sha256"},
                     "source_hashes": protocol.get("source_hashes", {})} if "task" in declared else spec)
        jobs.append({"id": identity, "job": expected, "registration_sha256": actual_hash,
                     "registration_errors": errors})
    if len(jobs) != protocol.get("expected_jobs"):
        raise ValueError("Protocol expected_jobs disagrees with its job list")
    return jobs


def pending_jobs(study, registered):
    """Require the coordinator to finish, including explicitly failed launches."""
    study = Path(study)
    path = study/"execution.json"
    if not path.is_file():
        return [row["id"] for row in registered]
    execution = read_json(path)
    rows = execution.get("rows", [])
    ids = [row.get("id") for row in rows]
    if not execution.get("complete") or sorted(ids) != sorted(row["id"] for row in registered):
        return [row["id"] for row in registered if row["id"] not in ids] or ["coordinator_not_complete"]
    return []


def global_integrity(study, protocol):
    """Registration and completion evidence; no predictions or checkpoints read."""
    study = Path(study)
    registration = read_json(study/"registration_receipt.json")
    execution = read_json(study/"execution.json")
    actual = digest(study/"protocol.json")
    errors = []
    if registration.get("protocol_sha256") != actual or execution.get("protocol_sha256") != actual:
        errors.append("Protocol hash differs from registration/completion evidence")
    if registration.get("source_hashes") != protocol.get("source_hashes"):
        errors.append("Registration source/data manifest differs from protocol")
    return dict(errors=errors, protocol_sha256=actual,
                registration_receipt_sha256=digest(study/"registration_receipt.json"),
                execution_sha256=digest(study/"execution.json"), execution=execution)


def prediction_metrics(path, expected, cohort=None, classes=None):
    with np.load(path, allow_pickle=False) as archive:
        logits, labels = np.asarray(archive["logits"]), np.asarray(archive["labels"])
        episodes, stored_correct = np.asarray(archive["episodes"]), np.asarray(archive["correct"])
        positions = np.asarray(archive["token_index"])
        clips = np.asarray(archive["clip_ids"]) if "clip_ids" in archive else None
        actors = np.asarray(archive["actors"]) if "actors" in archive else None
    if (logits.ndim != 2 or labels.shape != (len(logits),) or len(logits) == 0
            or not np.all(np.isfinite(logits)) or not np.issubdtype(labels.dtype, np.integer)
            or np.any(labels < 0) or np.any(labels >= logits.shape[1])):
        raise ValueError("Malformed prediction/label archive")
    if classes is not None and logits.shape[1] != classes:
        raise ValueError("Prediction class dimension differs from registered task")
    if any(array.shape != labels.shape for array in (episodes, positions, stored_correct)):
        raise ValueError("Prediction metadata dimensions differ")
    if (not np.issubdtype(episodes.dtype, np.integer) or not np.issubdtype(positions.dtype, np.integer)
            or np.any(episodes < 0) or np.any(episodes >= expected["episodes"]) or np.any(positions < 0)):
        raise ValueError("Prediction episode identity is outside declared cohort")
    if len(np.unique(episodes)) != expected["episodes"]:
        raise ValueError("At least one declared episode has no saved supervision")
    if np.any((np.diff(episodes) < 0) | ((np.diff(episodes) == 0) & (np.diff(positions) <= 0))):
        raise ValueError("Prediction identities are duplicated or not episode/token ordered")
    correct = logits.argmax(axis=1) == labels
    if not np.array_equal(correct, stored_correct):
        raise ValueError("Stored correctness disagrees with logits")
    z = logits.astype(np.float64)
    maximum = z.max(axis=1)
    ce = maximum+np.log(np.exp(z-maximum[:, None]).sum(axis=1))-z[np.arange(len(labels)), labels]
    if not np.all(np.isfinite(ce)) or not all(math.isfinite(expected[k]) for k in ("accuracy", "cross_entropy")):
        raise ValueError("Nonfinite prediction or summary metric")
    metrics = {"accuracy": float(correct.mean()), "cross_entropy": float(ce.mean()),
               "supervised_tokens": len(labels), "episodes": int(expected["episodes"])}
    if abs(metrics["accuracy"]-expected["accuracy"]) > 1e-12:
        raise ValueError("Summary accuracy disagrees with saved predictions")
    if abs(metrics["cross_entropy"]-expected["cross_entropy"]) > 2e-6+2e-6*abs(metrics["cross_entropy"]):
        raise ValueError("Summary cross entropy disagrees with saved predictions")
    if len(labels) != expected["supervised_tokens"]:
        raise ValueError("Summary supervised-token count disagrees")
    identity = hashlib.sha256()
    for name, array in (("labels", labels), ("episodes", episodes), ("token_index", positions)):
        identity.update(name.encode()); identity.update(array.astype("<i8").tobytes())
    if cohort is not None:
        if clips is None or actors is None or clips.shape != labels.shape or actors.shape != labels.shape:
            raise ValueError("AV prediction archive lacks per-token clip/actor identities")
        if set(clips.tolist()) != set(cohort):
            raise ValueError("AV clip cohort differs from registered manifest")
        for clip, actor, label in zip(clips, actors, labels, strict=True):
            if str(actor) != str(clip).split("_")[0] or cohort[str(clip)]["label"] != int(label):
                raise ValueError("AV actor or target label differs from registered clip manifest")
        if len(clips) != len(cohort) or len(np.unique(clips)) != expected["episodes"]:
            raise ValueError("AV must have exactly one supervised prediction per clip")
        identities = list(zip(clips.tolist(), actors.tolist(), strict=True))
        identity.update(json.dumps(identities, ensure_ascii=True).encode())
        metrics.update(clip_ids=clips.tolist(), actor_ids=sorted(set(actors.tolist())))
    elif clips is not None or actors is not None:
        raise ValueError("Synthetic prediction archive unexpectedly contains AV identities")
    metrics.update(prediction_sha256=digest(path), prediction_bytes=Path(path).stat().st_size,
                   labels_sha256=identity.hexdigest(), cohort_sha256=identity.hexdigest(),
                   maximum_token_index=int(positions.max()))
    return metrics


def audit_job(study, registration, source_cache=None):
    study = Path(study)
    identity, expected = registration["id"], registration["job"]
    run = study/"runs"/identity
    receipt_path = study/"meter"/(identity+".json")
    result = dict(registration, audit_ok=False, errors=list(registration.get("registration_errors", [])),
                  warnings=[], metrics={}, costs={})
    errors, warnings = result["errors"], result["warnings"]
    source_cache = {} if source_cache is None else source_cache
    result["source_hashes"] = expected.get("source_hashes", {})
    checkpoint = run/"selected.pt"
    result["costs"].update(checkpoint_bytes=checkpoint.stat().st_size if checkpoint.is_file() else 0,
                          artifact_bytes=sum(p.stat().st_size for p in run.rglob("*") if p.is_file()))
    try:
        meter = read_json(receipt_path)
        result["receipt_sha256"] = digest(receipt_path)
        result["meter_status"] = {key: meter.get(key) for key in
                                  ("returncode", "timed_out", "spawn_error", "child_reaped")}
        result["costs"].update({key: meter.get(key) for key in
                           ("child_cpu_seconds", "supervisor_cpu_seconds", "wall_seconds",
                            "child_peak_rss_bytes", "bytes_read_observed_lower_bound",
                            "bytes_written_observed_lower_bound", "direct_energy_joules")})
        if meter.get("returncode") != 0 or meter.get("timed_out") or not meter.get("child_reaped"):
            errors.append("Worker did not complete normally; failure receipt is retained")
        if meter.get("meter_source_sha256") != expected.get("source_hashes", {}).get("cost_meter.py"):
            errors.append("Meter source differs from registered cost-meter hash")
        if not meter.get("inner_training_clocks_are_subtotals"):
            errors.append("Receipt does not declare training clocks as subtotals")
        log = Path(meter["log_path"])
        if not log.is_absolute():
            log = Path(meter.get("cwd", study))/log
        if not log.is_file() or digest(log) != meter.get("log_sha256"):
            errors.append("Meter log hash mismatch or absent log")
        if not expected.get("source_hashes"):
            errors.append("No frozen source hashes in registered job")
        for name, wanted in expected.get("source_hashes", {}).items():
            source = PACKAGE/name
            if name not in source_cache:
                source_cache[name] = digest(source) if source.is_file() else None
            if source_cache[name] != wanted:
                errors.append("Current source disagrees with registered hash: "+name)
        if not (run/"summary.json").is_file():
            errors.append("No complete summary.json")
            return result
        summary = read_json(run/"summary.json")
        result["summary_sha256"] = digest(run/"summary.json")
        result["runtime"] = summary.get("runtime", {})
        result["config"] = summary.get("config", {})
        if summary.get("job") != expected or read_json(run/"job.json") != expected:
            errors.append("Executed job/summary differs from registered job")
        if summary.get("runtime", {}).get("preflight"):
            errors.append("A preflight cannot stand in for a registered study run")
        trace = read_json(run/"trace.json")
        actual = summary["actual_updates"]
        if len(trace) != actual or [r["step"] for r in trace] != list(range(1, actual+1)):
            errors.append("Training trace is incomplete or has nonsequential update numbers")
        if not all(math.isfinite(r["loss"]) and math.isfinite(r["gradient_norm"]) for r in trace):
            errors.append("Nonfinite training loss/gradient")
        times = [0., *[r["training_cpu_seconds"] for r in trace]]
        if not all(math.isfinite(x) and b >= x for x, b in zip(times, times[1:])):
            errors.append("Cumulative training CPU is nonfinite or nonmonotone")
        if trace[-1]["training_cpu_seconds"] != summary["training_cpu_seconds"]:
            errors.append("Final trace and summary training CPU disagree")
        budget = expected.get("training_cpu_budget")
        if budget is None and actual != expected["updates"]:
            errors.append("Fixed-update run stopped early")
        if budget is not None:
            reached = summary["training_cpu_seconds"] >= budget
            if reached and actual > 1 and trace[-2]["training_cpu_seconds"] >= budget:
                errors.append("Training continued after the declared CPU stopping rule")
            if not reached:
                warnings.append("Requested CPU budget not reached before update cap")
            result["cpu_budget_overshoot_seconds"] = max(0., summary["training_cpu_seconds"]-budget)
        if not 1 <= actual <= expected["updates"]:
            errors.append("Invalid actual update count")
        deltas = summary["group_delta"]
        result["group_delta"] = deltas
        result["selected_group_delta"] = summary["selected_group_delta"]
        result["mean_gradient"] = summary["mean_gradient"]
        result["parameter_delta_scope"] = {"group_delta": "Last optimizer state",
                                           "selected_group_delta": "Validation-selected checkpoint used for test"}
        for scope in ("group_delta", "selected_group_delta"):
            if sum(value["trainable"] for value in summary[scope].values()) != summary["trainable_parameters"]:
                errors.append("Parameter-group trainable counts disagree with total: "+scope)
            if not all(math.isfinite(value["l2"]) and 0 <= value["changed"] <= value["tensors"]
                       for value in summary[scope].values()):
                errors.append("Invalid or nonfinite parameter-group change evidence: "+scope)
        if expected["arm"].startswith("freeze_"):
            group = expected["arm"].removeprefix("freeze_")
            for scope in ("group_delta", "selected_group_delta"):
                item = summary[scope].get(group)
                if item is None or item["changed"] != 0 or item["l2"] != 0 or item["trainable"] != 0:
                    errors.append("Frozen group changed or retained trainable parameters in "+scope)
            if summary["mean_gradient"].get(group) != 0:
                errors.append("Frozen group acquired gradients")
        for group, delta in deltas.items():
            if delta["trainable"] and (delta["changed"] == 0 or summary["mean_gradient"].get(group, 0) == 0):
                warnings.append("Trainable group shows zero change or zero mean gradient: "+group)
        selected = read_json(run/"selection.json")
        if selected != summary["validation_selection"]:
            errors.append("Durable validation selection disagrees with summary")
        actual_hash = digest(checkpoint)
        if actual_hash != selected["checkpoint_sha256"]:
            errors.append("Selected checkpoint hash mismatch")
        validation_rows = [row for row in trace if "validation" in row]
        best = min(validation_rows, key=lambda row: row["validation"]["cross_entropy"])
        if selected["step"] != best["step"] or selected["validation"] != best["validation"]:
            errors.append("Selection is not the first minimum validation-CE checkpoint")
        cohorts = {}
        if expected["task"] == "async_av":
            manifest = read_json(PACKAGE/"data"/"async_manifest.json")
            for split in ("train", "validation", "test"):
                cohorts[split] = {r["clip"]: r for r in manifest["records"] if r["split"] == split}
            actor_sets = [set(str(r["actor"]) for r in cohorts[s].values()) for s in cohorts]
            if any(a & b for i, a in enumerate(actor_sets) for b in actor_sets[i+1:]):
                errors.append("Registered AV actor splits are not disjoint")
        classes = 6 if expected["task"] == "async_av" else 8
        result["validation"] = prediction_metrics(run/"validation_prediction.npz", selected["validation"],
                                                  cohorts.get("validation"), classes)
        if not cohorts and result["validation"]["episodes"] != 128:
            errors.append("Synthetic validation episode count differs from registered worker")
        access = read_json(run/"access.json")
        tests = [row for row in access if row["split"] == "test"]
        if not tests or min(row["unix_seconds"] for row in tests) < (run/"selection.json").stat().st_mtime-1:
            errors.append("Test access predates durable validation selection or is unrecorded")
        result["access_sha256"] = digest(run/"access.json")
        result["test_selection_audit"] = "Timestamp/order check; not a cryptographic proof of every external access"
        result["dataset_sha256"] = {}
        for split in ("train", "val"):
            hashes = {row["sha256"] for row in access if row["split"] == split}
            if len(hashes) != 1:
                errors.append("Training/validation dataset identity absent or inconsistent: "+split)
            result["dataset_sha256"][split] = next(iter(hashes)) if len(hashes) == 1 else None
        expected_cases = ({"length32", "missing_modality0", "missing_modality1"}
                          if expected["task"] == "async_av" else {"length32", "length64", "length128"})
        if set(summary["evaluation"]) != expected_cases:
            errors.append("Evaluation cases differ from the registered worker contract")
        for case, metrics in summary["evaluation"].items():
            verified = prediction_metrics(run/f"prediction_{case}.npz", metrics, cohorts.get("test"), classes)
            missing = int(case[-1]) if case.startswith("missing_modality") else None
            length = int(case.removeprefix("length")) if missing is None else 32
            if expected["task"] != "async_av" and verified["maximum_token_index"] >= length:
                errors.append("Saved prediction index exceeds sequence length: "+case)
            if not cohorts and verified["episodes"] != 128:
                errors.append("Synthetic test episode count differs from registered worker: "+case)
            records = [row for row in tests if row["length"] == length and row.get("missing_modality") == missing]
            identities = {row["sha256"] for row in records}
            if len(identities) != 1:
                errors.append("Missing/inconsistent data access identity: "+case)
            verified["data_sha256"] = next(iter(identities)) if len(identities) == 1 else None
            result["metrics"][case] = verified
        result["allocated_parameters"] = summary["allocated_parameters"]
        result["trainable_parameters"] = summary["trainable_parameters"]
        if not 0 < summary["trainable_parameters"] <= summary["allocated_parameters"]:
            errors.append("Invalid allocated/trainable parameter counts")
        result["actual_updates"] = actual
        result["selected_step"] = selected["step"]
        result["inference"] = summary.get("inference", {})
        for sample in result["inference"].get("samples", []):
            logical, storage = sample.get("persistent_numeric_state_bytes"), sample.get("persistent_storage_bytes")
            if (logical is None) != (storage is None) or (logical is not None and (logical <= 0 or storage <= 0)):
                errors.append("Inference state memory fields are missing or nonpositive inconsistently")
            # Aliased tensors can make logical bytes exceed unique storage; neither is an RSS claim.
        result["costs"].update(training_cpu_seconds=summary["training_cpu_seconds"],
                              training_wall_seconds=summary["training_wall_seconds"],
                              worker_body_cpu_seconds=summary["worker_body_cpu_seconds"],
                              worker_body_wall_seconds=summary["worker_body_wall_seconds"],
                              checkpoint_bytes=checkpoint.stat().st_size,
                              artifact_bytes=sum(p.stat().st_size for p in run.rglob("*") if p.is_file()))
        if summary["training_cpu_seconds"] > meter["child_cpu_seconds"]+.1:
            errors.append("Inner training CPU exceeds whole-worker CPU receipt")
        for key in ("training_cpu_seconds", "child_cpu_seconds", "child_peak_rss_bytes", "checkpoint_bytes"):
            if not math.isfinite(result["costs"][key]) or result["costs"][key] <= 0:
                errors.append("Invalid positive resource measure: "+key)
    except Exception as exc:
        errors.append(f"Audit exception: {type(exc).__name__}: {exc}")
    result["audit_ok"] = not errors
    return result
