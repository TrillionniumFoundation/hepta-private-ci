"""External receipt covering the full pipeline process and waited descendants."""
import argparse
import datetime
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from io_helpers import read, save, sha


parser=argparse.ArgumentParser()
for name in ("science","joint","inputs","protocol","output"):
    parser.add_argument("--"+name,type=Path,required=True)
args=parser.parse_args()
args.output.mkdir(exist_ok=False)
protocol=read(args.protocol)
root=Path(__file__).parent
command=[sys.executable,"-B",str(root/"run_bounded.py")]
for name in ("science","joint","inputs","protocol"):
    command += ["--"+name,str(getattr(args,name))]
command += ["--output",str(args.output/"run")]
started=datetime.datetime.now(datetime.timezone.utc).isoformat()
tick=time.perf_counter()
timed_out=False
with (args.output/"stdout.log").open("wb") as stdout,(args.output/"stderr.log").open("wb") as stderr:
    child=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True)
    while True:
        pid,status,usage=os.wait4(child.pid,os.WNOHANG)
        if pid:
            break
        if time.perf_counter()-tick>protocol["resources"]["total_pipeline_wall_cap"]:
            timed_out=True
            os.killpg(child.pid,signal.SIGKILL)
            _,status,usage=os.wait4(child.pid,0)
            break
        time.sleep(.1)
    child.returncode=os.waitstatus_to_exitcode(status)
cpu=usage.ru_utime+usage.ru_stime
receipt={"schema":"hepta.train-margin-whole-pipeline-receipt.v1","started_utc":started,
         "ended_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"exit_code":child.returncode,
         "timed_out":timed_out,"whole_pipeline_cpu_seconds":cpu,
         "whole_pipeline_user_cpu_seconds":usage.ru_utime,"whole_pipeline_system_cpu_seconds":usage.ru_stime,
         "wall_seconds":time.perf_counter()-tick,"maximum_descendant_rss_bytes":usage.ru_maxrss*1024,
         "cpu_cap_pass":cpu<=protocol["resources"]["total_measured_pipeline_cpu_cap"],
         "pipeline_source_sha256":sha((root/"run_bounded.py").read_bytes()),
         "measurement_source_sha256":sha(Path(__file__).read_bytes()),"protocol_sha256":sha(args.protocol.read_bytes()),
         "scope":"complete pipeline import/startup/final writes and waited producer/verifier descendants; excludes this measurement supervisor startup/publication",
         "descendant_CPU_may_be_lower_bound_if_killed_before_wait":timed_out}
save(args.output/"PROCESS_RECEIPT.json",receipt)
print(receipt,flush=True)
sys.exit(0 if child.returncode==0 and not timed_out and receipt["cpu_cap_pass"] else 1)
