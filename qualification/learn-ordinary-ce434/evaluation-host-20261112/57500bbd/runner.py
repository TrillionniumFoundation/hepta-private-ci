import datetime, hashlib, json, os, pathlib, subprocess, sys, time
repo=pathlib.Path("/workspace/scratch/ce434f960ee9/evaluation-host-review-57500bbd-v1")
out=pathlib.Path("/workspace/scratch/ce434f960ee9/evaluation-host-evidence-57500bbd-v1")
EXPECTED="57500bbdf5bc362de17828296c831e90dcb30dae"
TREE="0fc145ee9237babfdf793579cf15d58eaa4e0ddc"
TESTS=["qa/b4-no-bypass/test_original_evaluation_host_source_closure.py","qa/b4-no-bypass/test_original_candidate_stage_source_closure.py","qa/b4-no-bypass/test_original_evaluation_panel_source_closure.py","qa/b4-no-bypass/test_original_evaluation_receipt_owner_source_closure.py","qa/b4-no-bypass/test_original_next_use_command_source_closure.py","qa/b4-no-bypass/test_original_no_update_stage_source_closure.py","qa/b4-no-bypass/test_original_selector_command_source_closure.py","qa/b4-no-bypass/test_original_training_bootstrap_source_closure.py","qa/b4-no-bypass/test_original_training_command_source_closure.py","qa/b4-no-bypass/test_original_training_initial_connection_source_closure.py","qa/b4-no-bypass/test_resident_candidate_stage_source_closure.py","qa/b4-no-bypass/test_resident_root_source_closure.py"]
def utc(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def git(*args): return subprocess.check_output(["git",*args],cwd=repo,text=True).strip()
def identity():
    return {"source_sha":git("rev-parse","HEAD"),"tree_sha":git("rev-parse","HEAD^{tree}"),
            "dirty":git("status","--porcelain=v1","--untracked-files=all")}
def save(name,value):
    with (out/name).open("x") as stream: json.dump(value,stream,sort_keys=True,indent=2); stream.write("\n")
before=identity()
if before!={"source_sha":EXPECTED,"tree_sha":TREE,"dirty":""}: raise RuntimeError(before)
save("source-before.json",before)
commands=[]
env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
def run(label,command):
    start=time.monotonic(); started=utc(); path=out/(label+".log")
    with path.open("xb") as log:
        try:
            result=subprocess.run(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            code=result.returncode; timed_out=False
        except subprocess.TimeoutExpired:
            code=None;timed_out=True
    raw=path.read_bytes()
    record={"label":label,"command":command,"started_at":started,"finished_at":utc(),
            "elapsed_seconds":time.monotonic()-start,"exit_code":code,"timed_out":timed_out,
            "log_file":path.name,"log_bytes":len(raw),"log_sha256":hashlib.sha256(raw).hexdigest(),
            "source_sha":EXPECTED,"tree_sha":TREE}
    commands.append(record);save(label+".json",record);print(json.dumps(record),flush=True)
for path in TESTS:
    item=pathlib.Path(path)
    run(item.stem,["python3","-B","-m","unittest","discover","-s",str(item.parent),"-p",item.name,"-v"])
run("coverage-parser",["python3","-B","-m","unittest","discover","-s","scripts","-p","test_hepta_c_observer_coverage.py","-v"])
run("working-tree-diff-check",["git","diff","--check"])
after=identity();save("source-after.json",after)
passed=after==before and all(row["exit_code"]==0 and not row["timed_out"] for row in commands)
save("result.json",{"schema":1,"status":"passed" if passed else "failed","source_before":before,
     "source_after":after,"commands":commands,"qualification_scope":"12 changed source-closure suites and report parser; no Rust, H, full caller proof or ordinary experiment",
     "native_executed":0,"ordinary_closed_loops":0})
print(json.dumps({"status":"passed" if passed else "failed","source":EXPECTED,"commands":len(commands)}),flush=True)
sys.exit(0 if passed else 1)
