"""Measure real frozen AV model tasks in the validated single-task CI profile."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from experiments.hcsn_v10_followup_20261101.economics.cgroup_meter import run
from .identity import freeze, sha
from .profile import OwnedProfile, THREAD_ENV, singleton_verified, snapshot


def cost():
    a, b = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return a.ru_utime + a.ru_stime + b.ru_utime + b.ru_stime


def cases(models):
    expected = {(task, family, seed) for task in ("async_av", "av_binding")
                for family in ("history", "gru", "ssm", "filter") for seed in (91101, 91103)}
    if len(models) != 16 or {(m["task"], m["family"], m["seed"]) for m in models} != expected:
        raise RuntimeError("Exactly the sixteen frozen model identities are required")
    ordered = sorted(models, key=lambda m: (m["task"], m["family"], m["seed"]))
    return [{"task": m["task"], "family": m["family"], "seed": m["seed"], "implementation": implementation}
            for m in ordered for implementation in (("expm", "uniformization") if m["family"] == "filter" else ("expm",))]


def execute(item, bundle, out, parent):
    out.mkdir()
    command = [sys.executable, "-m", "experiments.hcsn_v12_followup_20261101.model_runtime.numpy_runtime",
               "--bundle", str(bundle), "--out", str(out / "worker")]
    for key, value in item.items():
        command.extend(["--" + key, str(value)])
    before = snapshot(parent)
    receipt = run(command, out / "meter", parent, 180)
    after = snapshot(parent)
    singleton = singleton_verified(before, after, receipt)
    waited = receipt.get("waited_subtrees", [])
    record = {"case": item, "profile_before": before, "profile_after": after,
              "singleton_profile_verified": singleton,
              "worker_family_rss_peak_bytes": waited[0]["diagnostic_largest_single_process_rss_bytes"] if singleton else None,
              "whole_worker_cpu_seconds": waited[0]["diagnostic_wait4_cpu_seconds"] if singleton else None,
              "cgroup_cpu_seconds": receipt["cgroup_cpu_usage_seconds"],
              "cgroup_charge_peak_bytes": receipt["cgroup_memory_charge_peak_bytes"],
              "enclosing_meter_wall_seconds": receipt["meter_wall_seconds"],
              "device_energy_joules": None,
              "rss_scope": "Only this kernel-enforced one-TID worker family; birth through exit includes pre-join gate/exec bootstrap. Meter and verifier excluded.",
              "timing_scope": "Worker loads sealed prepared AV packets/weights, executes both actual policies and serializes all traces. Media preparation and fitting excluded."}
    (out / "RESOURCE.json").write_text(json.dumps(record, indent=2) + "\n")
    if not singleton:
        raise RuntimeError("Real worker single-task resource profile did not qualify: " + out.name)
    verifier = [sys.executable, "-m", "experiments.hcsn_v12_followup_20261101.model_runtime.verify_runtime",
                "--bundle", str(bundle), "--run", str(out / "worker"),
                "--reference", str(bundle / "FROZEN_REFERENCE.json.gz"), "--out", str(out / "VERIFY.json")]
    started, cpu = time.monotonic(), cost()
    with (out / "VERIFY.log").open("xb") as log:
        checked = subprocess.run(verifier, stdout=log, stderr=subprocess.STDOUT, timeout=60)
    verification_cost = {"exit_code": checked.returncode, "cpu_seconds": cost() - cpu,
                         "wall_seconds": time.monotonic() - started,
                         "scope": "Group-external verification including parent launch/wait and child; not added to model worker CPU."}
    (out / "VERIFY_COST.json").write_text(json.dumps(verification_cost, indent=2) + "\n")
    if checked.returncode:
        return False
    verified = json.loads((out / "VERIFY.json").read_text())
    return verified["status"] == "passed" and verified["actions_classes_requests_fees_exact"] is True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    bundle, out = args.bundle.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    profile, results = OwnedProfile(), []
    started, cpu = time.monotonic(), cost()
    report = {"status": "FAIL", "scientific_adoption_passed": False, "frontend_quality_gate_passed": False,
              "analytic_core_increment_passed": False, "device_energy_joules": None,
              "unavailable_historical_preparation_cpu_seconds": None}
    try:
        for key, value in THREAD_ENV.items():
            os.environ[key] = value
        os.environ["PYTHONHASHSEED"] = "0"
        report["thread_environment"] = {key: os.environ[key] for key in THREAD_ENV}
        manifest = freeze(bundle, out, args.expected_head)
        items = cases(manifest["models"])
        (out / "FROZEN_CASES.json").write_text(json.dumps(items, indent=2) + "\n")
        parent = profile.create()
        profile.save(out)
        for round_name, roster in (("forward", items), ("reverse", list(reversed(items)))):
            round_out = out / round_name
            round_out.mkdir()
            for item in roster:
                name = "-".join(str(item[k]) for k in ("task", "family", "seed", "implementation"))
                passed = execute(item, bundle, round_out / name, parent)
                results.append({"round": round_name, "case": item, "directory": f"{round_name}/{name}",
                                "semantic_conformance_passed": passed})
        checked = subprocess.run([sys.executable, "-m", "experiments.hcsn_v12_followup_20261101.economics.audit",
                                  "--run", str(out)], timeout=60)
        report["independent_audit_exit_code"] = checked.returncode
        report["all_model_resource_and_conformance_passed"] = checked.returncode == 0 and all(r["semantic_conformance_passed"] for r in results)
    except Exception as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        profile.close()
        profile.save(out)
        report["results"] = results
        report["parent_cleanup_verified"] = profile.record["cleanup_verified"]
        if len(results) == 40 and report.get("all_model_resource_and_conformance_passed") and report["parent_cleanup_verified"]:
            report["status"] = "PASS"
        report["enclosing_cpu_seconds_lower_bound"] = cost() - cpu
        report["enclosing_wall_seconds"] = time.monotonic() - started
        report["enclosing_cost_scope"] = "This driver and waited workers/verifiers/auditor from main boundary; initial interpreter imports/setup and final receipt serialization excluded. Nested worker costs already included."
        report["identity_sha256"] = sha(out / "IDENTITY.json") if (out / "IDENTITY.json").exists() else None
        (out / "CAMPAIGN.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
