"""Aggregate disjoint retained CPU scopes; never impute unknown whole-run cost."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "experiments/hcsn_v12_followup_20261101"
OUT = BASE / "results/economics"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cpu(value):
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def resource_rows(run):
    rows = []
    for path in sorted(run.rglob("RESOURCE.json")):
        record = read(path)
        meter = read(path.parent / "meter/RECEIPT.json")
        assert record["singleton_profile_verified"] is True
        assert meter["task_success"] and meter["cleanup_verified"]
        assert len(meter["waited_subtrees"]) == 1
        verified = read(path.parent / "VERIFY.json")
        verification = read(path.parent / "VERIFY_COST.json")
        assert verification["exit_code"] == 0 and verified["status"] == "passed"
        rows.append({"directory": str(path.parent.relative_to(run)), **record["case"],
                     "whole_worker_cpu_seconds": float(cpu(record["whole_worker_cpu_seconds"])),
                     "outside_verifier_cpu_seconds": float(cpu(verification["cpu_seconds"])),
                     "worker_family_rss_peak_bytes": record["worker_family_rss_peak_bytes"],
                     "cgroup_charge_peak_bytes": record["cgroup_charge_peak_bytes"],
                     "episodes": verified["executions"], "resource_sha256": sha(path)})
    return rows


def main():
    report = read(OUT / "COST_SCOPE_PRE_CI.json")
    components = report["recorded_components"]
    old_receipts = {item["receipt"] for item in components}
    ledger = read(BASE / "control/COST_LEDGER.json")
    assert ledger["worker_count"] == 14
    assert sum(cpu(item["cpu_seconds"]) for item in ledger["workers"]) == Decimal("620.406604")
    for item in ledger["workers"]:
        path = BASE / "control" / item["path"]
        relative = str(path.relative_to(ROOT))
        if relative not in old_receipts:
            record = read(path)
            assert record["task_success"] == item["task_success"]
            components.append({"name": "control_" + item["path"], "cpu_seconds": float(cpu(item["cpu_seconds"])),
                               "receipt": relative, "receipt_sha256": sha(path),
                               "task_success": item["task_success"], "complete_task_cpu_coverage": True,
                               "cost_scope": "Independent enclosing waited worker; inner clocks already included."})
    success = BASE / "results/ci_run41374287486_attempt1/artifact/model-costs"
    cancelled = BASE / "results/ci_run41374244788_cancelled/artifact/model-costs"
    campaign = read(success / "CAMPAIGN.json")
    assert campaign["status"] == "PASS" and len(campaign["results"]) == 40
    good_rows, partial_rows = resource_rows(success), resource_rows(cancelled)
    assert len(good_rows) == 40 and sum(row["episodes"] for row in good_rows) == 1440
    assert not (cancelled / "CAMPAIGN.json").exists()
    audit_path = BASE / "results/ci_run41374287486_attempt1/review_cost001/RECEIPT.json"
    audit = read(audit_path)
    assert audit["task_success"]
    components.extend([
        {"name": "successful_ci_driver", "cpu_seconds": float(cpu(campaign["enclosing_cpu_seconds_lower_bound"])),
         "receipt": str((success / "CAMPAIGN.json").relative_to(ROOT)),
         "receipt_sha256": sha(success / "CAMPAIGN.json"), "cost_scope": campaign["enclosing_cost_scope"]},
        {"name": "local_independent_ci_audit", "cpu_seconds": float(cpu(audit["complete_supervisor_wait4"]["cpu_seconds"])),
         "receipt": str(audit_path.relative_to(ROOT)), "receipt_sha256": sha(audit_path),
         "cost_scope": "Local outer worker reviewing downloaded CI; not part of remote driver."}])
    subtotal = sum(cpu(item["cpu_seconds"]) for item in components)
    partial = sum(cpu(row["whole_worker_cpu_seconds"]) + cpu(row["outside_verifier_cpu_seconds"])
                  for row in partial_rows)
    report.update(scope_state="ACTUAL_CI_AND_CONTROL_COMPLETE_WITH_UNKNOWN_PROJECT_COST",
                  recorded_disjoint_cpu_lower_bound_seconds=float(subtotal),
                  subtotals_cpu_seconds={"runtime": 68.452922, "review": 8.795378, "frontend": 5.701940,
                      "control": 620.406604, "economics_sparse_smoke": 1.237109,
                      "successful_ci_driver": float(cpu(campaign["enclosing_cpu_seconds_lower_bound"])),
                      "local_independent_ci_audit": float(cpu(audit["complete_supervisor_wait4"]["cpu_seconds"]))},
                  pending_control_audits_cpu_seconds="none; all 14 retained control envelopes included",
                  cancelled_run={"run_id": 41374244788, "complete_campaign_cpu_seconds": None,
                      "completed_worker_receipts": len(partial_rows),
                      "completed_worker_and_verifier_cpu_lower_bound_seconds": float(partial),
                      "scope": "Only completed resource/verifier pairs; unfinished worker, initial identity/setup, driver, cleanup and cancellation remain unmeasured."},
                  additional_disjoint_partial_scope_lower_bound_seconds={
                      "control_first_smoke_inner_only": ledger["known_first_smoke_inner_CPU_seconds_separate_scope"],
                      "cancelled_ci_completed_workers_and_verifiers": float(partial)},
                  ci={"run_id": 41374287486, "state": "ACTUAL_RAW_ARTIFACT_AND_INDEPENDENT_AUDIT_PASS",
                      "enclosing_driver_cpu_seconds_lower_bound": float(cpu(campaign["enclosing_cpu_seconds_lower_bound"])),
                      "model_worker_cpu_seconds_nested": float(sum(cpu(row["whole_worker_cpu_seconds"]) for row in good_rows)),
                      "external_verifier_cpu_seconds_nested": float(sum(cpu(row["outside_verifier_cpu_seconds"]) for row in good_rows)),
                      "setup_cpu_seconds": None, "network_cost": None})
    report["nested_costs_excluded_from_addition"].append("Success CI worker/verifier/inner audit CPU already belongs to its enclosing 50.522798s; cancelled-run partial counters are separate, not an imputed whole campaign.")
    report["limits"][-1] = "Post-CI checkpoint: recorded disjoint envelopes plus explicitly separate partial lower bounds; no unknown cost imputed. Complete project, energy and historical costs remain null."
    (OUT / "COST_SCOPE.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = {"schema": "hcsn-v12-actual-ci-resource-summary.v1", "successful_workers": good_rows,
               "cancelled_completed_workers": partial_rows,
               "rss_scope": "Only trusted no-swap singleton actual-model profile; not an arbitrary-family, cold-page or energy claim."}
    (OUT / "CI_RESOURCE_SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"recorded_disjoint_cpu_lower_bound_seconds": float(subtotal),
                      "cancelled_complete_workers": len(partial_rows), "cancelled_partial_cpu_lower_bound": float(partial)}))


if __name__ == "__main__":
    main()
