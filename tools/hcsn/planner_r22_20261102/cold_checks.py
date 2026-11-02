"""Cold continuation with the shared scalar validation fastpath and all I/O guards."""

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

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..planner_r20_20261101 import execution as old, recovery_checks
from ..planner_r20_20261101.campaign import ROOT, save, semantic
from ..planner_r20_20261101.persistence import load
from ..support_retention_r16_20261101.compression import BlockLaw
from .memory import BlockLaw as NewBlockLaw
from . import execution as new

HERE = Path(__file__).resolve().parent


def verify_sources():
    for name, digest in json.loads((HERE / "SOURCE_MANIFEST.json").read_text())["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed R22 input: {name}")
    receipt = json.loads((HERE / "PUBLICATION.json").read_text())
    if receipt["manifest_sha256"] != hashlib.sha256((HERE / "SOURCE_MANIFEST.json").read_bytes()).hexdigest():
        raise RuntimeError("Unbound R22 publication")


def policy_class(base, pattern):
    if pattern == "value":
        return base
    if pattern not in ("wait_read", "refresh_stop"):
        raise ValueError("Unknown declared control policy")
    class ScriptedPlanner(base):
        def choose(self, belief, remaining):
            if pattern == "wait_read":
                return {3: "WAIT", 2: "READ", 1: "STOP", 0: "STOP"}[remaining]
            return "REFRESH" if remaining == 3 else "STOP"
    return ScriptedPlanner


def child(input_path, output_path):
    verify_sources()
    case = json.loads(input_path.read_text())
    new.BatchOwnedPlanner = policy_class(new.BatchOwnedPlanner, case["pattern"])
    recovery_checks.execute = new.execute
    recovery_checks.BlockLaw = NewBlockLaw
    recovery_checks.child(input_path, output_path)


def controller(output):
    verify_sources()
    protocol = json.loads((HERE / "COLD_PROTOCOL.json").read_text())
    training = ROOT / f"tools/hcsn/addressed_decision_r15_20261101/run_01/training/{protocol['fit']}.json.gz"
    law_payload = json.loads(gzip.decompress(training.read_bytes()))["calibration"]["models"]["hx"]["payload"]
    owner = Law()
    records, processes = [], 0
    def invoke(folder, case):
        nonlocal processes
        folder.mkdir(parents=True, exist_ok=True)
        inp, out = folder / "INPUT.json", folder / "OUTPUT.json"
        save(inp, case)
        process = subprocess.run([sys.executable, "-m", __spec__.name, "--child", str(inp), "--output", str(out)],
                                 capture_output=True, text=True)
        processes += 1
        save(folder / "PROCESS.json", dict(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr))
        return process.returncode, json.loads(out.read_text()) if out.exists() else None
    for pattern in protocol["patterns"]:
        for representation in protocol["representations"]:
            group = output / (pattern + "_" + representation)
            base = dict(law=law_payload, seed=protocol["seed"], domain="ood", variant="r20",
                        representation=representation, pattern=pattern)
            code, reference = invoke(group / "reference", dict(base, checkpoint_path=str(group / "reference/state.json")))
            assert code == 0 and reference["fsync_calls"] == ["file", "directory"] * 6
            prior_class = old.BatchOwnedPlanner
            old.BatchOwnedPlanner = policy_class(prior_class, pattern)
            try:
                legacy = old.execute(BlockLaw.from_payload(law_payload), make_episode(owner, protocol["seed"], "ood"),
                                     "r20", representation, group / "legacy_state.json", KernelCache())
            finally:
                old.BatchOwnedPlanner = prior_class
            assert semantic(legacy) == semantic(reference["result"])
            save(group / "LEGACY_REFERENCE.json", legacy)
            if pattern != "value":
                expected = ["WAIT", "READ"] if pattern == "wait_read" else ["REFRESH"]
                assert all([a["action"] for a in q["actions"]] == expected for q in reference["result"]["queries"])
            for query in range(6):
                checkpoint = group / f"lost_query_{query}/state.json"
                code, reply = invoke(group / f"lost_query_{query}", dict(base, checkpoint_path=str(checkpoint),
                                      stop_after_query=query, die_before_reply=True))
                assert code == -signal.SIGKILL and reply is None
                committed = load(checkpoint)
                public = [{k: v for k, v in q.items() if k not in ("target", "reward", "utility")}
                          for q in reference["result"]["queries"][:query + 1]]
                assert committed["completed_query"] == query and committed["history"] == public
                code, resumed = invoke(group / f"resume_query_{query}", dict(base,
                    checkpoint_path=str(group / f"resume_query_{query}/state.json"), resume_path=str(checkpoint)))
                assert code == 0 and semantic(resumed["result"]) == semantic(reference["result"])
                assert resumed["fsync_calls"] == ["file", "directory"] * (5 - query)
                records.append(dict(pattern=pattern, representation=representation, query=query,
                                    prefix_fee=sum(q["fee"] for q in public), exact_history=True,
                                    exact_legacy_output=True, exact_cold_continuation=True, lost_reply_sigkill=True))
    save(output / "SUMMARY.json", dict(passed=True, cases=records, process_count=processes,
         cold_lost_reply_cases=len(records), legacy_semantic_references=9,
         scope="Freshgenerated-statecorrectnessonly:3memoryschemas×3policies×6querycuts; notresource/efficacyqualification, nomidqueryexternal-effect/power-lossclaim"))


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
             scope="Completecoldcontroller+reapedchildren+legacyreferences; notperformanceconfirmation"))
        raise SystemExit(code)
