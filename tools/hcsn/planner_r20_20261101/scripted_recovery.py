"""Prospective action-coverage controls; no value-policy performance inference."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from . import execution, recovery_checks
from .campaign import ROOT, save, semantic
from .persistence import load
from .planner import BatchOwnedPlanner

HERE = Path(__file__).resolve().parent


def verify_sources():
    manifest = json.loads((HERE / "SCRIPTED_SOURCE_MANIFEST.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed scripted-control source: {name}")
    publication = json.loads((HERE / "SCRIPTED_PUBLICATION.json").read_text())
    if publication["manifest_sha256"] != hashlib.sha256((HERE / "SCRIPTED_SOURCE_MANIFEST.json").read_bytes()).hexdigest():
        raise RuntimeError("Unbound scripted-control publication")


def child(input_path, output_path):
    verify_sources()
    case = json.loads(input_path.read_text())
    pattern = case["pattern"]
    if pattern not in ("wait_read", "refresh_stop"):
        raise ValueError("Unknown public action script")
    class ScriptedPlanner(BatchOwnedPlanner):
        def choose(self, belief, remaining):
            if pattern == "wait_read":
                return {3: "WAIT", 2: "READ", 1: "STOP", 0: "STOP"}[remaining]
            return "REFRESH" if remaining == 3 else "STOP"
    # This is local to the control child. No source, fitted parameter, numerical
    # answer method or resource-campaign process is modified.
    execution.BatchOwnedPlanner = ScriptedPlanner
    recovery_checks.child(input_path, output_path)


def controller(output):
    verify_sources()
    protocol = json.loads((HERE / "SCRIPTED_PROTOCOL.json").read_text())
    training = ROOT / f"tools/hcsn/addressed_decision_r15_20261101/run_01/training/{protocol['fit']}.json.gz"
    law = json.loads(gzip.decompress(training.read_bytes()))["calibration"]["models"]["hx"]["payload"]
    records, process_count = [], 0
    def invoke(folder, case):
        nonlocal process_count
        folder.mkdir(parents=True, exist_ok=True)
        inp, out = folder / "INPUT.json", folder / "OUTPUT.json"
        save(inp, case)
        process = subprocess.run([sys.executable, "-m", __spec__.name, "--child", str(inp), "--output", str(out)],
                                 capture_output=True, text=True)
        process_count += 1
        save(folder / "PROCESS.json", dict(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr))
        return process.returncode, json.loads(out.read_text()) if out.exists() else None
    for pattern in protocol["patterns"]:
        for representation in protocol["representations"]:
            group = output / (pattern + "_" + representation)
            base = dict(law=law, seed=protocol["seed"], domain="ood", variant="r20",
                        representation=representation, pattern=pattern)
            code, reference = invoke(group / "reference", dict(base, checkpoint_path=str(group / "reference/state.json")))
            assert code == 0 and reference["fsync_calls"] == ["file", "directory"] * 6
            expected = ["WAIT", "READ"] if pattern == "wait_read" else ["REFRESH"]
            for q in reference["result"]["queries"]:
                assert [a["action"] for a in q["actions"]] == expected
                expected_fee = .006 * q["dt"] + (.025 if pattern == "wait_read" else .07) * q["price_scale"]
                assert abs(q["fee"] - expected_fee) < 1e-14
            for query in range(6):
                checkpoint = group / f"lost_query_{query}/state.json"
                code, reply = invoke(group / f"lost_query_{query}", dict(base, checkpoint_path=str(checkpoint),
                                      stop_after_query=query, die_before_reply=True))
                assert code == -signal.SIGKILL and reply is None
                committed = load(checkpoint)
                public = [{k: v for k, v in row.items() if k not in ("target", "reward", "utility")}
                          for row in reference["result"]["queries"][:query + 1]]
                assert committed["completed_query"] == query and committed["history"] == public
                code, resumed = invoke(group / f"resume_query_{query}", dict(base,
                    checkpoint_path=str(group / f"resume_query_{query}/state.json"), resume_path=str(checkpoint)))
                assert code == 0 and semantic(resumed["result"]) == semantic(reference["result"])
                assert resumed["fsync_calls"] == ["file", "directory"] * (5 - query)
                records.append(dict(pattern=pattern, representation=representation, query=query,
                    prefix_fee=sum(q["fee"] for q in public), full_fee=sum(q["fee"] for q in reference["result"]["queries"]),
                    public_history_exact=True, cold_continuation_exact=True, lost_reply_sigkill=True))
    save(output / "SUMMARY.json", dict(passed=True, cases=records, process_count=process_count,
         cold_lost_reply_cases=len(records), scope=protocol["scope"], base_source_commit=protocol["base_source_commit"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", type=Path)
    parser.add_argument("--controller", action="store_true")
    args = parser.parse_args()
    if args.child:
        child(args.child, args.output)
    elif args.controller:
        controller(args.output)
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        started = time.perf_counter()
        process = subprocess.Popen([sys.executable, "-m", __spec__.name, "--controller", "--output", str(args.output)])
        _, status, usage = os.wait4(process.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
             complete_child_family_cpu_seconds=usage.ru_utime + usage.ru_stime,
             wall_seconds=time.perf_counter() - started, linux_max_rss_kib=usage.ru_maxrss,
             scope="Independentcontrolcampaignonly; completecontroller+reapedchildren; notpooledwithresource/qualityobservations"))
        raise SystemExit(code)
