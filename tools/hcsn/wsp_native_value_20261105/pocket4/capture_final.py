#!/usr/bin/env python3
"""One final bounded read-only observation; raw audit stdout stays private."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bounded(path, maximum):
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=maximum
        parts=[]
        count=0
        while data:=os.read(fd,min(65536,maximum+1-count)):
            parts.append(data)
            count+=len(data)
            assert count<=maximum
        after=os.fstat(fd)
        fields=("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")
        assert tuple(getattr(before,k) for k in fields)==tuple(getattr(after,k) for k in fields)
        return b"".join(parts)
    finally:
        os.close(fd)


def utc():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser=argparse.ArgumentParser()
    for name in ["audit","sanitizer","output"]:
        parser.add_argument("--"+name,type=Path,required=True)
    for name in ["audit-sha256","sanitizer-sha256"]:
        parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    start,cpu=time.perf_counter(),time.process_time()
    child_before=resource.getrusage(resource.RUSAGE_CHILDREN)
    os.umask(0o077)
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    receipt={"schema":"hepta.wsp.final_snapshot_capture.v1","started_utc":utc(),
        "driver_sha256":sha(Path(__file__).read_bytes()),"status":"STARTED",
        "selection":"Actual active trainer MainPID --config argument, then the unchanged strict audit rechecks effective service and live process identity",
        "raw_audit_stdout_published":False,"live_state_mutated":False,"broker_queries_sent":0,"orders_sent":0,
        "model_forward_executed":False,"training_started":False,
        "scope":"One final bounded read-only delta observation; no new efficacy qualification"}
    phase="source_identity"
    try:
        assert sha(bounded(args.audit,65536))==args.audit_sha256
        assert sha(bounded(args.sanitizer,65536))==args.sanitizer_sha256
        receipt["audit_source_sha256"]=args.audit_sha256
        receipt["sanitizer_source_sha256"]=args.sanitizer_sha256
        phase="select_active_guardian"
        selected=subprocess.run(["systemctl","--user","show","heptatrader-laya-trainer.service",
            "--property=MainPID","--value"],capture_output=True,text=True,timeout=6)
        assert selected.returncode==0
        pid=int(selected.stdout.strip())
        assert pid>0
        with (Path("/proc")/str(pid)/"cmdline").open("rb") as stream:
            command=stream.read(16385)
        assert len(command)<=16384
        parts=command.split(b"\0")
        positions=[i for i,x in enumerate(parts) if x==b"--config"]
        assert len(positions)==1 and positions[0]+1<len(parts)
        guardian=Path(os.fsdecode(parts[positions[0]+1]))
        observed_config_root=Path.home()/".config"/"heptatrader-laya-resident"
        assert guardian.resolve().is_relative_to(observed_config_root.resolve())
        guardian_sha=sha(bounded(guardian,65536))
        receipt["selected_current_guardian_sha256"]=guardian_sha
        phase="strict_audit"
        private_stdout=args.output/"private_audit_stdout.json"
        private_stderr=args.output/"private_audit_stderr.log"
        with private_stdout.open("xb") as out,private_stderr.open("xb") as err:
            audit=subprocess.run(["python3","-B",str(args.audit),"--guardian-config",str(guardian),
                "--guardian-config-sha256",guardian_sha],stdout=out,stderr=err,timeout=45)
        raw=bounded(private_stdout,1048576)
        receipt["audit_exit_code"]=audit.returncode
        receipt["private_stdout_sha256"]=sha(raw)
        receipt["private_stdout_bytes"]=len(raw)
        receipt["private_stderr_sha256"]=sha(bounded(private_stderr,65536))
        audit_value=json.loads(raw)
        receipt["audit_status"]=audit_value["status"]
        if audit.returncode!=0:
            # The original audit may already contain private step records when a
            # late identity check fails. Publish only this explicit small failure.
            receipt["status"]="STRICT_AUDIT_FAILED_PRESERVED"
            receipt["audit_failure"]={k:audit_value.get(k) for k in ["source_sha256","started_utc","finished_utc","error","cost"]}
        else:
            phase="public_projection"
            projected=subprocess.run(["python3","-B",str(args.sanitizer),"--private-stdout",str(private_stdout),
                "--public-output",str(args.output/"public_snapshot.json")],capture_output=True,text=True,timeout=10)
            receipt["sanitizer_exit_code"]=projected.returncode
            assert projected.returncode==0
            public=bounded(args.output/"public_snapshot.json",65536)
            value=json.loads(public)
            assert value["public_projection"]["original_private_stdout_sha256"]==sha(raw)
            receipt["public_snapshot_sha256"]=sha(public)
            receipt["public_snapshot_bytes"]=len(public)
            receipt["status"]="PASS_FINAL_BOUND_READONLY_SNAPSHOT"
        assert sha(bounded(args.audit,65536))==args.audit_sha256
        assert sha(bounded(args.sanitizer,65536))==args.sanitizer_sha256
    except BaseException as error:
        receipt["status"]="CAPTURE_FAILED_PRESERVED"
        receipt["failure"]={"phase":phase,"type":type(error).__name__}
    child_after=resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt["finished_utc"]=utc()
    receipt["cost"]={"wrapper_wall_seconds":time.perf_counter()-start,
        "wrapper_cpu_seconds":time.process_time()-cpu,
        "owned_child_user_cpu_seconds":child_after.ru_utime-child_before.ru_utime,
        "owned_child_system_cpu_seconds":child_after.ru_stime-child_before.ru_stime,
        "nested_audit_cost_not_additive":True,"dispatch_transfer_and_report_cost_included":False}
    text=json.dumps(receipt,indent=2,sort_keys=True,allow_nan=False)+"\n"
    assert "/home/" not in text and "/Users/" not in text
    (args.output/"capture_receipt.json").write_text(text)
    print(json.dumps({"status":receipt["status"],"capture_receipt_sha256":sha(text.encode()),
        "public_snapshot_sha256":receipt.get("public_snapshot_sha256"),"finished_utc":receipt["finished_utc"]}))
    return 0 if receipt["status"]=="PASS_FINAL_BOUND_READONLY_SNAPSHOT" else 2


if __name__=="__main__":
    raise SystemExit(main())
