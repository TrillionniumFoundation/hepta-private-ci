"""Recompute meter receipts from raw samples and independent fixture records."""

import argparse
import hashlib
import json
from pathlib import Path


def audit(directory):
    receipt_path = directory / "RECEIPT.json"
    receipt = json.loads(receipt_path.read_text())
    raw = (directory / "MEMORY_SAMPLES.jsonl").read_bytes()
    samples = [json.loads(line) for line in raw.splitlines()]
    checks = {
        "sample_digest": hashlib.sha256(raw).hexdigest() == receipt["sample_sha256"],
        "sample_count": len(samples) == receipt["memory"]["samples"],
        "rss_sum_each_sample": all(s["observed_rss_sum_bytes"] == sum(
            m["rss_bytes"] or 0 for m in s["members"]) for s in samples),
        "pss_sum_each_sample": all(s["observed_pss_sum_bytes"] == sum(
            m["pss_bytes"] or 0 for m in s["members"]) for s in samples),
        "rss_peak": receipt["memory"]["observed_peak_nonatomic_rss_sum_bytes"]
            == max(s["observed_rss_sum_bytes"] for s in samples),
        "pss_peak": receipt["memory"]["observed_peak_nonatomic_pss_sum_bytes"]
            == max(s["observed_pss_sum_bytes"] for s in samples),
        "waited_cpu_sum": abs(receipt["task_cpu_seconds"] - sum(
            s["cpu_seconds"] for s in receipt["wait4_subtrees"])) < 1e-12,
        "enclosing_cpu_counted_once": abs(receipt["enclosing_observed_cpu_seconds"]
            - receipt["task_cpu_seconds"] - receipt["measurement_cpu_seconds"]) < 1e-12,
        "no_complete_memory_claim": receipt["memory"]["complete"] is False
            and receipt["memory"]["continuous_complete_family_peak_bytes"] is None,
        "no_energy_claim": receipt["capabilities"]["energy"]["joules"] is None
            and receipt["capabilities"]["energy"]["attributable"] is False,
    }
    fixtures = []
    for path in sorted((directory / "fixture").glob("*.json")):
        value = json.loads(path.read_text())
        identity = {k: value["identity"][k] for k in ("pid", "start_ticks")}
        matches = [x for x in receipt["memory"]["seen_processes"] if x["identity"] == identity]
        fixtures.append({"role": value["role"], "allocated_bytes": value["allocated_bytes"],
                         "self_cpu_seconds": value["self_cpu_seconds"],
                         "identity_seen": bool(matches),
                         "resident_memory_sample_seen": bool(matches and matches[0]["available_samples"]),
                         "observed_ppids": matches[0]["observed_ppids"] if matches else [],
                         "identity": identity})
    if fixtures:
        fixture_cpu = sum(x["self_cpu_seconds"] for x in fixtures)
        checks["waited_cpu_covers_fixture_self_cpu"] = receipt["task_cpu_seconds"] >= fixture_cpu - 1e-6
    return {"directory": str(directory), "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "checks": checks, "all_checks_pass": all(checks.values()),
            "fixture_diagnostics": fixtures, "task_success": receipt["task_success"],
            "task_cpu_seconds": receipt["task_cpu_seconds"],
            "monitor_cpu_seconds": receipt["measurement_cpu_seconds"],
            "observed_nonatomic_rss_peak_bytes": receipt["memory"]["observed_peak_nonatomic_rss_sum_bytes"],
            "observed_nonatomic_pss_peak_bytes": receipt["memory"]["observed_peak_nonatomic_pss_sum_bytes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = [audit(path.parent) for path in sorted(args.results.glob("*/RECEIPT.json"))]
    report = {"schema": "hcsn-v9-cost-audit.v1", "rows": rows,
              "all_checks_pass": bool(rows) and all(row["all_checks_pass"] for row in rows),
              "failed_workloads_retained": [row["directory"] for row in rows if not row["task_success"]]}
    with args.out.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"receipts": len(rows), "all_checks_pass": report["all_checks_pass"]}))
    return 0 if report["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
