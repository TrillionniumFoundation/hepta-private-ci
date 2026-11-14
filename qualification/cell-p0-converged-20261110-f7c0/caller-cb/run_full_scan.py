from pathlib import Path
import datetime,hashlib,json,os,resource,subprocess,sys,time

REPO=Path("/workspace/scratch/f7c0ded86bcc/hepta-p0-learn-merge")
OUT=Path("/workspace/scratch/f7c0ded86bcc/p0_final_caller_audit_cb0598_20261111")
HEAD="cb0598a9099a0d828ce73aedb51e397e600e49d1"
TREE="59a019b79a6b879bbc27f6a614e1222fe87581ca"
BRANCH="codex/cell-p0-final-caller-audit-f7c0"
KEY="p0-cb0598-full-caller-scan-20261111-v1"
COMMAND=["python3","scripts/verify_hepta_callers.py","verify","--root",str(REPO)]
sha=lambda b:hashlib.sha256(b).hexdigest()
utc=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def emit(value):
    print(json.dumps(value,sort_keys=True),flush=True)
def save(name,value):
    p=OUT/name
    p.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")
def git(*args):
    return subprocess.check_output(["git",*args],cwd=REPO)
def snapshot(phase):
    head=git("rev-parse","HEAD").decode().strip()
    tree=git("rev-parse","HEAD^{tree}").decode().strip()
    branch=git("symbolic-ref","--short","HEAD").decode().strip()
    status=git("status","--porcelain=v1","-z","--untracked-files=all")
    (OUT/(phase+"_STATUS.porcelain.z")).write_bytes(status)
    assert git("rev-parse","HEAD").decode().strip()==head
    result={"observed_at_utc":utc(),"head":head,"tree":tree,"branch":branch,
            "status_command":["git","status","--porcelain=v1","-z","--untracked-files=all"],
            "status_bytes":len(status),"status_sha256":sha(status),"clean":status==b"",
            "clean_scope":"tracked and non-ignored untracked files as reported by git status",
            "callers_sha256":sha((REPO/"CALLERS.toml").read_bytes()),
            "verifier_sha256":sha((REPO/"scripts/verify_hepta_callers.py").read_bytes())}
    save(phase+".json",result)
    return result
if (OUT/"INVOCATION.json").exists() or (OUT/"SCAN.stdout.json").exists():
    raise SystemExit("A prior attempt record exists; refusing to start another scan.")
before=snapshot("BEFORE")
assert before["head"]==HEAD and before["tree"]==TREE and before["branch"]==BRANCH and before["clean"],before
preparation=json.loads((OUT/"PREPARATION.json").read_text())
assert git("rev-parse","refs/heads/"+preparation["original_branch"]).decode().strip()==preparation["original_branch_head_retained"]
invocation={"key":KEY,"command":COMMAND,"cwd":str(REPO),"source_before":before,"python":sys.version,
            "started_at_utc":utc(),"status":"PREPARED","runner_pid":os.getpid(),
            "scope":"One full static caller verification; no native build/test/model/business job."}
save("INVOCATION.json",invocation)
with (OUT/"SCAN.stdout.json").open("xb") as stdout,(OUT/"SCAN.stderr.txt").open("xb") as stderr:
    ru_before=resource.getrusage(resource.RUSAGE_CHILDREN)
    started=time.monotonic()
    proc=subprocess.Popen(COMMAND,cwd=REPO,stdout=stdout,stderr=stderr)
    invocation.update({"status":"RUNNING","child_pid":proc.pid})
    save("INVOCATION.json",invocation)
    emit({"phase":"scan_started","key":KEY,"pid":proc.pid,"started_at_utc":invocation["started_at_utc"],"head":HEAD,"tree":TREE,"before_clean":True})
    while True:
        try:
            code=proc.wait(timeout=40)
            break
        except subprocess.TimeoutExpired:
            cpu=None
            try:
                stat=Path(f"/proc/{proc.pid}/stat").read_text()
                fields=stat.rsplit(")",1)[1].split()
                cpu=(int(fields[11])+int(fields[12]))/os.sysconf("SC_CLK_TCK")
            except (FileNotFoundError,ValueError,IndexError):
                pass
            heartbeat={"at_utc":utc(),"phase":"scan_running","pid":proc.pid,"elapsed_wall_seconds":round(time.monotonic()-started,3),
                       "child_cpu_seconds_proc":cpu,"stdout_bytes":(OUT/"SCAN.stdout.json").stat().st_size,
                       "stderr_bytes":(OUT/"SCAN.stderr.txt").stat().st_size}
            with (OUT/"HEARTBEATS.jsonl").open("a",encoding="utf-8") as heartbeat_file:
                heartbeat_file.write(json.dumps(heartbeat,sort_keys=True)+"\n")
            emit(heartbeat)
    elapsed=time.monotonic()-started
    ru_after=resource.getrusage(resource.RUSAGE_CHILDREN)
    ended=utc()
after=snapshot("AFTER")
identity_keys=["head","tree","branch","status_bytes","status_sha256","clean","callers_sha256","verifier_sha256"]
unchanged=all(before[k]==after[k] for k in identity_keys)
raw_stdout=(OUT/"SCAN.stdout.json").read_bytes()
raw_stderr=(OUT/"SCAN.stderr.txt").read_bytes()
parsed=None
parse_error=None
try:
    parsed=json.loads(raw_stdout)
except Exception as exc:
    parse_error=str(exc)
execution={"key":KEY,"status":"COMPLETED","command":COMMAND,"child_pid":proc.pid,"exit_code":code,
           "started_at_utc":invocation["started_at_utc"],"ended_at_utc":ended,"wall_seconds":elapsed,
           "child_user_cpu_seconds":ru_after.ru_utime-ru_before.ru_utime,
           "child_system_cpu_seconds":ru_after.ru_stime-ru_before.ru_stime,
           "child_cpu_scope":"RUSAGE_CHILDREN delta around only the verifier subprocess; excludes preparation, Git snapshots, orchestration and external CI.",
           "source_identity_unchanged":unchanged,"before":before,"after":after,
           "original_branch_retained":git("rev-parse","refs/heads/"+preparation["original_branch"]).decode().strip()==preparation["original_branch_head_retained"],
           "stdout":{"file":"SCAN.stdout.json","bytes":len(raw_stdout),"sha256":sha(raw_stdout)},
           "stderr":{"file":"SCAN.stderr.txt","bytes":len(raw_stderr),"sha256":sha(raw_stderr)},
           "verifier_receipt_parse_error":parse_error,
           "verifier_status":parsed.get("status") if isinstance(parsed,dict) else None,
           "rust_files_scanned":parsed.get("rustFilesScanned") if isinstance(parsed,dict) else None,
           "boundaries_count":len(parsed.get("boundaries",[])) if isinstance(parsed,dict) else None,
           "privileged_inventory_count":len(parsed.get("privilegedInventory",[])) if isinstance(parsed,dict) else None,
           "protected_files_count":len(parsed.get("protectedFiles",[])) if isinstance(parsed,dict) else None,
           "authority_granted":parsed.get("authorityGranted") if isinstance(parsed,dict) else None}
execution["qualified_exact_source_caller_scan"]=(code==0 and unchanged and execution["original_branch_retained"] and execution["verifier_status"]=="PASS_HEPTA_CALLER_CLOSED_SET" and execution["authority_granted"] is False)
save("EXECUTION.json",execution)
invocation.update({"status":"COMPLETED","exit_code":code,"ended_at_utc":ended})
save("INVOCATION.json",invocation)
emit({k:v for k,v in execution.items() if k not in ["before","after","command"]})
raise SystemExit(0 if execution["qualified_exact_source_caller_scan"] else 1)

