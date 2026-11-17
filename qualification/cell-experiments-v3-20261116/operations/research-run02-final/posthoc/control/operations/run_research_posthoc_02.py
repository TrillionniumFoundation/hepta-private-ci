"""Run the reviewed Run02 posthoc readout once and preserve exact output bytes."""
import base64, hashlib, json, shlex, subprocess, time
from pathlib import Path
ROOT=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
PY="/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python"
REL="operations/research02-diagnostic-order-fix-01"
MAN="147d90e993733c3c998210c55548c15d339a87d661a72bc49b1968bda3936e1c"
RUN="d78fd9c8b4c2349303a187a8cd715385c0e42bccd3180a60aea45bd891cd125a"
CONTROL=ROOT/"research-posthoc-operation-02"
OUT=ROOT/"research-posthoc-evidence-02"
SSH=["/usr/bin/ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=15","desktop-ts"]
def sha(raw): return hashlib.sha256(raw).hexdigest()
def save(name,value):
    with (CONTROL/name).open("x",encoding="utf-8") as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write("\n")
def remote(label,code,data=None,timeout=None):
    start=time.perf_counter()
    r=subprocess.run(SSH+[shlex.join([PY,"-I","-B","-c",code])],input=data,capture_output=True,timeout=timeout)
    (CONTROL/(label+".stdout")).write_bytes(r.stdout)
    (CONTROL/(label+".stderr")).write_bytes(r.stderr)
    save(label+".json",{"wait_returncode":r.returncode,"wall_seconds":time.perf_counter()-start,
        "stdout_sha256":sha(r.stdout),"stderr_sha256":sha(r.stderr),"automatic_retry":False})
    assert r.returncode==0,r.stderr.decode(errors="replace")
    return r.stdout
def main():
    CONTROL.mkdir(exist_ok=False);started=time.perf_counter()
    raw=(ROOT/REL/"POSTHOC_RUN_MANIFEST.json").read_bytes();assert sha(raw)==MAN
    m=json.loads(raw)
    chosen={r["path"]:r for r in m["bindings"].values() if r["path"].startswith(REL+"/")}
    chosen[REL+"/POSTHOC_RUN_MANIFEST.json"]={"bytes":len(raw),"sha256":MAN}
    assert len(chosen)==6 and m["bindings"]["runner"]["sha256"]==RUN
    payload=[]
    for rel,identity in chosen.items():
        p=ROOT/rel;assert p.is_file() and not p.is_symlink()
        data=p.read_bytes();assert len(data)==identity["bytes"] and sha(data)==identity["sha256"]
        payload.append({"name":p.name,"bytes":len(data),"sha256":sha(data),"data_base64":base64.b64encode(data).decode()})
    save("SOURCE_BINDINGS.json",{"manifest_sha256":MAN,"files":[{k:v for k,v in r.items() if k!="data_base64"} for r in payload]})
    deploy="""import base64,hashlib,json,pathlib,sys
target=pathlib.Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/operations/research02-diagnostic-order-fix-01")
data=json.load(sys.stdin)
assert len(data)==6 and len({r["name"] for r in data})==6
assert target.parent.is_dir() and target.parent.resolve()==target.parent and not target.exists()
target.mkdir(exist_ok=False)
for r in data:
 assert pathlib.Path(r["name"]).name==r["name"]
 raw=base64.b64decode(r["data_base64"],validate=True)
 assert len(raw)==r["bytes"] and hashlib.sha256(raw).hexdigest()==r["sha256"]
 p=target/r["name"]
 with p.open("xb") as f:f.write(raw)
 assert hashlib.sha256(p.read_bytes()).hexdigest()==r["sha256"]
print(json.dumps({"status":"DEPLOYED_EXACT_NEW_FILES","files":[{k:v for k,v in r.items() if k!="data_base64"} for r in data]}))
"""
    remote("DEPLOYMENT",deploy,json.dumps(payload).encode(),60)
    launch="""import hashlib,json,os,pathlib,sys,time
p=pathlib.Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/operations/research02-diagnostic-order-fix-01/run_posthoc_readonly.py")
assert hashlib.sha256(p.read_bytes()).hexdigest()=="d78fd9c8b4c2349303a187a8cd715385c0e42bccd3180a60aea45bd891cd125a"
os.environ["CUDA_VISIBLE_DEVICES"]=""
print(json.dumps({"state":"POSTHOC_EXEC_START","pid":os.getpid(),"at_ns":time.time_ns()}),flush=True)
os.execv(sys.executable,[sys.executable,"-I","-B",str(p),"--manifest-sha256","147d90e993733c3c998210c55548c15d339a87d661a72bc49b1968bda3936e1c"])
"""
    print(json.dumps({"state":"POSTHOC_REVIEWED_START","manifest_sha256":MAN}),flush=True)
    remote("EXECUTION",launch)
    export="""import base64,hashlib,json,pathlib
root=pathlib.Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-diagnostic-posthoc-02")
names=["DIAGNOSTIC.json","INPUT_BINDINGS.json","POSTHOC_RECEIPT.json"]
assert sorted(p.name for p in root.iterdir())==sorted(names)
out=[]
for name in names:
 p=root/name;assert p.is_file() and not p.is_symlink()
 raw=p.read_bytes();assert p.read_bytes()==raw
 out.append({"name":name,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"data_base64":base64.b64encode(raw).decode()})
print(json.dumps({"files":out}))
"""
    package=json.loads(remote("EXPORT",export,timeout=60));OUT.mkdir(exist_ok=False);identities=[]
    for r in package["files"]:
        assert r["name"] in ("DIAGNOSTIC.json","INPUT_BINDINGS.json","POSTHOC_RECEIPT.json")
        data=base64.b64decode(r["data_base64"],validate=True)
        assert len(data)==r["bytes"] and sha(data)==r["sha256"]
        with (OUT/r["name"]).open("xb") as f:f.write(data)
        assert sha((OUT/r["name"]).read_bytes())==r["sha256"]
        identities.append({k:r[k] for k in ("name","bytes","sha256")})
    diag=json.loads((OUT/"DIAGNOSTIC.json").read_bytes())
    receipt=json.loads((OUT/"POSTHOC_RECEIPT.json").read_bytes())
    assert receipt["diagnostic_sha256"]==sha((OUT/"DIAGNOSTIC.json").read_bytes())
    assert receipt["input_bindings_sha256"]==sha((OUT/"INPUT_BINDINGS.json").read_bytes())
    assert receipt["diagnostic_model_calls"]==receipt["diagnostic_verifier_calls"]==0
    complete={"schema":"hepta.posthoc-controller-complete.v1","status":"CLOSED_AND_COPIED",
        "actual_ssh_wait_returncode":0,"manifest_sha256":MAN,"files":identities,
        "wall_seconds":time.perf_counter()-started,"original_artifacts_rewritten":False,
        "new_model_calls":0,"new_verifier_calls":0,"new_C":False,"scientific_confirmation_qualified":False}
    save("COMPLETE.json",complete);print(json.dumps(complete),flush=True)
    print(json.dumps({"first_attempt_opportunity":diag["first_attempt_opportunity"],"binding_errors":diag["binding_errors"],
        "slots":{k:v["status"] for k,v in diag["fixed_expert_slots"].items()},
        "ledger":{k:diag["cost_ledger"][k] for k in ("model_calls","student_verifier_calls","reference_calls",
        "training_steps","input_tokens","output_tokens","global_totals_unknown")}}),flush=True)
if __name__=="__main__":main()
