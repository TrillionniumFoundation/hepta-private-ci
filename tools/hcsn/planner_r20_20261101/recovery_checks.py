"""Actual cold-process query recovery, syscall probes and atomic-write kill windows."""

import argparse
import gzip
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..support_retention_r16_20261101.compression import BlockLaw
from .campaign import save, semantic
from .execution import execute
from .persistence import load, persist

HERE = Path(__file__).resolve().parent


def child(input_path, output_path):
    case = json.loads(input_path.read_text())
    if "persist_phase" in case:
        def hook(phase):
            if phase == case["persist_phase"]:
                os.kill(os.getpid(), signal.SIGKILL)
        persist(Path(case["checkpoint_path"]), dict(schema="hcsn-r20-query-checkpoint-v1", value=2), hook)
        raise RuntimeError("Expected kill phase did not execute")
    law = BlockLaw.from_payload(case["law"])
    episode = make_episode(Law(), case["seed"], case["domain"])
    counts, original = [], os.fsync
    def observed(fd):
        mode = os.fstat(fd).st_mode
        counts.append("directory" if stat.S_ISDIR(mode) else "file")
        return original(fd)
    os.fsync = observed
    try:
        row = execute(law, episode, case["variant"], case["representation"], Path(case["checkpoint_path"]),
                      KernelCache(), Path(case["resume_path"]) if case.get("resume_path") else None,
                      case.get("stop_after_query"))
    finally:
        os.fsync = original
    if case.get("die_before_reply"):
        os.kill(os.getpid(), signal.SIGKILL)
    save(output_path, dict(result=row, fsync_calls=counts))


def controller(output):
    started = time.process_time()
    training = HERE.parent / "addressed_decision_r15_20261101/run_01/training/151101.json.gz"
    models = json.loads(gzip.decompress(training.read_bytes()))["calibration"]["models"]
    law = models["hx"]["payload"]
    records, process_count = [], 0
    def invoke(folder, case):
        nonlocal process_count
        folder.mkdir(parents=True, exist_ok=True)
        inp, out = folder / "INPUT.json", folder / "OUTPUT.json"
        save(inp, case)
        result = subprocess.run([sys.executable, "-m", __spec__.name, "--child", str(inp), "--output", str(out)],
                                capture_output=True, text=True)
        process_count += 1
        save(folder / "PROCESS.json", dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
        return result.returncode, json.loads(out.read_text()) if out.exists() else None
    for variant in ("baseline", "r18", "r19", "r20"):
        for representation in ("full", "anchored"):
            group = output / f"{variant}_{representation}"
            base = dict(law=law, seed=2000999101, domain="ood", variant=variant, representation=representation)
            code, reference = invoke(group / "reference", dict(base, checkpoint_path=str(group / "reference/state.json")))
            assert code == 0
            assert reference["fsync_calls"] == ["file", "directory"] * 6
            for query in range(6):
                checkpoint = group / f"lost_query_{query}/state.json"
                code, reply = invoke(group / f"lost_query_{query}", dict(base, checkpoint_path=str(checkpoint),
                                      stop_after_query=query, die_before_reply=True))
                assert code == -signal.SIGKILL and reply is None
                committed = load(checkpoint)
                assert committed["completed_query"] == query
                assert len(committed["history"]) == query + 1
                code, resumed = invoke(group / f"resume_query_{query}", dict(base,
                    checkpoint_path=str(group / f"resume_query_{query}/state.json"), resume_path=str(checkpoint)))
                assert code == 0
                assert semantic(resumed["result"]) == semantic(reference["result"])
                assert resumed["fsync_calls"] == ["file", "directory"] * (5 - query)
                records.append(dict(variant=variant, representation=representation, completed_query=query,
                                    lost_reply_sigkill=True, cold_resume_exact=True,
                                    resumed_file_fsyncs=5 - query, resumed_directory_fsyncs=5 - query))
    windows = []
    for phase in ("file_fsync", "replace", "directory_fsync"):
        folder = output / ("atomic_" + phase)
        folder.mkdir(parents=True)
        path = folder / "state.json"
        persist(path, dict(schema="hcsn-r20-query-checkpoint-v1", value=1))
        code, reply = invoke(folder / "killed", dict(persist_phase=phase, checkpoint_path=str(path)))
        assert code == -signal.SIGKILL and reply is None
        recovered = load(path)
        assert recovered["value"] == (1 if phase == "file_fsync" else 2)
        persist(path, dict(schema="hcsn-r20-query-checkpoint-v1", value=3))
        assert load(path)["value"] == 3
        windows.append(dict(phase=phase, sigkill=True, recovered=recovered, retry_value=3))
    save(output / "SUMMARY.json", dict(passed=True, cases=records, atomic_windows=windows,
         process_count=process_count, lost_reply_cases=len(records),
         controller_body_cpu_seconds=time.process_time() - started,
         scope="48 real SIGKILL-aftercommit/lostreply cases, fresh process resumes, 8 six-query syscallprobes,3 atomic process-death windows. TrustedlocalLinuxsinglewriter; no midqueryexternal-effect,power-loss,networkorconcurrent-ownerqualification."))


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
        wall = time.perf_counter()
        process = subprocess.Popen([sys.executable, "-m", __spec__.name, "--controller", "--output", str(args.output)])
        _, status, usage = os.wait4(process.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
             complete_child_family_cpu_seconds=usage.ru_utime + usage.ru_stime,
             wall_seconds=time.perf_counter() - wall, linux_max_rss_kib=usage.ru_maxrss,
             scope="Wait4outercontrollerandreapeddescendants; nestedcontrollerbodyandchildprobeclocksarenotaddedagain. No superparentstartup cost."))
        raise SystemExit(code)
