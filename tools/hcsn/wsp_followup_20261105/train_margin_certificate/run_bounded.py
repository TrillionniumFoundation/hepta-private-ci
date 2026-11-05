"""Run frozen producer and independent verifier with separate whole-child usage."""
import argparse
import datetime
import os
from pathlib import Path
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
start=time.perf_counter()
receipts=[]
for stage,script in (("producer","run_diagnostic.py"),("verifier","verify_records.py")):
    command=[sys.executable,"-B",str(root/script)]
    for name in ("science","joint","inputs","protocol"):
        command += ["--"+name,str(getattr(args,name))]
    command += ["--output",str(args.output/stage)]
    if stage=="verifier":
        command += ["--run",str(args.output/"producer")]
    began=datetime.datetime.now(datetime.timezone.utc).isoformat()
    tick=time.perf_counter()
    with (args.output/(stage+".stdout.log")).open("wb") as stdout, (args.output/(stage+".stderr.log")).open("wb") as stderr:
        child=subprocess.Popen(command,stdout=stdout,stderr=stderr)
        _,status,usage=os.wait4(child.pid,0)
        child.returncode=os.waitstatus_to_exitcode(status)
    receipt={"stage":stage,"exit_code":child.returncode,"started_utc":began,
             "ended_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "whole_child_cpu_seconds":usage.ru_utime+usage.ru_stime,
             "whole_child_user_cpu_seconds":usage.ru_utime,"whole_child_system_cpu_seconds":usage.ru_stime,
             "whole_child_peak_rss_bytes":usage.ru_maxrss*1024,"wall_seconds":time.perf_counter()-tick,
             "worker_sha256":sha((root/script).read_bytes()),"protocol_sha256":sha(args.protocol.read_bytes()),
             "scope":"complete worker import/startup/final writes/exit; controller measured by outer receipt"}
    save(args.output/(stage+"_PROCESS_RECEIPT.json"),receipt)
    receipts.append(receipt)
    print(stage,child.returncode,receipt["whole_child_cpu_seconds"],flush=True)
save(args.output/"PIPELINE_STATUS.json",{"passed":all(x["exit_code"]==0 for x in receipts),
     "stages":receipts,"wall_seconds_before_final_write":time.perf_counter()-start,
     "no_new_scientific_efficacy":True})
sys.exit(0 if all(x["exit_code"]==0 for x in receipts) else 1)
