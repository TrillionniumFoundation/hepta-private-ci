import hashlib,json,os,pathlib,resource,signal,subprocess,sys,time
root=pathlib.Path("/workspace/scratch/c385a7439f8e/renderer-native155-independent-closure-v1")
out=root/"coverage-rebind-v1"
def ident(p):
    b=p.read_bytes();return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()}
argv=[sys.executable,"-B",str(out/"check.py"),str(root),str(out/"ROSTER-REBIND.json")]
def limits():resource.setrlimit(resource.RLIMIT_AS,(268435456,268435456))
with (out/"stdout").open("xb") as stdout,(out/"stderr").open("xb") as stderr:
    start=time.monotonic();child=subprocess.Popen(argv,stdout=stdout,stderr=stderr,preexec_fn=limits,start_new_session=True)
    timed=False
    while True:
        pid,status,usage=os.wait4(child.pid,os.WNOHANG)
        if pid:
            elapsed=time.monotonic()-start;child.returncode=os.waitstatus_to_exitcode(status);break
        if time.monotonic()-start>30 and not timed:
            os.killpg(child.pid,signal.SIGKILL);timed=True
        time.sleep(.01)
receipt={"schema":"renderer155-roster-only-execution-v1","argv":argv,"returncode":child.returncode,"timed_out":timed,
    "whole_child_wall_seconds":elapsed,"wait4_child_CPU_seconds":usage.ru_utime+usage.ru_stime,"wait4_peak_RSS_bytes":usage.ru_maxrss*1024,
    "limits":{"whole_child_seconds":30,"address_space_bytes":268435456,"workers":1,"automatic_retry":False},
    "check_source":ident(out/"check.py"),"output":ident(out/"ROSTER-REBIND.json") if (out/"ROSTER-REBIND.json").is_file() else None,
    "scope":"One read-only source/hash child, no probe rerun; parent receipt serialization/exit excluded from this exact child cost."}
(out/"EXECUTION.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
print(json.dumps(receipt))
raise SystemExit(child.returncode)

