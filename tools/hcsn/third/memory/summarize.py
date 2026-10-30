"""Post-run evidence audit and descriptive summaries; never trains or selects."""
from datetime import datetime
import itertools
import json
import math
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from third.memory.execution import atomic_json
from third.memory.freeze import verify, sha


def read(name):
    return json.loads((HERE/name).read_text())


def main():
    verify()
    result = read("development_results.json")
    protocol, rows = result["protocol"], result["runs"]
    audit = read("development_audit.json")
    numerical = read("numerical_validation.json")
    amendment = read("operational_amendment.json")
    handoff = read("operational_handoff.json")
    preserved = read(amendment["preserved_result_file"])
    expected = set(itertools.product(protocol["tasks"], protocol["seeds"], protocol["variants"]))
    actual = {(r["task"], r["seed"], r["variant"]) for r in rows}
    checks = dict(complete=result["complete"] and actual == expected and len(rows) == len(expected),
        independent_replay=audit["passed"] and audit["development_results_sha256"] == sha(HERE/"development_results.json"),
        numerical_receipt=numerical["passed"] and numerical["freeze_sha256"] == sha(HERE/"freeze.json"),
        original_first_run_preserved=rows[:amendment["applies_after_completed_runs"]] == preserved["runs"],
        scientific_freeze_unchanged=sha(HERE/"freeze.json") == amendment["scientific_freeze_sha256"],
        numerical_receipt_unchanged=sha(HERE/"numerical_validation.json") == amendment["numeric_receipt_sha256"],
        execution_driver_unchanged=sha(HERE/"operational_driver.py") == amendment["driver_sha256"],
        handoff_unchanged=sha(HERE/"operational_handoff.json") == amendment["handoff_receipt_sha256"])
    checks["preserved_files_unchanged"] = all(sha(HERE/"before_operational_amendment"/name) == digest
        for name, digest in handoff["preserved_sha256"].items())
    amended_rows = rows[amendment["applies_after_completed_runs"]:]
    checks["all_later_runs_identify_driver"] = all(
        r["operational_driver"]["driver_sha256"] == amendment["driver_sha256"] and
        r["operational_driver"]["amendment_sha256"] == sha(HERE/"operational_amendment.json") and
        r["resource_pause"]["execution_driver_sha256"] == amendment["driver_sha256"] for r in amended_rows)
    checks["checkpoint_hashes"] = all(sha(HERE/r["checkpoint_file"]) == r["checkpoint_sha256"] for r in rows)
    checks["budgets_preserved"] = all(r["timing"]["steps"] == protocol["training_updates"] and
        r["timing"]["batch_size"] == protocol["batch_size"] and
        r["timing"]["learning_rate"] == protocol["learning_rate"] for r in rows)
    checks["validation_only_checkpoint_selection"] = all(r["timing"]["best_step"] ==
        min(r["history"], key=lambda h: h["validation"]["loss"])["step"] for r in rows)
    checks["logged_training_finite"] = all(math.isfinite(r["timing"]["max_unclipped_gradient_norm"]) and
        all(math.isfinite(h["train_minibatch_loss"]) and math.isfinite(h["validation"]["loss"])
            for h in r["history"]) for r in rows)
    summaries = []
    for task, variant in itertools.product(protocol["tasks"], protocol["variants"]):
        group = sorted((r for r in rows if r["task"] == task and r["variant"] == variant), key=lambda r:r["seed"])
        metrics = {split:dict(mean_accuracy=statistics.mean(r["metrics"][split]["accuracy"] for r in group),
            worst_seed_accuracy=min(r["metrics"][split]["accuracy"] for r in group),
            per_seed_accuracy={str(r["seed"]):r["metrics"][split]["accuracy"] for r in group})
            for split in ("validation32", "diagnostic128", "diagnostic512")}
        summaries.append(dict(task=task, variant=variant, metrics=metrics,
            width=group[0]["width"], parameters=group[0]["parameters"], resources=group[0]["resources"],
            median_logit_batch32_ms=statistics.median(r["latency_batch32"]["median_ms"] for r in group),
            median_optimizer_update_ms=statistics.median(r["timing"]["optimizer_update_median_ms"] for r in group)))
    paired = []
    for task, family in itertools.product(protocol["tasks"], ("full", "sigmoid", "c1", "memory")):
        pairs = {}
        for split in ("diagnostic128", "diagnostic512"):
            deltas = []
            for seed in protocol["seeds"]:
                match = {r["variant"]:r for r in rows if r["task"] == task and r["seed"] == seed}
                deltas.append(match[family+"_mass"]["metrics"][split]["accuracy"] -
                              match[family+"_fixed"]["metrics"][split]["accuracy"])
            pairs[split] = dict(per_seed_delta=dict(zip(map(str,protocol["seeds"]),deltas)),
                mean_delta=statistics.mean(deltas))
        paired.append(dict(task=task, family=family, paired_mass_minus_fixed=pairs))
    targets = protocol["development_gate"]
    gate = dict(matrix_complete=checks["complete"])
    for task in protocol["tasks"]:
        group = [r for r in rows if r["task"] == task and r["variant"] == "full_mass"]
        gate[task+"128_every_seed"] = all(r["metrics"]["diagnostic128"]["accuracy"] >=
            targets["full_mass_every_seed_"+task+"128_min"] for r in group)
        delta = next(p for p in paired if p["task"] == task and p["family"] == "full")
        gate[task+"512_delta"] = (delta["paired_mass_minus_fixed"]["diagnostic512"]["mean_delta"] >=
            targets["full_mass_minus_full_fixed_mean_"+task+"512_min"])
    diagnostics = [d for r in rows for d in r["solve_diagnostics"].values()]
    gate["all_numerical"] = all(d["all_finite"] and d["condition_bound_satisfied"] and
        d["maximum_relative_residual"] <= targets["maximum_solve_relative_residual"] and
        d["maximum_condition_times_solver_epsilon"] <= protocol["numerical_standards"]["maximum_condition_times_solver_epsilon"]
        for d in diagnostics)
    checks["gate_independently_recomputed"] = (gate == result["development_gate"]["checks"] and
        all(gate.values()) == result["development_gate"]["passed"])
    snapshots = [amendment["initial_resources"]]
    snapshots += [r["resource_pause"]["admission_snapshot"] for r in amended_rows]
    snapshots += [r["resources_after_run"] for r in amended_rows]
    restart = read("final_run_handoff.json") if (HERE/"final_run_handoff.json").exists() else None
    if restart:
        saved = read(restart["saved_result_file"])
        checks["all_pre_final_restart_runs_preserved"] = rows[:restart["completed_runs"]] == saved["runs"]
        checks["final_restart_preserved_files_unchanged"] = all(
            sha(HERE/"before_final_run_restart"/name) == digest for name,digest in restart["preserved_sha256"].items())
        checks["final_restart_same_driver"] = restart["driver_sha256"] == amendment["driver_sha256"]
    for name in ("before_final_run_restart/operational_resource_pause.json", "operational_resource_pause.json"):
        if (HERE/name).exists():
            snapshots.extend(read(name)["observations"])
    baseline = amendment["initial_resources"]["oom_events"]
    counters = {k: max(s["oom_events"][k] for s in snapshots)-baseline[k] for k in baseline}
    checks["admission_headroom_preserved"] = all(
        r["resource_pause"]["admission_snapshot"]["estimated_headroom_bytes"] >= 1500000000 for r in amended_rows)
    timing_keys = ("total_train_call_seconds", "compilation_seconds", "optimizer_execution_seconds", "validation_seconds", "host_batch_seconds")
    costs = {k:sum(r["timing"][k] for r in rows) for k in timing_keys}
    costs.update(completed_training_runs=len(rows), optimizer_updates=sum(r["timing"]["steps"] for r in rows),
        numerical_validation_attempts_are_training_runs=False,
        recorded_runner_elapsed_seconds=result["elapsed_seconds"],
        original_post_first_run_pause_seconds=datetime.fromisoformat(handoff["utc"]).timestamp() -
            handoff["active_attempt"]["started_epoch_seconds"]-handoff["active_attempt"]["elapsed_seconds"],
        final_pre_run_pause_seconds=(datetime.fromisoformat(restart["utc"]).timestamp() -
            restart["active_attempt"]["started_epoch_seconds"]-restart["active_attempt"]["elapsed_seconds"]) if restart else 0.,
        interrun_process_restarts=1+int(restart is not None),
        peak_process_rss_bytes=max(r["process_peak_rss_bytes"] for r in rows),
        maximum_unclipped_training_gradient_norm=max(r["timing"]["max_unclipped_gradient_norm"] for r in rows),
        maximum_observed_cgroup_raw_bytes=max(s["raw_current_bytes"] for s in snapshots),
        cgroup_oom_counter_changes=counters,
        cgroup_counter_scope="Since operational amendment after the first completed run; historical counters are not attributed to this experiment.",
        timing_scope="Shared CPU with recorded inter-run restarts; no speed claim across cache/admission changes. Diagnostics and independent replay cost are not optimizer execution.")
    report = dict(evidence_audit_passed=all(checks.values()), evidence_checks=checks,
        development_gate_passed=all(gate.values()), development_gate_checks=gate,
        groups=summaries, paired_mass_minus_fixed=paired, costs=costs,
        maxima={k:max(d[k] for d in diagnostics) for k in ("maximum_condition", "maximum_relative_residual",
            "maximum_condition_times_solver_epsilon", "maximum_condition_times_state_epsilon", "maximum_read", "maximum_write_mass")},
        scientific_freeze_sha256=sha(HERE/"freeze.json"), development_results_sha256=sha(HERE/"development_results.json"),
        replay_audit_sha256=sha(HERE/"development_audit.json"), summarizer_sha256=sha(Path(__file__)),
        scope="Descriptive development results only; no confirmation data, financial superiority or large-backbone authorization.")
    atomic_json(HERE/"development_summary.json", report)
    print(json.dumps({k:report[k] for k in ("evidence_audit_passed", "development_gate_passed", "development_gate_checks", "costs", "maxima")},indent=2))
    if not report["evidence_audit_passed"]:
        raise RuntimeError("Post-run evidence audit failed; retain and investigate")


if __name__ == "__main__":
    main()
