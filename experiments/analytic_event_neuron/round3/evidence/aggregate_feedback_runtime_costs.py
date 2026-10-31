"""Report-only aggregation of completed frozen execution receipts; no new inference."""

from collections import Counter
import gzip
import json
from pathlib import Path
import sys
import tarfile

import numpy as np

from experiments.analytic_event_neuron.round3 import freeze
from experiments.analytic_event_neuron.round3.feedback import digest
from experiments.analytic_event_neuron.round3.feedback_study import write_json
from experiments.analytic_event_neuron.round3.runtime_feedback import file_sha


def read(path):
    return json.loads(Path(path).read_text())


def sum_fields(rows, fields):
    return {field: sum(row[field] for row in rows) for field in fields}


def aggregate(root):
    root = Path(root)
    frozen = freeze.verify(root)
    protocol = read(freeze.PROJECT / "PROTOCOL.json")
    phases = {name: read(root / (name.upper() + "_INDEX.json")) for name in ("feedback", "runtime")}
    for name, phase in phases.items():
        if (not phase["complete"] or phase["source_commit"] != frozen["source_commit"]
                or [r["seed"] for r in phase["scopes"]] != protocol[name]["seeds"]):
            raise ValueError("Incomplete or changed frozen phase")
        for scope in phase["scopes"]:
            for path, expected in scope["files_sha256"].items():
                if file_sha(root / path) != expected:
                    raise ValueError("Completed evidence changed: " + path)
    training, summaries, audits, scopes = [], [], [], []
    for seed in protocol["feedback"]["seeds"]:
        prepared = root / "feedback_prepared" / f"seed_{seed}"
        scope = root / "feedback_confirmation" / f"seed_{seed}"
        t, s, a = read(prepared / "TRAINING_RECEIPT.json"), read(scope / "SUMMARY.json"), read(scope / "AUDIT.json")
        training.append(t)
        summaries.append(s)
        audits.append(a)
        scopes.append({"seed": seed, "training_receipt": str((prepared / "TRAINING_RECEIPT.json").relative_to(root)),
            "summary": str((scope / "SUMMARY.json").relative_to(root)), "audit": str((scope / "AUDIT.json").relative_to(root)),
            "training_wall_ns": t["wall_ns"], "training_parent_cpu_ns": t["cpu_ns"],
            "training_native": t["native"], "policy_worker_wall_ns": s["wall_ns"],
            "policy_worker_cpu_ns": s["cpu_ns"], "policy_native_requests": s["native_requests"],
            "policy_native_ticks": s["native_ticks"], "policy_native_roundtrip_ns": s["native_roundtrip_ns"],
            "audit_wall_ns": a["wall_ns"], "audit_native": a["replay_cost"],
            "typed_ticks_replayed": a["typed_ticks_replayed"], "sparse_ticks_replayed": a["sparse_ticks_replayed"]})
    training_native = sum_fields([t["native"] for t in training], ("requests", "ticks", "roundtrip_ns"))
    workers = sum_fields(summaries, ("wall_ns", "cpu_ns", "native_requests", "native_ticks", "native_roundtrip_ns"))
    replay = sum_fields([a["replay_cost"] for a in audits], ("native_requests", "native_ticks", "native_roundtrip_ns"))
    training_transport = [t[group]["readbacks"] for t in training for group in ("train_archive", "development_archive")]
    confirmation_transport = [s["readbacks"] for s in summaries]
    feedback = {"schema": "hepta.round3.feedback-execution-costs.v1", "complete": True,
        "source_commit": frozen["source_commit"], "seed_count": len(scopes), "scopes": scopes,
        "successful_training": {"wall_ns_sum": sum(t["wall_ns"] for t in training),
            "parent_cpu_ns_sum": sum(t["cpu_ns"] for t in training), "native": training_native,
            "includes_train_development_actual_readbacks_and_archiving": True},
        "confirmation_phase": {"wall_ns": phases["feedback"]["wall_ns"],
            "controller_parent_cpu_ns": phases["feedback"]["parent_cpu_ns"],
            "scope": "Controller data creation/scoring, policy subprocesses, full native audit, per-seed freeze verification and persistence"},
        "policy_workers_nested_in_confirmation_phase": workers,
        "native_audit_nested_in_confirmation_phase": {"wall_ns_sum": sum(a["wall_ns"] for a in audits),
            **replay, "typed_ticks": sum(a["typed_ticks_replayed"] for a in audits),
            "sparse_ticks": sum(a["sparse_ticks_replayed"] for a in audits), "isolated_parent_cpu_ns": None},
        "statistics_after_confirmation_phase": read(root / "FEEDBACK_STATISTICS_EXECUTION.json"),
        "training_transport": sum_fields(training_transport, ("deliveries", "observations", "files", "archive_ns", "archive_bytes")),
        "confirmation_transport": sum_fields(confirmation_transport, ("deliveries", "observations", "files", "archive_ns", "archive_bytes")),
        "confirmation_owner_compressed_bytes": sum(s["owners"]["bytes"] for s in summaries),
        "audit_native_compressed_bytes": sum(a["native_replay_archive"]["bytes"] for a in audits),
        "covered_successful_native_requests": training_native["requests"] + workers["native_requests"] + replay["native_requests"],
        "covered_successful_native_ticks": training_native["ticks"] + workers["native_ticks"] + replay["native_ticks"],
        "all_formal_episodes": sum(a["episodes"] for a in audits),
        "unique_confirmation_trajectories": sum(a["unique_trajectories"] for a in audits),
        "failed_development_training_attempt": {"receipt": "FEEDBACK_TRAINING_OPERATIONAL_EVENT.json",
            "phase": "seed701 first training attempt before freeze", "wall_ns": None,
            "parent_cpu_ns": None, "all_native_requests_or_ticks": None,
            "reason": "ENOSPC interrupted before complete counters; all partial bytes retained and hashed"},
        "unmeasured": {"native_subprocess_cpu_ns": None, "energy_joules": None,
            "hardware_write_amplification_bytes": None, "monetary_cost": None, "total_end_to_end_wall_ns": None},
        "accounting_rules": [
            "Phase wall already contains worker and audit wall; do not add nested values into an elapsed total.",
            "Controller process CPU excludes policy-worker and native process CPU; policy-worker CPU is a separate scope.",
            "Native IPC wall is nested in caller wall; kernel/head timing is nested again.",
            "Readback archive duration is nested in training/worker wall and includes verification/removal.",
            "Task utility charges are not CPU time, energy or dollars; do not sum their units.",
            "Development smoke and failed-attempt totals are not inferred from successful formal counters.",
            "Shared host with concurrent main confirmation; no isolated hardware-speed or energy claim."]}
    write_json(root / "FEEDBACK_EXECUTION_COSTS.json", feedback)

    runtime_scopes, native_receipts, unique_ids, check_counts = [], {}, set(), Counter()
    qualification_cpu = qualification_wall = native_ipc = fresh_processes = recovery_ticks = in_process_ticks = 0
    maximum_cdf_error = 0.0
    for seed in protocol["runtime"]["seeds"]:
        folder = root / "runtime_confirmation" / f"seed_{seed}"
        q = read(folder / "QUALIFICATION.json")
        if not q["passed"] or q["development_only"] or not q["same_runtime_as_feedback_utility"]:
            raise ValueError("Runtime qualification failed or used development data")
        expected_model = frozen["artifacts_sha256"][f"feedback_prepared/seed_{seed}/MODELS.json"]
        if q["model_sha256"] != expected_model:
            raise ValueError("Runtime used a different model")
        with np.load(folder / "PUBLIC.npz", allow_pickle=False) as data:
            ids = [str(x) for x in data["ids"]]
            expected_ids = {f"feedback3:runtime_confirmation:{protocol['runtime']['data_offset'] + seed}:{i}"
                            for i in range(protocol["runtime"]["unique_histories_per_seed"])}
            if set(ids) != expected_ids or str(data["split"].item()) != "runtime_confirmation":
                raise ValueError("Runtime history coverage differs from registration")
            unique_ids.update(ids)
        with gzip.open(folder / "FORECASTS.json.gz", "rt") as stream:
            recorded = json.load(stream)
        pending_native = []
        if file_sha(folder / q["owners"]["path"]) != q["owners"]["sha256"]:
            raise ValueError("Runtime owner archive changed")
        with tarfile.open(folder / q["owners"]["path"], "r:gz") as archive:
            for member in archive:
                if member.isfile() and member.name.endswith("/pending.json"):
                    envelope = json.loads(archive.extractfile(member).read())
                    if digest(envelope["document"]) != envelope["sha256"]:
                        raise ValueError("Corrupt pending state")
                    if "native" in envelope["document"]:
                        pending_native.append(envelope["document"]["native"])
        recoveries = [read(folder / f"recovery_{sequence}.json") for sequence in (2, 3)]
        new_native = [r["native"] for r in recorded["ordinary"] + recorded["stress"]]
        new_native.extend(pending_native)
        new_native.extend(r["receipt"]["native"] for r in recoveries if r["native_requests"])
        seen = set()
        for native in new_native:
            key = (native["case"], native["checkpoint_after"])
            if key in seen or key in native_receipts:
                raise ValueError("Duplicate successful native tick accounting")
            seen.add(key)
            native_receipts[key] = native
        native_count = q["in_process_cost"]["native_ticks"] + q["recovery_native_ticks"]
        ipc = q["in_process_cost"]["native_roundtrip_ns"] + sum(r["native_roundtrip_ns"] for r in recoveries)
        if len(new_native) != native_count or sum(r["subprocess_roundtrip_ns"] for r in new_native) != ipc:
            raise ValueError("Runtime native accounting differs from actual deduplicated receipts")
        runtime_scopes.append({"seed": seed, "qualification": str((folder / "QUALIFICATION.json").relative_to(root)),
            "qualification_sha256": file_sha(folder / "QUALIFICATION.json"), "passed": q["passed"],
            "checks": len(q["checks"]), "unique_histories": q["unique_histories"],
            "ordinary_forecasts": q["ordinary_forecasts"], "fresh_processes": q["fresh_processes"],
            "native_ticks": native_count, "in_process_native_ticks": q["in_process_cost"]["native_ticks"],
            "recovery_native_ticks": q["recovery_native_ticks"], "native_roundtrip_ns": ipc,
            "qualification_wall_ns": q["wall_ns"], "qualification_parent_cpu_ns": q["cpu_ns"],
            "owner_archive_bytes": q["owners"]["bytes"], "owner_archive_files": q["owners"]["verified_files"]})
        qualification_cpu += q["cpu_ns"]
        qualification_wall += q["wall_ns"]
        native_ipc += ipc
        in_process_ticks += q["in_process_cost"]["native_ticks"]
        recovery_ticks += q["recovery_native_ticks"]
        fresh_processes += q["fresh_processes"]
        check_counts.update(q["checks"])
        maximum_cdf_error = max(maximum_cdf_error, max(r["native_cdf_error"] for r in recorded["ordinary"]))
    total_native = list(native_receipts.values())
    runtime = {"schema": "hepta.round3.feedback-runtime-results.v1", "passed": True,
        "complete": True, "source_commit": frozen["source_commit"], "seed_count": len(runtime_scopes),
        "unique_histories": len(unique_ids), "ordinary_forecasts": sum(s["ordinary_forecasts"] for s in runtime_scopes),
        "fresh_processes": fresh_processes, "native_ticks": len(total_native),
        "in_process_native_ticks": in_process_ticks, "recovery_native_ticks": recovery_ticks,
        "successful_native_requests": len(total_native), "cached_duplicate_recovery_new_native_ticks": 0,
        "native_receipt_deduplication": "(case, checkpoint_after); excludes cached duplicate and includes retained native-committed pending",
        "checks": sum(check_counts.values()), "check_counts": dict(check_counts), "scopes": runtime_scopes,
        "maximum_ordinary_cdf_absolute_error": maximum_cdf_error,
        "same_runtime_as_feedback_utility": True, "all_runtime_permission_confidences_zero": all(n["legacy_runtime_confidence_ppm"] == 0 for n in total_native),
        "all_native_abstain": all(n["abstain"] for n in total_native),
        "production_promotion": False, "cross_owner_atomicity": False,
        "source_or_density_retention_certificate": None,
        "runtime_source_sha256": frozen["sources_sha256"]["experiments/analytic_event_neuron/round3/runtime_feedback.py"],
        "scope": "Actual frozen count receiver and typed native head used by feedback decisions; state qualification is not retention or population calibration proof"}
    write_json(root / "RUNTIME_RESULTS.json", runtime)
    runtime_costs = {"schema": "hepta.round3.runtime-execution-costs.v1", "complete": True,
        "source_commit": frozen["source_commit"], "scopes": runtime_scopes,
        "phase_wall_ns": phases["runtime"]["wall_ns"], "phase_controller_parent_cpu_ns": phases["runtime"]["parent_cpu_ns"],
        "qualification_wall_ns_sum_nested_in_phase": qualification_wall,
        "qualification_parent_cpu_ns_sum_nested_in_phase": qualification_cpu,
        "successful_native_requests": len(total_native), "successful_native_ticks": len(total_native),
        "native_subprocess_roundtrip_ns_nested": native_ipc,
        "native_typed_tick_wall_ns_nested": sum(n["typed_tick_wall_ns"] for n in total_native),
        "native_head_execution_micros_nested": sum(n["head_execution_micros"] for n in total_native),
        "native_reported_journal_bytes_written": sum(n["journal_bytes_written"] for n in total_native),
        "maximum_sampled_native_process_resident_bytes": max(n["process_resident_bytes"] for n in total_native),
        "owner_compressed_archive_bytes": sum(s["owner_archive_bytes"] for s in runtime_scopes),
        "owner_archived_files": sum(s["owner_archive_files"] for s in runtime_scopes),
        "fresh_processes": fresh_processes,
        "unmeasured": {"native_subprocess_cpu_ns": None, "recovery_python_process_cpu_ns": None,
            "hardware_write_amplification_bytes": None, "energy_joules": None, "monetary_cost": None,
            "isolated_rejected_request_latency_ns": None},
        "rules": ["Do not add phase wall and contained qualification/native wall.",
            "Qualification parent CPU is contained in phase controller CPU; neither includes all child-process CPU.",
            "Native-reported journal write bytes are not total storage I/O or hardware write amplification.",
            "Cached duplicate returns retain old receipt timing; this aggregation excludes that timing a second time.",
            "Includes native-committed pending interruption; permission remains non-authorizing.",
            "Shared host; no isolated neuron hardware speed or energy claim."]}
    write_json(root / "RUNTIME_EXECUTION_COSTS.json", runtime_costs)
    freeze.verify(root)
    write_json(root / "FEEDBACK_RUNTIME_ACCOUNTING.json", {"schema": "hepta.round3.feedback-runtime-accounting-index.v1",
        "complete": True, "source_commit": frozen["source_commit"], "aggregator_sha256": file_sha(__file__),
        "reports": {name: file_sha(root / name) for name in ("FEEDBACK_RESULTS.json", "FEEDBACK_EXECUTION_COSTS.json",
            "RUNTIME_RESULTS.json", "RUNTIME_EXECUTION_COSTS.json")},
        "covered_successful_native_ticks_all_listed_nonoverlapping_phases": feedback["covered_successful_native_ticks"] + len(total_native),
        "not_a_full_failed_attempt_or_energy_or_monetary_cost_total": True})
    return feedback, runtime, runtime_costs


if __name__ == "__main__":
    a, b, c = aggregate(sys.argv[1])
    print(json.dumps({"feedback_control_executions": a["all_formal_episodes"],
        "feedback_phase_wall_seconds": a["confirmation_phase"]["wall_ns"] / 1e9,
        "runtime_histories": b["unique_histories"], "runtime_native_ticks": b["native_ticks"],
        "runtime_checks": b["checks"], "runtime_phase_wall_seconds": c["phase_wall_ns"] / 1e9}))
