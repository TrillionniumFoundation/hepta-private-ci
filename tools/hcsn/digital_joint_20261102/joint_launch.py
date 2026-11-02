"""Bounded parallel fit masters with complete wait4 tree and launcher ledgers."""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


def write(path, value):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-commit", required=True); parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 3 or len(args.source_commit) != 40 or set(args.source_commit)-set("0123456789abcdef"):
        raise ValueError("one to three masters and a published source commit required")
    protocol = json.loads(Path(__file__).with_name("joint_protocol.json").read_text())
    if protocol["status"] != "frozen": raise ValueError("frozen protocol required")
    args.out.mkdir(parents=True, exist_ok=False)
    waiting = list(protocol["fits"]); active, completed = {}, []
    wall = time.perf_counter(); failure, unexpected = False, None
    write(args.out/"LAUNCH_STARTED.json", dict(source_commit=args.source_commit, fits=waiting,
          concurrency=args.concurrency, launcher_source_sha256=__import__("hashlib").sha256(Path(__file__).read_bytes()).hexdigest()))
    try:
        while waiting or active:
            while waiting and len(active) < args.concurrency and not failure:
                fit = waiting.pop(0)
                stdout = (args.out/f"master_{fit}.stdout.log").open("x")
                stderr = (args.out/f"master_{fit}.stderr.log").open("x")
                command = [sys.executable, "-u", "-m", "tools.hcsn.digital_joint_20261102.joint_campaign", "fit", "--fit", str(fit), "--out", str(args.out/f"fit_{fit}"), "--source-commit", args.source_commit]
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                active[process.pid] = dict(process=process, fit=fit, stdout=stdout, stderr=stderr, wall_start=time.perf_counter(), command=command)
            pid, status, usage = os.wait4(-1, os.WNOHANG) if active else (0,0,None)
            if not pid:
                if not active: break
                time.sleep(.02); continue
            job = active.pop(pid); job["process"].returncode = os.waitstatus_to_exitcode(status)
            job["stdout"].close(); job["stderr"].close()
            record = dict(schema="joint-complete-master-tree-v1", fit=job["fit"], command=job["command"], returncode=job["process"].returncode,
              tree_user_cpu_seconds=usage.ru_utime, tree_system_cpu_seconds=usage.ru_stime,
              tree_cpu_seconds=usage.ru_utime+usage.ru_stime, wall_seconds=time.perf_counter()-job["wall_start"], maximum_resident_kib=usage.ru_maxrss,
              scope="wait4 complete master plus its waited descendants; overlaps shared/worker/monitor ledgers, never add them again")
            write(args.out/f"master_{job['fit']}_RECEIPT.json", record); completed.append(record)
            failure = failure or record["returncode"] != 0
            print(json.dumps(dict(stage="master_complete", fit=job["fit"], returncode=record["returncode"], tree_cpu_seconds=record["tree_cpu_seconds"])), flush=True)
    except BaseException as error:
        unexpected = dict(type=type(error).__name__, message=str(error)); failure = True
        for pid, job in list(active.items()):
            _, status, usage = os.wait4(pid, 0)
            job["stdout"].close(); job["stderr"].close()
            record = dict(fit=job["fit"], returncode=os.waitstatus_to_exitcode(status), tree_user_cpu_seconds=usage.ru_utime,
                          tree_system_cpu_seconds=usage.ru_stime, tree_cpu_seconds=usage.ru_utime+usage.ru_stime,
                          wall_seconds=time.perf_counter()-job["wall_start"], launcher_exception=unexpected)
            write(args.out/f"master_{job['fit']}_RECEIPT.json", record); completed.append(record)
    finally:
        own = resource.getrusage(resource.RUSAGE_SELF)
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = dict(schema="joint-complete-launch-v1", passed=not failure and len(completed)==len(protocol["fits"]), source_commit=args.source_commit,
          completed_masters=completed, not_launched_fits=waiting, exception=unexpected, wall_seconds=time.perf_counter()-wall,
          master_tree_cpu_seconds=sum(r["tree_cpu_seconds"] for r in completed), launcher_self_user_cpu_seconds=own.ru_utime,
          launcher_self_system_cpu_seconds=own.ru_stime, launcher_self_cpu_seconds=own.ru_utime+own.ru_stime,
          waited_child_cpu_crosscheck=child.ru_utime+child.ru_stime,
          observed_tree_plus_launcher_cpu_seconds=sum(r["tree_cpu_seconds"] for r in completed)+own.ru_utime+own.ru_stime,
          scope="includes master launch/import/monitor/guard rejection/exit and all waited workers/preparation; final receipt serialization and launcher exit excluded, no lifecycle/energy claim")
        write(args.out/"LAUNCH_COMPLETE.json", result)
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__": main()
