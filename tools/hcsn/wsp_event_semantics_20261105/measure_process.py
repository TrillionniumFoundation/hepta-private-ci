"""Create-only whole-child-process cost receipt with bounded execution."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=190.)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("child command required")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start, parent_cpu = time.perf_counter(), time.process_time()
    began = datetime.datetime.now(datetime.timezone.utc).isoformat()
    timed_out = False
    with (out / "stdout.txt").open("xb") as stdout, (out / "stderr.txt").open("xb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = dict(schema="hepta-ctmc-semantic-whole-child-cost-v1", command=command,
        started_utc=began, ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        child_user_cpu_seconds=after.ru_utime-before.ru_utime,
        child_system_cpu_seconds=after.ru_stime-before.ru_stime,
        child_total_cpu_seconds=(after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime),
        child_peak_rss_bytes=after.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        wall_seconds=time.perf_counter()-start, controller_partial_cpu_seconds=time.process_time()-parent_cpu,
        exit_code=code, timed_out=timed_out,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope="Whole child including imports and final writes; controller imports/final receipt writes, editor, prior training, energy and production costs excluded/unknown.")
    (out / "PROCESS_RECEIPT.json").write_text(json.dumps(receipt, sort_keys=True, indent=2)+"\n")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    raise SystemExit(0 if code == 0 else 1)


if __name__ == "__main__":
    main()
