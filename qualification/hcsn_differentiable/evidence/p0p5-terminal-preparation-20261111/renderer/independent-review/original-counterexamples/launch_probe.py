import hashlib,json,os,pathlib,resource,signal,subprocess,sys,time
root=pathlib.Path("/workspace/scratch/c385a7439f8e/renderer-native155-independent-review-v1")
source=root/"candidate-source"
def ident(p):
    b=p.read_bytes();return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()}
before={p.name:ident(p) for p in source.iterdir() if p.is_file()}
argv=[sys.executable,"-B",str(root/"probe.py"),str(source),str(root/"cases")]
def limits():resource.setrlimit(resource.RLIMIT_AS,(268435456,268435456))
with (root/"stdout").open("xb") as out,(root/"stderr").open("xb") as err:
    start=time.monotonic()
    child=subprocess.Popen(argv,stdout=out,stderr=err,preexec_fn=limits,start_new_session=True)
    timed=False
    while True:
        pid,status,usage=os.wait4(child.pid,os.WNOHANG)
        if pid:
            elapsed=time.monotonic()-start;child.returncode=os.waitstatus_to_exitcode(status);break
        if time.monotonic()-start>30 and not timed:
            os.killpg(child.pid,signal.SIGKILL);timed=True
        time.sleep(.01)
after={p.name:ident(p) for p in source.iterdir() if p.is_file()}
result={"schema":"independent-renderer155-counterexample-execution-v1","argv":argv,
    "returncode":child.returncode,"timed_out":timed,"whole_child_wall_seconds":elapsed,
    "wait4_child_CPU_seconds":usage.ru_utime+usage.ru_stime,"wait4_peak_RSS_bytes":usage.ru_maxrss*1024,
    "limits":{"whole_child_seconds":30,"address_space_bytes":268435456,"workers":1,"automatic_retry":False},
    "source_before":before,"source_after":after,"source_unchanged":before==after,
    "scope":"One stdlib pure synthetic metadata process. No Matplotlib, render, model, actual C2, E or native audit. Parent receipt/save/exit excluded from child cost."}
(root/"EXECUTION.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
print(json.dumps({k:result[k] for k in ("returncode","whole_child_wall_seconds","wait4_child_CPU_seconds","wait4_peak_RSS_bytes","source_unchanged")}))
raise SystemExit(child.returncode)

