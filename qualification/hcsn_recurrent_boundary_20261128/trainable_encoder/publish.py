"""Mirror complete registered native evidence to the private experiment results branch."""
import base64
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

REPO="TrillionniumFoundation/hepta-private-ci"
BRANCH="research/hcsn-returning-regimes-9de7-results"
DIRECTORY="qualification/hcsn_recurrent_boundary_20261128/trainable_encoder/results"
REMOTE="/home/qq/.local/share/hepta-research/hcsn-returning-regimes-9de7/run"
ORIGIN="ai395"
CELLS=[f"{a}-{s}" for a in ("stationary","irreversible","returning","lif","sdpa") for s in (137,311,557)]
RUNG=("epoch1","time120","time900","time2600")
SSH=["ssh","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=12"]


def command(argv,data=None,timeout=600):
    run=subprocess.run(argv, input=data, timeout=timeout,check=False,capture_output=True)
    if run.returncode:
        raise RuntimeError(argv[0]+" "+str(run.returncode)+" "+run.stderr.decode(errors="replace")[-350:])
    return run.stdout


def gh(method,resource,payload=None):
    args=["/usr/bin/gh","api","-X",method,"repos/"+REPO+"/git/"+resource]
    if payload is not None:args+=["--input","-"]
    return json.loads(command(args,json.dumps(payload).encode() if payload is not None else None))


def fetch_list(dest, names):
    if any("\n" in x or x.startswith("/") or ".." in x.split("/") for x in names):
        raise ValueError("invalid archive member")
    command(["rsync","-a","--files-from=-","-e"," ".join(SSH),ORIGIN+":"+REMOTE+"/",str(dest)+"/"],
            ("\n".join(sorted(names))+"\n").encode(),timeout=1800)


def inventory(dest,tag):
    # All lightweight observations come from the real file on the original machine.
    script="""import json,sys
from pathlib import Path
root=Path(sys.argv[1]); rows={}
for p in sorted(root.glob('*/progress.json')):
    d=json.loads(p.read_text())
    rows[p.parent.name]=d['history']
verified=(root/'verification.json').is_file() and (root/'strict_verification.json').is_file()
print(json.dumps({'history':rows,'verified':verified}))
"""
    # All remote words are fixed registered constants, without user-controlled shell text.
    state=json.loads(command(SSH+[ORIGIN,"python3","-",REMOTE],script.encode()))
    if tag=="terminal" and not state["verified"]:
        return None
    if any(c not in state["history"] or any(t not in state["history"][c]
           for t in (RUNG if tag=="terminal" else (tag,))) for c in CELLS):
        return None
    wanted={}
    for c in CELLS:
        for t in (RUNG if tag=="terminal" else (tag,)):
            row=state["history"][c][t]
            for filename,checksum in ((row["file"],row["weight_sha"]),(row["score_file"],row["score_sha"])):
                if Path(filename).name!=filename:
                    raise ValueError("unsafe filename")
                wanted[c+"/"+filename]=checksum
    if tag=="terminal":
        fetch_list(dest,["seal.json","terminal.json","verification.json","strict_verification.json","held-identities.npz","recipe.json","sessions.jsonl"])
        result=json.loads((dest/"terminal.json").read_text())
        verified=json.loads((dest/"verification.json").read_text())
        strict=json.loads((dest/"strict_verification.json").read_text())
        if not (verified["terminal_sha"]==strict["terminal_sha"]==hashlib.sha256((dest/"terminal.json").read_bytes()).hexdigest()):
            raise ValueError("independent verification mismatch")
        for c,scores in result["panels"].items():
            if c not in CELLS:
                raise ValueError("invalid model")
            for score in scores.values():
                if Path(score["file"]).name!=score["file"]:
                    raise ValueError("invalid score filename")
                wanted[c+"/"+score["file"]]=score["sha"]
        for f in ("seal.json","terminal.json","verification.json","strict_verification.json","held-identities.npz","recipe.json","sessions.jsonl"):
            wanted[f]=hashlib.sha256((dest/f).read_bytes()).hexdigest()
    fetch_list(dest,wanted)
    for name,digest in wanted.items():
        if hashlib.sha256((dest/name).read_bytes()).hexdigest()!=digest:
            raise ValueError("native receipt mismatch "+name)
    receipt_name="released-"+tag+".json"
    (dest/receipt_name).write_text(json.dumps(dict(tag=tag,files=wanted),indent=2)+"\n")
    return [*wanted,receipt_name]


def publish(stage,tag,files,ledger):
    entries=[]
    for name in files:
        data=(stage/name).read_bytes()
        oid=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        if oid not in ledger:
            obj=gh("POST","blobs",dict(encoding="base64",content=base64.b64encode(data).decode()))
            if obj["sha"]!=oid:raise ValueError("stored blob identity differs")
            ledger.add(oid)
            (stage/"uploaded.txt").write_text("\n".join(sorted(ledger))+"\n")
        entries.append(dict(path=DIRECTORY+"/"+name,mode="100644",type="blob",sha=oid))
    ref=gh("GET","ref/heads/"+BRANCH)["object"]["sha"]
    base=gh("GET","commits/"+ref)["tree"]["sha"]
    tree=gh("POST","trees",dict(base_tree=base,tree=entries))["sha"]
    if tree==base:return ref
    commit=gh("POST","commits",dict(tree=tree,parents=[ref],message="Preserve native returning-regime "+tag+" observations"))["sha"]
    actual=gh("PATCH","refs/heads/"+BRANCH,dict(sha=commit,force=False))["object"]["sha"]
    if actual!=commit:raise ValueError("unexpected remote ref")
    return commit


def run(stage):
    stage.mkdir(parents=True,exist_ok=True)
    with (stage/"publisher.lock").open("a") as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ledger=set((stage/"uploaded.txt").read_text().splitlines()) if (stage/"uploaded.txt").exists() else set()
        for tag in (*RUNG,"terminal"):
            receipt=stage/("commit-"+tag+".txt")
            if receipt.is_file():continue
            failures=0
            while True:
                try:
                    files=inventory(stage,tag)
                    if files:
                        commit=publish(stage,tag,files,ledger)
                        receipt.write_text(commit+"\n")
                        print(tag,commit,"files",len(files),flush=True)
                        break
                    failures=0
                except (RuntimeError,subprocess.TimeoutExpired) as err:
                    failures+=1
                    print("transport",tag,failures,str(err)[:380],flush=True)
                    if failures>=10:raise
                time.sleep(60)


if __name__=="__main__":
    run(Path(sys.argv[1]).resolve())
