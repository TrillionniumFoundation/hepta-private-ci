"""Measure complete POSIX export/replay workers, including failures and writes."""
import argparse
import datetime
import os
from pathlib import Path
import subprocess
import sys
import time
from bridge_io import read, sha, write


parser = argparse.ArgumentParser()
parser.add_argument("stage", choices=("export", "replay"))
for name in ("science", "joint", "protocol", "output"):
    parser.add_argument("--"+name, type=Path, required=True)
parser.add_argument("--exported", type=Path)
parser.add_argument("--native", type=Path)
args = parser.parse_args()
args.output.mkdir(exist_ok=False)
worker = Path(__file__).with_name("export_graphs.py" if args.stage == "export" else "verify_native.py")
command = [sys.executable, str(worker)]
for name in ("science", "joint", "protocol"):
    command += ["--"+name, str(getattr(args, name).resolve())]
if args.stage == "replay":
    assert args.exported and args.native
    command += ["--exported", str(args.exported.resolve()), "--native", str(args.native.resolve())]
command += ["--output", str((args.output/"run").resolve())]
start, cpu = time.perf_counter(), time.process_time()
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
with (args.output/"stdout.log").open("xb") as out, (args.output/"stderr.log").open("xb") as err:
    child = subprocess.Popen(command, stdout=out, stderr=err)
    _, raw_status, usage = os.wait4(child.pid, 0)
    child.returncode = os.waitstatus_to_exitcode(raw_status)
record = dict(schema="hepta-native-bellman-engineering-process-v1", stage=args.stage,
    started_utc=started, ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), exit_code=child.returncode,
    child_user_cpu_seconds=usage.ru_utime, child_system_cpu_seconds=usage.ru_stime,
    child_total_cpu_seconds=usage.ru_utime+usage.ru_stime,
    child_peak_rss_bytes=usage.ru_maxrss*(1 if sys.platform=="darwin" else 1024),
    controller_measured_cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-start,
    worker_source_sha256=sha(worker.read_bytes()), controller_source_sha256=sha(Path(__file__).read_bytes()),
    protocol_sha256=sha(args.protocol.read_bytes()),
    scope="complete child import/startup/final writes; measured controller interval separate; no scientific requalification")
write(args.output/"PROCESS_RECEIPT.json", record)
print(record, flush=True)
raise SystemExit(0 if child.returncode==0 else 1)
