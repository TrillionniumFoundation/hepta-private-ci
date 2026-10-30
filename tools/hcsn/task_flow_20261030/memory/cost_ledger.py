"""Separate measured scopes, nested components and explicitly unknown costs."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.memory.execution import atomic_json
from task_flow_20261030.memory.freeze import sha


def main():
    result = json.loads((HERE / "results.json").read_text())
    audit = json.loads((HERE / "audit.json").read_text())
    validation = json.loads((HERE / "validation.json").read_text())
    diagnosis = json.loads((HERE / "diagnosis.json").read_text())
    archive = json.loads((HERE / "archive_validation.json").read_text())
    numerical = json.loads((HERE / "replay_diagnosis.json").read_text())["execution"]
    interrupted_wait_snapshot = json.loads((HERE / "resource_pause.json").read_text())
    runs = result["runs"]
    completed_cpu = sum(r["run_cpu_seconds"] for r in runs)
    completed_wall = sum(r["run_wall_seconds"] for r in runs)
    pauses = [r["resource_admission"] for r in runs]
    observed_wait = sum(r.get("wait_seconds", r.get("operational_admission", {}).get("wait_seconds", 0)) for r in pauses)
    ledger = dict(
        complete_training_matrix=result["complete"],
        measured_completed_run_cpu_seconds=completed_cpu,
        measured_completed_run_wall_seconds=completed_wall,
        additional_numpy_audit_cpu_seconds=audit["cpu_seconds"],
        additional_numpy_audit_wall_seconds=audit["wall_seconds"],
        additional_exploratory_diagnosis_cpu_seconds=diagnosis["cpu_seconds"],
        additional_exploratory_diagnosis_wall_seconds=diagnosis["wall_seconds"],
        additional_archive_and_restore_cpu_seconds=archive["measured_cpu_seconds"],
        additional_archive_and_restore_wall_seconds=archive["wall_seconds"],
        additional_independent_numerical_diagnosis_cpu_seconds=numerical["cpu_seconds"],
        additional_independent_numerical_diagnosis_wall_seconds=numerical["wall_seconds"],
        measured_cpu_lower_bound_seconds=(completed_cpu + audit["cpu_seconds"] + diagnosis["cpu_seconds"]
            + archive["measured_cpu_seconds"] + numerical["cpu_seconds"]),
        measured_nonoverlapping_wall_lower_bound_seconds=(completed_wall + audit["wall_seconds"]
            + max(diagnosis["wall_seconds"] + archive["wall_seconds"], numerical["wall_seconds"])
            + validation["wall_seconds"] + observed_wait),
        separate_pretraining_validation_wall_seconds=validation["wall_seconds"],
        pretraining_validation_cpu_seconds=None,
        completed_admission_wait_wall_seconds=observed_wait,
        interrupted_admission_wait_wall_seconds=None,
        interrupted_admission_wait_observed_lower_bound_wall_seconds=interrupted_wait_snapshot["wait_seconds"],
        data_generation_freshness_and_startup_cpu_seconds=None,
        summary_rendering_coordination_and_minor_reporting_repair_cpu_seconds=None,
        development_editing_download_or_network_cost=None,
        nested_training_components=dict(
            compilation_seconds=sum(r["training"]["compilation_seconds"] for r in runs),
            optimizer_seconds=sum(r["training"]["optimizer_seconds"] for r in runs),
            validation_seconds=sum(r["training"]["validation_seconds"] for r in runs)),
        peak_process_rss_bytes=max(r["process_peak_rss_bytes"] for r in runs),
        source_inputs={p: sha(HERE / p) for p in ("results.json", "audit.json", "validation.json", "freeze.json", "diagnosis.json", "archive_validation.json", "replay_diagnosis.json")},
        convention="Completed-run scopes include init/compile/train/evaluate/latency/persistence; nested training components are not added again. Initial validation, completed admissions, runs and final audit were sequential. After the audit, address diagnosis then archive verification were one sequential branch; independent numerical diagnosis may overlap them, so the wall lower bound adds only max(branches), while CPU adds both. Interrupted admission is excluded because it briefly overlapped continuation. Null means unmeasured, never zero.",
        full_campaign_cost_known=False,
    )
    atomic_json(HERE / "cost_ledger.json", ledger)
    print(json.dumps(ledger, indent=2))


if __name__ == "__main__":
    main()
