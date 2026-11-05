"""Complete POSIX child-process receipt, including failed attempts and imports."""
import argparse
import datetime
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from artifact_io import identity, save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wall-limit", type=int, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("child command required")
    args.output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"):
        env[key] = "1"
    start, cpu = time.perf_counter(), time.process_time()
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    timed_out = False
    with (args.output / "stdout.log").open("xb") as stdout, (args.output / "stderr.log").open("xb") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
        def terminate(_signal, _frame):
            nonlocal timed_out
            timed_out = True
            os.killpg(child.pid, signal.SIGKILL)
        signal.signal(signal.SIGALRM, terminate)
        if args.wall_limit:
            signal.alarm(args.wall_limit)
        _, raw_status, usage = os.wait4(child.pid, 0)
        signal.alarm(0)
        child.returncode = os.waitstatus_to_exitcode(raw_status)
    record = dict(schema="hepta-value-edit-complete-process-receipt-v1", command=command,
        started_utc=started, ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        exit_code=child.returncode, controller_timeout=timed_out,
        child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
        child_total_cpu_seconds=usage.ru_utime + usage.ru_stime,
        child_peak_rss_bytes=usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        controller_cpu_seconds=time.process_time() - cpu,
        elapsed_wall_seconds=time.perf_counter() - start, threads_per_numeric_library=1,
        controller_source=identity(Path(__file__)),
        scope="worker startup/imports/final writes included; controller CPU measures only main body after imports and before final receipt write, so controller startup/final-write cost is not measured; scientific caps belong to worker")
    save(args.output / "PROCESS_RECEIPT.json", record)
    print(__import__("json").dumps(record, sort_keys=True), flush=True)
    return 0 if child.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
