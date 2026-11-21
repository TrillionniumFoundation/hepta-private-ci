"""One-shot scientific or read-only-review child, with exact wait4 costs."""
from pathlib import Path
import datetime,hashlib,json,os,resource,signal,subprocess,sys,time
root=Path(__file__).resolve().parent
protocol=json.loads((root/"PROTOCOL_FROZEN.json").read_text())
review=sys.argv[1:]==["--review"]
if sys.argv[1:] and not review:raise ValueError("invalid one-shot mode")
label="independent_reader" if review else "attempt001"
command=([sys.executable,"-B",str(root/"verify_records.py"),"--protocol",str(root/"PROTOCOL_FROZEN.json"),
          "--protocol-sha256",hashlib.sha256((root/"PROTOCOL_FROZEN.json").read_bytes()).hexdigest(),
          "--output",protocol["output_absolute"]] if review else
         [sys.executable,"-B",str(root/"experiment.py"),"--protocol",str(root/"PROTOCOL_FROZEN.json"),
          "--output",protocol["output_absolute"]])
env=os.environ.copy();env["HEPTA_WSP_INPUT_ROOT"]=protocol["input_root_absolute"]
for key in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):env[key]="1"
def cpu_limit():resource.setrlimit(resource.RLIMIT_CPU,(7,8) if review else (250,261))
started=time.perf_counter();cpu=time.process_time();killed=False
stdout=root/f"{label}.stdout.log";stderr=root/f"{label}.stderr.log"
with stdout.open("xb") as so,stderr.open("xb") as se:
    process=subprocess.Popen(command,cwd=root,env=env,stdout=so,stderr=se,
                             preexec_fn=cpu_limit,start_new_session=True)
    def deadline(*unused):
        global killed
        killed=True;os.killpg(process.pid,signal.SIGKILL)
    signal.signal(signal.SIGALRM,deadline);signal.alarm(60 if review else 560)
    print(json.dumps(dict(started_pid=process.pid,mode=label,output=protocol["output_absolute"])),flush=True)
    pid,status,usage=os.wait4(process.pid,0);signal.alarm(0)
    process.returncode=os.waitstatus_to_exitcode(status)
receipt=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),pid=pid,exit_code=process.returncode,
    child_CPU_seconds=usage.ru_utime+usage.ru_stime,child_user_seconds=usage.ru_utime,
    child_system_seconds=usage.ru_stime,child_peak_RSS_bytes=usage.ru_maxrss*1024,
    enclosed_wall_seconds=time.perf_counter()-started,supervisor_CPU_seconds=time.process_time()-cpu,
    command=command,mode=label,automatic_retry=False,external_wall_kill=killed,
    protocol_sha256=hashlib.sha256((root/"PROTOCOL_FROZEN.json").read_bytes()).hexdigest(),
    supervisor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    stdout_sha256=hashlib.sha256(stdout.read_bytes()).hexdigest(),
    stderr_sha256=hashlib.sha256(stderr.read_bytes()).hexdigest())
with (root/f"{label}_supervisor.json").open("x") as f:json.dump(receipt,f,indent=2)
if review:
    # Preserve the independent reader's complete single JSON report verbatim.
    with (root/"INDEPENDENT_REVIEW.json").open("xb") as f:f.write(stdout.read_bytes())
print(json.dumps(receipt),flush=True);sys.exit(process.returncode)
