#!/usr/bin/env python3
"""Execute exactly one isolated probe under an enclosing resource-limited unit."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time


def child_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (180, 190))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))


def verify_enclosing_limits():
    """Fail closed unless the requested v2 cgroup budgets actually enclose us."""
    memberships = [line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
                   if line.startswith("0::")]
    if len(memberships) != 1 or ".." in Path(memberships[0]).parts:
        raise ValueError("CGROUP_MEMBERSHIP_UNAVAILABLE")
    group = Path("/sys/fs/cgroup") / memberships[0].lstrip("/")
    memory = int((group / "memory.max").read_text().strip())
    tasks = int((group / "pids.max").read_text().strip())
    quota, period = map(int, (group / "cpu.max").read_text().split())
    if not (0 < memory <= 3 * 1024**3 and 0 < tasks <= 32 and 0 < quota * 2 <= period):
        raise ValueError("CGROUP_BUDGET_NOT_ENFORCED")
    return {"memory_max_bytes": memory, "pids_max": tasks, "cpu_quota_us": quota,
            "cpu_period_us": period, "cpu_core_fraction": quota / period,
            "membership_sha256": hashlib.sha256(memberships[0].encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root
    run = root / "execution"
    run.mkdir(exist_ok=False)
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
               USE_TF="0", PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="",
               HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    began, cpu = time.perf_counter(), time.process_time()
    receipt = {"schema": "hepta.wsp.full_encoder.supervisor.v1",
               "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "child_cpu_soft_seconds": 180, "child_cpu_hard_seconds": 190,
               "child_wall_timeout_seconds": 420, "gpu_execution_permitted": False,
               "cgroup_memory_max_bytes_expected": 3 * 1024**3,
               "enclosing_cpu_quota_expected": "50%", "status": "STARTED"}
    with (run / "stdout.log").open("xb") as out, (run / "stderr.log").open("xb") as err:
        try:
            receipt["cgroup_limits_observed"] = verify_enclosing_limits()
            child = subprocess.run([args.python, "-B", str(root / "probe_full_encoder.py"),
                                    "--output", str(run / "probe")], stdout=out, stderr=err,
                                   env=env, timeout=420, preexec_fn=child_limits)
            receipt.update(status="COMPLETED", child_exit_code=child.returncode)
        except subprocess.TimeoutExpired:
            receipt.update(status="TIMEOUT_PRESERVED", child_exit_code=None)
        except Exception as error:
            # Retain a bounded, path-free receipt when isolation cannot be verified.
            receipt.update(status="FAILED_BEFORE_OR_DURING_LAUNCH", child_exit_code=None,
                           failure_type=type(error).__name__)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt.update(finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   child_user_cpu_seconds=after.ru_utime - before.ru_utime,
                   child_system_cpu_seconds=after.ru_stime - before.ru_stime,
                   elapsed_wall_seconds=time.perf_counter() - began,
                   supervisor_cpu_seconds=time.process_time() - cpu,
                   complete_child_peak_rss_bytes=after.ru_maxrss * 1024,
                   nested_worker_timings_must_not_be_added=True)
    receipt["files"] = {name: {"sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
                              "bytes": (root / name).stat().st_size}
                        for name in ("probe_full_encoder.py", "head_probe_helpers.py", "supervise_full_encoder.py")}
    receipt["streams"] = {name: {"sha256": hashlib.sha256((run / name).read_bytes()).hexdigest(),
                                "bytes": (run / name).stat().st_size}
                          for name in ("stdout.log", "stderr.log")}
    (run / "SUPERVISOR_RECEIPT.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt))
    return 0 if receipt.get("child_exit_code") == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
