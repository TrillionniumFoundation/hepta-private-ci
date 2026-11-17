
from pathlib import Path
import hashlib,io,json,stat,sys,time,zipfile
root=Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
probe=root/"probe-qwen-parent-03"
phase='setup'
files={}
def add(path):
    assert path.is_file() and path.resolve()==path
    files[path.relative_to(root).as_posix()]=path
if phase=="setup":
    for stage in ("SOURCE","RUNTIME_MATERIALS","PREPARATION","MODEL_LOAD"):
        assert json.loads((probe/(stage+"_FINISHED.json")).read_bytes())["status"]=="COMPLETE"
        add(probe/(stage+"_STARTED.json"));add(probe/(stage+"_FINISHED.json"))
    for name in ("STARTED.json","SOURCE.json","ENVIRONMENT_RECOVERY_03.json","MATERIALS_RECOVERY_04.json","PRIOR_ENVIRONMENT_FAILURE_02.json","PRIOR_MATERIALS_STOP_02.json","RECOVERY.json","RUNTIME.json","parent.json","PREPARATION_FREEZE.json","REFERENCE_INPUTS.json","PREPARED_RECORDS.json","PREPARED_A_RECORDS.json","FREEZE.json","MODEL_LOADED.json"):
        add(probe/name)
    for index in range(9):add(probe/("reference-%d.json"%index))
    for name in ("INTENT.json","STARTED.json"):add(root/"owned-qwen-parent-03"/name)
elif phase=="repository":
    assert json.loads((probe/"REPOSITORY_FINISHED.json").read_bytes())["status"]=="COMPLETE"
    add(probe/"REPOSITORY_STARTED.json");add(probe/"REPOSITORY_FINISHED.json")
    for path in (probe/"repository").rglob("*"):
        if not path.is_dir():add(path)
elif phase=="terminal":
    exit_receipt=json.loads((root/"owned-qwen-parent-03/EXIT.json").read_bytes())
    assert exit_receipt["exit_source"]=="subprocess.Popen.wait"
    for directory in (probe,root/"owned-qwen-parent-03",root/"readiness-preflight-03b",root/"readiness-preflight-03"):
        for path in directory.rglob("*"):
            if not path.is_dir():add(path)
    for name in ("run_qwen_readiness_v3_03.py","launch_qwen_parent03_owned.py","copy_qwen_materials_ram03.py","preflight_qwen_readiness_v3_04.py","preflight_qwen_readiness_v3_05.py","MATERIALS_COPY_03_STARTED.json","MATERIALS_COPY_03.json","QWEN_SOURCE_02.json"):
        add(root/"operations"/name)
    add(root/"WORKSPACE_OWNERSHIP.json");add(root/"qwen-source-02.zip")
else:raise ValueError("unknown bounded capture phase")
members=[];total=0;buffer=io.BytesIO()
with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as package:
    for name,path in sorted(files.items()):
        before=path.stat();assert stat.S_ISREG(before.st_mode) and before.st_size<=8*1024**2
        raw=path.read_bytes();after=path.stat()
        assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
        total+=len(raw);assert total<=64*1024**2
        row={"path":name,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
        if name.endswith(".json"):
            try:json.loads(raw);row["json_parse_status"]="valid"
            except (ValueError,UnicodeError):row["json_parse_status"]="invalid_original_bytes_preserved"
        package.writestr(name,raw);members.append(row)
    observation={"schema":"hepta.qwen-phase-capture.v3","phase":phase,"captured_at_ns":time.time_ns(),"members":members,"original_bytes_modified":False,"weights_exported":False,"model_calls_added":0,"training_steps_added":0,"independent_sample_increment":0,"h_terminal_status":"not_observed_by_capture"}
    if phase=="terminal":observation["owned_child_exit"]=exit_receipt
    package.writestr("POSTHOC_CAPTURE.json",json.dumps(observation,sort_keys=True,separators=(",",":"))+"\n")
assert len(buffer.getvalue())<16*1024**2
sys.stdout.buffer.write(buffer.getvalue());sys.stdout.buffer.flush()
