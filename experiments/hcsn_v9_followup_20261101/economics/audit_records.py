"""Independent standard-library audit of actual cost fixture records."""

import argparse
import json
from pathlib import Path


def audit(directory):
    checks = []
    results = {}
    capability = json.loads((directory / "CAPABILITY.json").read_text())
    checks.append(capability["complete_process_family_peak_bytes"] is None)
    checks.append(capability["shared_cgroup_peak_used"] is False)
    for mode in ("waited", "adopted"):
        prefix = directory / "results"
        records = {x.stem: json.loads(x.read_text()) for x in (prefix / (mode + "_nodes")).glob("*.json")}
        supervision = json.loads((prefix / mode / "SUPERVISION.json").read_text())
        receipt = json.loads((prefix / mode / "RECEIPT.json").read_text())
        checks.append(set(records) == {"root", "child", "grandchild", "short_leaf"})
        checks.append(len({r["pid"] for r in records.values()}) == 4)
        for parent, child in (("root", "child"), ("child", "grandchild"), ("grandchild", "short_leaf")):
            checks.append(records[parent]["spawned_pid"] == records[child]["pid"])
        checks.append(supervision["all_waitable_children_collected"] is True)
        checks.append(supervision["complete_task_cpu_coverage"] is True)
        checks.append(receipt["task_success"] is True)
        checks.append(all(r["family_peak_bytes"] is None for r in records.values()))
        checks.append(supervision["memory"]["family_sampled_peak_rss_sum_bytes"] is None)
        checks.append(supervision["energy"]["joules"] is None)
        checks.append(all(r["exit_code"] == 0 for r in supervision["disjoint_wait4_subtrees"]))
        checks.append(receipt["complete_supervisor_wait4"]["cpu_seconds"] >= supervision["observed_task_subtree_cpu_seconds"])
        reaped = {r["pid_in_supervisor_namespace"] for r in supervision["disjoint_wait4_subtrees"]}
        if mode == "adopted":
            supervisor_pid = records["root"]["parent_before"]
            checks.append(reaped == {records[r]["pid"] for r in ("root", "child", "grandchild")})
            checks.append(records["child"]["parent_after"] == supervisor_pid)
            checks.append(records["grandchild"]["parent_after"] == supervisor_pid)
            checks.append(records["short_leaf"]["begin_monotonic_ns"] > records["root"]["end_monotonic_ns"])
        else:
            checks.append(reaped == {records["root"]["pid"]})
            checks.append(all(records[r]["waited_children"] for r in ("root", "child", "grandchild")))
        registered_peak = supervision["memory"]["registered_subset_peak_rss_sum_bytes"]
        leaf_peak = records["short_leaf"]["self_highwater_diagnostic_bytes"]
        checks.append(registered_peak < leaf_peak)
        results[mode] = {
            "complete_enclosing_cpu_seconds": receipt["complete_supervisor_wait4"]["cpu_seconds"],
            "registered_subset_sampled_peak_bytes": registered_peak,
            "leaf_single_process_highwater_diagnostic_bytes": leaf_peak,
            "leaf_lifetime_seconds": (records["short_leaf"]["end_monotonic_ns"] - records["short_leaf"]["begin_monotonic_ns"]) / 1e9,
            "registered_peak_cannot_bound_family_peak": registered_peak < leaf_peak,
            "reaped_subtree_roots": len(reaped),
        }
    return {"passed": all(checks), "checks": len(checks), "failed": sum(not c for c in checks), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.directory)
    with args.out.open("x") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
