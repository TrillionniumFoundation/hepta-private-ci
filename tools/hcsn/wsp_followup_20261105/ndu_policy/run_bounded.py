"""POSIX outer-process receipt, including imports, final writes and failed runs."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
for name in ("joint", "inputs", "history", "protocol", "output"):
    parser.add_argument("--" + name, type=Path, required=True)
args = parser.parse_args()
start, cpu = time.perf_counter(), time.process_time()
args.output.mkdir(exist_ok=False)
command = [sys.executable, str(Path(__file__).with_name("run_experiment.py"))]
for name in ("joint", "inputs", "history", "protocol"):
    command += ["--" + name, str(getattr(args, name).resolve())]
command += ["--output", str((args.output / "run").resolve())]
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
with (args.output / "stdout.log").open("xb") as stdout, (args.output / "stderr.log").open("xb") as stderr:
    child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
    _, raw_status, usage = os.wait4(child.pid, 0)
    child.returncode = os.waitstatus_to_exitcode(raw_status)
record = dict(schema="hepta-own-bellman-complete-process-receipt-v1", started_utc=started,
              ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), exit_code=child.returncode,
              child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
              child_total_cpu_seconds=usage.ru_utime+usage.ru_stime,
              child_peak_rss_bytes=usage.ru_maxrss*(1 if sys.platform == "darwin" else 1024),
              controller_cpu_seconds=time.process_time()-cpu, elapsed_wall_seconds=time.perf_counter()-start,
              protocol_sha256=hashlib.sha256(args.protocol.read_bytes()).hexdigest(),
              worker_source_sha256=hashlib.sha256(Path(__file__).with_name("run_experiment.py").read_bytes()).hexdigest(),
              controller_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              scope="includes worker import/startup and final artifact writes; controller CPU separate, not duplicated")
(args.output / "PROCESS_RECEIPT.json").write_text(json.dumps(record, sort_keys=True, indent=2)+"\n")
print(json.dumps(record, sort_keys=True), flush=True)
sys.exit(0 if child.returncode == 0 else 1)
