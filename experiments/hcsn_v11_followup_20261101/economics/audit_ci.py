"""Independent standard-library audit; never import the meter's aggregation code."""

import argparse
import hashlib
import json
from pathlib import Path


def allocation_floor_holds(peak, nodes):
    allocations = [node["allocated_touched_bytes"] for node in nodes.values()]
    return (type(peak) is int and bool(allocations)
            and all(type(value) is int and value > 0 for value in allocations)
            and peak >= max(allocations))


def audit(run):
    checks, findings = [], {}
    identity = json.loads((run / "IDENTITY.json").read_text())
    profile = json.loads((run / "PARENT_PROFILE.json").read_text())
    checks.extend([profile["memory_swap_max"] == "0", profile["empty_before_admission"] is True,
                   {"cpu", "memory"}.issubset(profile["enabled_controllers"])])
    checks.append(identity["checkout_sha"] == identity["expected_head"])
    required = {"experiments/hcsn_v10_followup_20261101/economics/cgroup_meter.py",
                "experiments/hcsn_v10_followup_20261101/economics/runner_campaign.py",
                "experiments/hcsn_v9_followup_20261101/economics/short_tree_probe.py",
                ".github/workflows/hcsn-v11-cgroup-economics.yml"}
    checks.append(required.issubset({item["path"] for item in identity["sources"]}))
    for item in identity["sources"]:
        content = (run / item["snapshot"]).read_bytes()
        checks.append(hashlib.sha256(content).hexdigest() == item["sha256"])
        checks.append(hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == item["git_blob"])
        checks.append(hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"])
    checks.append(hashlib.sha256(Path(identity["python_binary"]["path"]).read_bytes()).hexdigest() == identity["python_binary"]["sha256"])
    campaign = run / "campaign"
    summary = json.loads((campaign / "SUMMARY.json").read_text())
    checks.append(summary["status"] == "PASS")
    for mode in ("waited", "adopted", "nonzero", "timeout"):
        receipt = json.loads((campaign / mode / "RECEIPT.json").read_text())
        checks.extend([
            receipt["status"] == "MEASURED", receipt["measurement_valid"] is True,
            receipt["cleanup_verified"] is True, receipt["all_group_tasks_exited"] is True,
            receipt["root_membership_confirmed_before_release"] is True,
            receipt["empty_group_kill_checked_before_admission"] is True,
            receipt["populated_before_removal"] == 0, receipt["group_absent_after_removal"] is True,
            Path(receipt["group_path"]).parent == Path(profile["parent"]),
            receipt["complete_process_family_rss_peak_bytes"] is None, receipt["device_energy_joules"] is None,
            receipt["cgroup_memory_charge_peak_bytes"] >= receipt["cgroup_memory_current_at_exit_bytes"] >= 0,
            receipt["cgroup_cpu_usage_seconds"] > 0,
            abs(receipt["cgroup_cpu_stat_at_exit"]["usage_usec"] / 1e6 - receipt["cgroup_cpu_usage_seconds"]) < 1e-9,
        ])
        waits = receipt["waited_subtrees"]
        checks.append(any(item["pid"] == receipt["root_pid"] for item in waits))
        if mode in ("waited", "adopted"):
            nodes = {p.stem: json.loads(p.read_text()) for p in (campaign / (mode + "_nodes")).glob("*.json")}
            checks.append(set(nodes) == {"root", "child", "grandchild", "short_leaf"})
            checks.append(len({n["pid"] for n in nodes.values()}) == 4)
            checks.append(nodes["root"]["pid"] == receipt["root_pid"])
            checks.append(receipt["task_success"] is True)
            # Payload allocations are touched after the pre-exec cgroup gate.
            # The verified hierarchical no-swap profile makes the leaf's 48 MiB
            # a resident anonymous-charge floor for this specific fixture.
            checks.append(allocation_floor_holds(receipt["cgroup_memory_charge_peak_bytes"], nodes))
            for parent, child in (("root", "child"), ("child", "grandchild"), ("grandchild", "short_leaf")):
                checks.append(nodes[parent]["spawned_pid"] == nodes[child]["pid"])
            checks.append(all(n["allocated_touched_bytes"] > 0 and n["family_peak_bytes"] is None for n in nodes.values()))
            if mode == "adopted":
                parent_pid = nodes["root"]["parent_before"]
                checks.append(nodes["child"]["parent_after"] == parent_pid)
                checks.append(nodes["grandchild"]["parent_after"] == parent_pid)
                checks.append(nodes["short_leaf"]["begin_monotonic_ns"] > nodes["root"]["end_monotonic_ns"])
                checks.append({w["pid"] for w in waits} == {nodes[r]["pid"] for r in ("root", "child", "grandchild")})
            else:
                checks.append({w["pid"] for w in waits} == {nodes["root"]["pid"]})
            findings[mode] = {"leaf_lifetime_seconds": (nodes["short_leaf"]["end_monotonic_ns"] - nodes["short_leaf"]["begin_monotonic_ns"]) / 1e9}
        elif mode == "nonzero":
            checks.extend([receipt["root_exit_code"] == 3, receipt["task_success"] is False])
        else:
            checks.extend([receipt["timed_out"] is True, receipt["root_exit_code"] == -9,
                           "spawned-child" in (campaign / mode / "stdout.log").read_text()])
        findings.setdefault(mode, {}).update({"charge_peak_bytes": receipt["cgroup_memory_charge_peak_bytes"],
                                             "group_cpu_seconds": receipt["cgroup_cpu_usage_seconds"]})
    return {"passed": all(checks), "checks": len(checks), "failed": sum(not x for x in checks), "findings": findings,
            "full_family_rss_qualified": False, "energy_qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.run)
    except Exception as error:
        result = {"passed": False, "error": {"type": type(error).__name__, "message": str(error)}}
    (args.run / "INDEPENDENT_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
