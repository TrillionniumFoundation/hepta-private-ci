"""Independent stdlib audit of real model resource receipts and semantic seals."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def audit(directory):
    checks, rows = [], []
    identity = json.loads((directory / "IDENTITY.json").read_text())
    checks.append(identity["checkout_sha"] == identity["expected_head"])
    for item in identity["files"]:
        content = (directory / item["snapshot"]).read_bytes()
        checks.extend([len(content) == item["bytes"], hashlib.sha256(content).hexdigest() == item["sha256"],
                       hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == item["git_blob"]])
    source_hashes = {item["path"]: item["sha256"] for item in identity["files"]}
    meter_hash = source_hashes["experiments/hcsn_v10_followup_20261101/economics/cgroup_meter.py"]
    verifier_hash = source_hashes["experiments/hcsn_v12_followup_20261101/model_runtime/verify_runtime.py"]
    profile = json.loads((directory / "PARENT_PROFILE.json").read_text())
    checks.extend([profile["created"] is True, profile["initial"]["pids_current"] == 0,
                   profile["initial"]["pids_peak"] == 0, profile["initial"]["pids_max"] == 1,
                   profile["initial"]["swap_max"] == 0, {"cpu", "memory", "pids"}.issubset(profile["enabled_controllers"])])
    cases = json.loads((directory / "FROZEN_CASES.json").read_text())
    checks.append(len(cases) == 20)
    expected = {(task, family, seed, implementation) for task in ("async_av", "av_binding")
                for family in ("history", "gru", "ssm", "filter") for seed in (91101, 91103)
                for implementation in (("expm", "uniformization") if family == "filter" else ("expm",))}
    keys = [(item["task"], item["family"], item["seed"], item["implementation"]) for item in cases]
    checks.extend([len(set(keys)) == 20, set(keys) == expected, keys == sorted(expected)])
    total_executions = 0
    previous_release = -1
    for round_name, items in (("forward", cases), ("reverse", list(reversed(cases)))):
        for item in items:
            name = "-".join(str(item[k]) for k in ("task", "family", "seed", "implementation"))
            run = directory / round_name / name
            measured = json.loads((run / "RESOURCE.json").read_text())
            receipt = json.loads((run / "meter/RECEIPT.json").read_text())
            verified = json.loads((run / "VERIFY.json").read_text())
            summary = json.loads((run / "worker/SUMMARY.json").read_text())
            before, after, waits = measured["profile_before"], measured["profile_after"], receipt["waited_subtrees"]
            checks.append(receipt["release_monotonic_ns"] > previous_release)
            previous_release = receipt["release_monotonic_ns"]
            checks.extend([
                measured["case"] == item, measured["singleton_profile_verified"] is True,
                before["inode"] == after["inode"] == profile["inode"],
                before["pids_current"] == after["pids_current"] == 0,
                before["pids_max"] == after["pids_max"] == 1, after["pids_peak"] == 1,
                before["pids_peak"] <= 1, before["pids_events"]["max"] == after["pids_events"]["max"] == 0,
                before["swap_max"] == after["swap_max"] == before["swap_current"] == after["swap_current"] == 0,
                len(waits) == 1, waits[0]["pid"] == receipt["root_pid"], waits[0]["exit_code"] == receipt["root_exit_code"] == 0,
                receipt["measurement_valid"] is True, receipt["cleanup_verified"] is True,
                receipt["root_membership_confirmed_before_release"] is True,
                receipt["empty_group_kill_checked_before_admission"] is True, receipt["payload_released"] is True,
                receipt["all_group_tasks_exited"] is True, receipt["task_success"] is True,
                receipt["status"] == "MEASURED", receipt["group_absent_after_removal"] is True,
                receipt["populated_before_removal"] == 0, receipt["source_sha256"] == meter_hash,
                receipt["source_unchanged"] is True,
                Path(receipt["group_path"]).parent == Path(profile["path"]),
                measured["worker_family_rss_peak_bytes"] == waits[0]["diagnostic_largest_single_process_rss_bytes"] > 0,
                measured["whole_worker_cpu_seconds"] == waits[0]["diagnostic_wait4_cpu_seconds"] > 0,
                measured["cgroup_charge_peak_bytes"] == receipt["cgroup_memory_charge_peak_bytes"] > 0,
                measured["cgroup_cpu_seconds"] == receipt["cgroup_cpu_usage_seconds"] > 0,
                abs(receipt["cgroup_cpu_usage_seconds"] - receipt["cgroup_cpu_stat_at_exit"]["usage_usec"] / 1e6) < 1e-9,
                receipt["device_energy_joules"] is None, measured["device_energy_joules"] is None,
                verified["status"] == "passed", verified["actions_classes_requests_fees_exact"] is True,
                verified["verifier_source_sha256"] == verifier_hash,
                verified["worker_trace_sha256"] == digest(run / "worker/TRACES.jsonl.gz"),
                verified["ci_manifest_sha256"] == identity["bundle_ci_manifest_sha256"],
                verified["rtol"] == 1e-10, verified["atol"] == 1e-12,
                summary["numpy"] == "2.3.5", summary["torch_imported"] is False,
                summary["scientific_admission"] is False, summary["executions"] == verified["executions"],
                summary["implementation"] == item["implementation"],
                all(summary["model"][key] == item[key] for key in ("task", "family", "seed")),
            ])
            total_executions += verified["executions"]
            rows.append({"round": round_name, **item, "episodes": verified["executions"],
                         "rss_bytes": measured["worker_family_rss_peak_bytes"],
                         "charge_bytes": measured["cgroup_charge_peak_bytes"],
                         "worker_cpu_seconds": measured["whole_worker_cpu_seconds"],
                         "cgroup_cpu_seconds": measured["cgroup_cpu_seconds"],
                         "meter_wall_seconds": measured["enclosing_meter_wall_seconds"]})
    checks.append(total_executions == 1440)
    return {"passed": all(checks), "checks": len(checks), "failed": sum(not value for value in checks),
            "workers": len(rows), "episodes": total_executions, "rows": rows,
            "device_energy_joules": None, "scientific_adoption_passed": False,
            "limits": "One host, two fixed orders, warmed/shared page cache. RSS is bounded single-task worker lifetime including birth/bootstrap, not arbitrary deployment family or observer. Charge peak is separately attributed; no cold-memory or adoption ranking."}


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
