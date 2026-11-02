"""Independent stdlib coverage/identity audit of downloaded V12 kernel receipts.

Runs only on actual CI artifacts, never synthetic resource fixtures. It checks
the bounded trusted one-TID profile; it cannot certify arbitrary process trees,
page-ownership-independent memory, external migration exclusion, or energy.
"""

import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory, expected_head):
    count, failed = 0, []

    def check(ok, label):
        nonlocal count
        count += 1
        if not ok and len(failed) < 30:
            failed.append(label)

    campaign = json.loads((directory / "CAMPAIGN.json").read_text())
    identity = json.loads((directory / "IDENTITY.json").read_text())
    parent = json.loads((directory / "PARENT_PROFILE.json").read_text())
    check(identity["checkout_sha"] == identity["expected_head"] == expected_head, "actual exact event-head identity")
    hashes = {}
    for record in identity["files"]:
        path = directory / record["snapshot"]
        content = path.read_bytes()
        check(len(content) == record["bytes"] and sha(path) == record["sha256"], "captured source/input snapshot SHA")
        check(hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == record["git_blob"], "captured snapshot Git blob identity")
        hashes[record["path"]] = record["sha256"]
    check(campaign["status"] == "PASS" and campaign["parent_cleanup_verified"] is True, "whole campaign passed and parent removed")
    check(parent["created"] is True and parent["cleanup_verified"] is True, "owned parent lifecycle")
    check(parent["initial"]["pids_current"] == parent["final"]["pids_current"] == 0, "empty parent before/after")
    check(parent["initial"]["pids_peak"] == 0 and parent["final"]["pids_peak"] == 1, "fresh parent peak and one TID maximum")
    check(parent["initial"]["swap_max"] == parent["final"]["swap_max"] == parent["final"]["swap_current"] == 0, "no-swap parent profile")
    expected = {(task, family, seed, implementation) for task in ("async_av", "av_binding")
        for family in ("history", "gru", "ssm", "filter") for seed in (91101, 91103)
        for implementation in (("expm", "uniformization") if family == "filter" else ("expm",))}
    observed = set()
    rows, episodes = [], 0
    for run in campaign["results"]:
        item, round_name = run["case"], run["round"]
        key = tuple(item[k] for k in ("task", "family", "seed", "implementation"))
        check(round_name in ("forward", "reverse") and key in expected, "declared model/round roster")
        check((round_name, key) not in observed, "unique model kernel measurement")
        observed.add((round_name, key))
        base = directory / run["directory"]
        resource = json.loads((base / "RESOURCE.json").read_text())
        meter = json.loads((base / "meter/RECEIPT.json").read_text())
        verified = json.loads((base / "VERIFY.json").read_text())
        summary = json.loads((base / "worker/SUMMARY.json").read_text())
        before, after = resource["profile_before"], resource["profile_after"]
        check(before["inode"] == after["inode"] == parent["inode"], "same owned kernel parent inode")
        check(before["pids_current"] == after["pids_current"] == 0 and before["pids_max"] == after["pids_max"] == 1, "empty/one-TID parent bound")
        check(before["pids_peak"] <= 1 and after["pids_peak"] == 1, "kernel observed one TID peak")
        check(before["pids_events"]["max"] == after["pids_events"]["max"] == 0, "no denied process/thread creation")
        check(before["swap_max"] == after["swap_max"] == before["swap_current"] == after["swap_current"] == 0, "no-swap worker bound")
        check(meter["measurement_valid"] and meter["task_success"] and meter["cleanup_verified"] and meter["all_group_tasks_exited"], "valid successful drained task group")
        check(meter["root_membership_confirmed_before_release"] and meter["group_absent_after_removal"], "gated admission and removed task subgroup")
        waits = meter["waited_subtrees"]
        check(len(waits) == 1 and waits[0]["pid"] == meter["root_pid"] and waits[0]["exit_code"] == meter["root_exit_code"] == 0, "exact single waited root process")
        check(resource["worker_family_rss_peak_bytes"] == waits[0]["diagnostic_largest_single_process_rss_bytes"] > 0, "singleton RSS highwater binding")
        check(resource["whole_worker_cpu_seconds"] == waits[0]["diagnostic_wait4_cpu_seconds"] > 0, "whole worker CPU binding")
        check(resource["cgroup_charge_peak_bytes"] == meter["cgroup_memory_charge_peak_bytes"] > 0, "separate kernel charge peak")
        check(meter["source_sha256"] == hashes["experiments/hcsn_v10_followup_20261101/economics/cgroup_meter.py"], "actual meter source identity")
        check(verified["verifier_source_sha256"] == hashes["experiments/hcsn_v12_followup_20261101/model_runtime/verify_runtime.py"], "actual verifier source identity")
        check(verified["worker_trace_sha256"] == sha(base / "worker/TRACES.jsonl.gz"), "verifier binds actual model trace")
        check(verified["ci_manifest_sha256"] == identity["bundle_ci_manifest_sha256"], "verifier binds exact CI model/input manifest")
        check(verified["status"] == "passed" and verified["actions_classes_requests_fees_exact"] is True, "actual semantic verifier success")
        check((verified["rtol"], verified["atol"]) == (1e-10, 1e-12), "unchanged numeric gate")
        check(summary["torch_imported"] is False and summary["numpy"] == "2.3.5", "actual no-Torch pinned worker")
        expected_episodes = 24 if item["task"] == "async_av" else 48
        check(summary["executions"] == verified["executions"] == expected_episodes, "all actual task objects and both policies")
        check(resource["device_energy_joules"] is None and meter["device_energy_joules"] is None, "unavailable physical energy retained")
        episodes += verified["executions"]
        rows.append({"round": round_name, **item, "rss_peak_bytes": resource["worker_family_rss_peak_bytes"],
                     "worker_cpu_seconds": resource["whole_worker_cpu_seconds"], "episodes": expected_episodes})
    check(observed == {(name, case) for name in ("forward", "reverse") for case in expected}, "all forty model/round identities covered")
    check(episodes == 1440, "all 1440 frozen model episodes")
    return {"schema": "hcsn-v12-independent-ci-singleton-review.v1", "checks": count,
            "all_checks_passed": not failed, "failed_examples": failed, "checkout_sha": expected_head,
            "workers": len(rows), "episodes": episodes, "rows": rows,
            "limits": "Trusted singleton profile only; shared/warmed host and pre-read artifacts; no arbitrary family, production, cold-memory superiority, energy or scientific admission"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run, args.expected_head)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
