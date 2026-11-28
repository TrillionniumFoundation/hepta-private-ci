"""Publish verified per-rung original archives in small, restartable Git object writes."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import os
import time
import fcntl
REPO="TrillionniumFoundation/hepta-private-ci"
BRANCH="research/hcsn-returning-regimes-9de7-results"
PREFIX="qualification/hcsn_recurrent_boundary_20261128/trainable_encoder/results/archives"
RUNGS=("epoch1","time120","time900","time2600","terminal")


def api(method,endpoint,body=None):
    args=["gh","api","--method",method,"repos/"+REPO+"/git/"+endpoint]
    if body is not None:args+=["--input","-"]
    proc=subprocess.run(args,input=None if body is None else json.dumps(body).encode(),capture_output=True,timeout=120)
    if proc.returncode:
        raise RuntimeError(f"{method} {endpoint.split('/')[0]}: "+proc.stderr.decode(errors="replace")[-170:])
    return json.loads(proc.stdout)


def ensure_blob(raw):
    want=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    obj=api("POST","blobs",{"encoding":"base64","content":base64.b64encode(raw).decode()})
    if obj["sha"]!=want:raise ValueError("Git content identity mismatch")
    return want


def publish(root,rung,work):
    manifest=root/(rung+".json")
    if not manifest.exists():return None
    raw=manifest.read_bytes();info=json.loads(raw)
    state=work/("blobs-"+rung+".json")
    ledger=json.loads(state.read_text()) if state.exists() else {}
    files=[(manifest,"manifest.json",hashlib.sha256(raw).hexdigest())]+[
        (root/rung/f["path"],f["path"],f["sha256"]) for f in info["parts"]]
    entries=[]
    for fil,name,checksum in files:
        b=fil.read_bytes()
        if hashlib.sha256(b).hexdigest()!=checksum:raise ValueError("changed source "+name)
        oid=hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
        if ledger.get(name)!=oid:
            if ensure_blob(b)!=oid:raise ValueError("transported blob mismatch")
            ledger[name]=oid;t=state.with_suffix(".tmp");t.write_text(json.dumps(ledger));t.replace(state)
        entries.append(dict(path=f"{PREFIX}/{rung}/{name}",mode="100644",type="blob",sha=oid))
    parent=api("GET","ref/heads/"+BRANCH)["object"]["sha"]
    tree0=api("GET","commits/"+parent)["tree"]["sha"]
    tree=api("POST","trees",dict(base_tree=tree0,tree=entries))["sha"]
    if tree==tree0:return parent
    commit=api("POST","commits",dict(message="Archive verified native "+rung+" weights and logits in checksummed parts",tree=tree,parents=[parent]))["sha"]
    ref=api("PATCH","refs/heads/"+BRANCH,dict(sha=commit,force=False))["object"]["sha"]
    if ref!=commit:raise ValueError("branch update mismatch")
    return commit


def run(src,work):
    work.mkdir(parents=True,exist_ok=True)
    with (work/"publisher.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for rung in RUNGS:
            done=work/(rung+".commit")
            if done.exists():continue
            errors=0
            while True:
                try:
                    sha=publish(src,rung,work)
                    if sha:
                        done.write_text(sha+"\n")
                        print("published",rung,sha,flush=True);break
                except (RuntimeError,subprocess.TimeoutExpired) as err:
                    errors+=1
                    print("transport",rung,errors,str(err)[:250],flush=True)
                time.sleep(20 if errors==0 else min(120,10*errors))
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("source",type=Path);a.add_argument("working",type=Path)
    p=a.parse_args();run(p.source,p.working)
