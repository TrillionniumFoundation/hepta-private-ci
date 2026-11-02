"""Audit disjoint phase receipts and controlled conservative memory bounds."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def audit_bound(directory):
    value = json.loads((directory / "fixture/BOUND.json").read_text())
    processes = value["per_process_records"]
    expected = {p["identity"]["namespace_pid"] for p in processes}
    waits = value["external_waits"] + [w for p in processes for w in p["waited_children"]]
    actual = [w["namespace_pid"] for w in waits]
    bound = sum(w["maxrss_upper_bytes"] for w in waits)
    identities = {(p["identity"]["proc_pid"], p["identity"]["start_ticks"]): p["role"] for p in processes}
    observed_rss, observed_pss, seen, role_samples = [], [], set(), defaultdict(int)
    for line in (directory / "inner/MEMORY_SAMPLES.jsonl").read_text().splitlines():
        sample = json.loads(line)
        members = [m for m in sample["members"] if (m["pid"], m["start_ticks"]) in identities and m["available"]]
        observed_rss.append(sum(m["rss_bytes"] for m in members))
        observed_pss.append(sum(m["pss_bytes"] for m in members))
        for member in members:
            key = (member["pid"], member["start_ticks"])
            seen.add(key)
            role_samples[identities[key]] += 1
    checks = {"unique_complete_wait_inventory": len(actual) == len(set(actual)) and set(actual) == expected,
              "bound_recomputed": bound == value["conservative_upper_bound_rss_sum_bytes"],
              "four_controlled_roles": {p["role"] for p in processes} == {"root", "child", "grandchild", "short"},
              "all_exit_success": all(w["exit_code"] == 0 for w in waits),
              "observed_rss_sums_bounded": all(x <= bound for x in observed_rss),
              "observed_pss_sums_bounded": all(x <= bound for x in observed_pss),
              "no_exact_peak_claim": value["exact_simultaneous_family_peak_bytes"] is None,
              "short_task_bound_included": any(w["namespace_pid"] == next(p["identity"]["namespace_pid"] for p in processes if p["role"] == "short") for w in waits)}
    return {"path": str(directory), "checks": checks, "pass": all(checks.values()),
            "conservative_upper_bound_bytes": bound,
            "observed_nonatomic_fixture_rss_sum_peak_bytes": max(observed_rss),
            "observed_nonatomic_fixture_pss_sum_peak_bytes": max(observed_pss),
            "resident_samples_by_role": dict(role_samples),
            "physical_unique_memory_peak_bytes": None,
            "scope": "Closed fixture family only; no inference of a production-family bound"}


def build(results, out):
    records, checks, seen = [], {}, set()
    grouped = defaultdict(list)
    for path in sorted(results.glob("*/PHASE_RECEIPT.json")):
        row = json.loads(path.read_text())
        key = (row["study"], row["stage"], row["attempt"])
        if key in seen:
            raise ValueError("Duplicate phase attempt " + repr(key))
        seen.add(key)
        inner_path = path.parent / "inner/RECEIPT.json"
        inner = json.loads(inner_path.read_text()) if inner_path.exists() else None
        stage_source = path.parent / "SOURCE_STAGE_METER.py"
        inner_source = path.parent / "SOURCE_INNER_METER.py"
        local_checks = {
            "inner_digest": (hashlib.sha256(inner_path.read_bytes()).hexdigest() == row["inner_receipt_sha256"]
                             if inner is not None else row["inner_receipt_sha256"] is None),
            "stage_source_digest": hashlib.sha256(stage_source.read_bytes()).hexdigest() == row["stage_meter_sha256"],
            "inner_source_digest": hashlib.sha256(inner_source.read_bytes()).hexdigest() == row["inner_meter_sha256"],
            "outer_covers_inner_cpu": (row["outer_wait4_cpu_seconds"] + 1e-6 >= inner["enclosing_observed_cpu_seconds"]
                                      if inner is not None else row["success"] is False),
            "cpu_decomposition": (abs(row["outer_wait4_cpu_seconds"] - inner["enclosing_observed_cpu_seconds"]
                - row["meter_bootstrap_and_serialization_cpu_seconds_diagnostic"]) < 1e-10
                if inner is not None else row["meter_bootstrap_and_serialization_cpu_seconds_diagnostic"] is None),
            "historical_unknown_preserved": row["historical_preparation_cpu_seconds"] is None,
            "energy_unknown_preserved": row["device_energy_joules"] is None,
            "no_complete_memory_claim": row["continuous_exact_family_memory_peak_bytes"] is None,
        }
        checks[str(path)] = local_checks
        record = {"study": row["study"], "stage": row["stage"], "attempt": row["attempt"],
                  "command": row["command"],
                  "path": str(path), "cpu_seconds": row["outer_wait4_cpu_seconds"],
                  "wall_seconds": row["wall_seconds"], "success": row["success"],
                  "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        records.append(record)
        grouped[row["study"]].append(record)
    bounds = [audit_bound(path) for path in sorted(results.glob("hwm_*/"))]
    scope_path = results.parent / "LIFECYCLE_SCOPE.json"
    scope = json.loads(scope_path.read_text()) if scope_path.exists() else {"required_phases": {}}
    coverage = {}
    for study, phases in scope["required_phases"].items():
        active = scope.get("active_output_by_study", {}).get(study)
        def applies(record):
            if active is None or active in record["command"]:
                return True
            return record["stage"] == "validation" and "--output" not in record["command"]
        completed = {r["stage"] for r in records if r["study"] == study and r["success"] and applies(r)}
        coverage[study] = {"required": phases, "present_successful": sorted(completed),
                           "active_output": active,
                           "missing": [stage for stage in phases if stage not in completed],
                           "formal_phase_metering_complete": set(phases) <= completed}
    report = {"schema": "hcsn-v10-exclusive-phase-ledger.v1", "records": records,
              "audit_scope": "Cost-account identity/arithmetic and controlled memory-bound fixtures only; not scientific adoption acceptance",
              "study_totals": {name: {"measured_cpu_seconds": sum(r["cpu_seconds"] for r in rows),
                               "failed_attempt_cpu_seconds": sum(r["cpu_seconds"] for r in rows if not r["success"]),
                               "phase_labels_present": sorted({r["stage"] for r in rows})}
                               for name, rows in grouped.items()},
              "phase_checks": checks, "memory_bound_fixture_audits": bounds,
              "all_checks_pass": all(all(v.values()) for v in checks.values()) and all(b["pass"] for b in bounds),
              "formal_lifecycle_coverage": coverage,
              "formal_lifecycle_metering_complete": bool(coverage) and all(v["formal_phase_metering_complete"] for v in coverage.values()),
              "lifecycle_scope_sha256": hashlib.sha256(scope_path.read_bytes()).hexdigest() if scope_path.exists() else None,
              "measured_disjoint_total_cpu_seconds": sum(r["cpu_seconds"] for r in records),
              "total_historical_development_cpu_seconds": None,
              "unmeasured_source_authoring_and_initial_inspection_cpu_seconds": None,
              "initial_meter_path_failure_cpu_seconds": None,
              "no_whole_development_cost_claim": True,
              "energy_joules": None, "exact_independent_family_memory_peak_bytes": None,
              "rule": "Only outer phase CPU is added. Studies/stages may overlap in wall time; process subtrees are disjoint. Wall times are never added as a concurrent critical-path latency."}
    with out.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"phases": len(records), "checks_pass": report["all_checks_pass"],
                      "measured_disjoint_cpu_seconds": report["measured_disjoint_total_cpu_seconds"]}))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.results, args.out)
    return 0 if result["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
