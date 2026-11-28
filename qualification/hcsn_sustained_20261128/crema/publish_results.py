"""Collect and publish only task-owned, sealed study outputs using the configured host identities."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from archive import inventory, sha, PREFIX, BRANCH

HOST_DIR = "/home/qq/.local/share/hepta-research/hcsn-sustained-1140569"
REPO = "TrillionniumFoundation/hepta-private-ci"
TARGET = "repos/" + REPO + "/git"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
       "-o", "ConnectTimeout=10", "ai395"]


def run(args,data=None,timeout=600):
    p=subprocess.run(args,input=data,capture_output=True,timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{args[0]} returned {p.returncode}: "+p.stderr.decode(errors="replace")[-280:])
    return p.stdout


def gh(method, endpoint, body=None):
    args=["gh","api","-X",method,endpoint]
    if body is not None:
        args+=["--input","-"]
    return json.loads(run(args,json.dumps(body).encode() if body is not None else None))


def file_list(kind):
    # Compute selection on the original machine against its original seal.
    program=f"""import json,sys
from pathlib import Path
base=Path({HOST_DIR!r})
sys.path.insert(0,str(base))
from archive_v2 import inventory
p=base/{kind!r}
if not (p/'terminal.json').is_file(): print('[]')
else: print(json.dumps([str(f.relative_to(p)) for f in inventory(p,{kind!r})]))
"""
    return json.loads(run(SSH+["python3","-"],program.encode()))


def push(kind,files,root):
    ref = TARGET+"/ref/heads/"+BRANCH
    local = root/kind
    entries=[]
    cachepath=root/(kind+"-uploaded.json")
    uploaded=json.loads(cachepath.read_text()) if cachepath.exists() else {}
    for f in files:
        relative=str(f.relative_to(local))
        data=f.read_bytes()
        oid=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        if uploaded.get(relative)!=oid:
            result=gh("POST",TARGET+"/blobs",dict(encoding="base64",content=base64.b64encode(data).decode()))
            if result["sha"]!=oid:
                raise ValueError("remote blob mismatch")
            uploaded[relative]=oid
            temp=cachepath.with_suffix(".tmp")
            temp.write_text(json.dumps(uploaded))
            temp.replace(cachepath)
        entries.append(dict(mode="100644",type="blob",path=PREFIX+kind+"/"+relative,sha=oid))
    for _ in range(5):
        head=gh("GET",ref)["object"]["sha"]
        tree=gh("GET",TARGET+"/commits/"+head)["tree"]["sha"]
        new=gh("POST",TARGET+"/trees",dict(base_tree=tree,tree=entries))["sha"]
        if tree==new:
            return head
        commit=gh("POST",TARGET+"/commits",dict(tree=new,parents=[head],message="Archive verified CREMA-D "+kind+" results"))["sha"]
        try:
            gh("PATCH",TARGET+"/refs/heads/"+BRANCH,dict(sha=commit,force=False))
        except RuntimeError:
            if gh("GET",ref)["object"]["sha"]==head:
                raise
            continue
        if gh("GET",ref)["object"]["sha"]==commit:
            return commit
    raise RuntimeError("result branch advanced during publication")


def main():
    root=Path(sys.argv[1]).resolve()
    root.mkdir(parents=True,exist_ok=True)
    with (root/"relay.lock").open("a") as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for kind in ("edit","run"):
            completed=root/(kind+"-receipt.json")
            if completed.is_file():
                continue
            while True:
                try:
                    names=file_list(kind)
                    if not names:
                        time.sleep(45)
                        continue
                    if any(Path(n).is_absolute() or ".." in Path(n).parts or "\n" in n for n in names):
                        raise ValueError("unexpected relative path")
                    dest=root/kind
                    dest.mkdir(exist_ok=True)
                    run(["rsync","-a","--files-from=-","-e","ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
                         "ai395:"+HOST_DIR+"/"+kind+"/",str(dest)+"/"], ("\n".join(names)+"\n").encode())
                    # Recreate all selected live-model files except the unselected sustained checkpoints.
                    if kind=="edit":
                        files=inventory(dest,kind)
                    else:
                        files=[dest/n for n in names]
                        if sha(dest/"seal.json")!=json.loads((dest/"terminal.json").read_text())["seal_sha256"]:
                            raise ValueError("relay seal mismatch")
                        for key,item in json.loads((dest/"seal.json").read_text()).items():
                            if sha(dest/key/item["best"]["file"])!=item["best"]["sha256"]:
                                raise ValueError("relay weight mismatch")
                    commit=push(kind,files,root)
                    receipt=dict(commit=commit,branch=BRANCH,files=len(files),terminal_sha256=sha(dest/"terminal.json"),utc=time.time())
                    completed.write_text(json.dumps(receipt,indent=2)+"\n")
                    print(json.dumps(receipt),flush=True)
                    break
                except (RuntimeError,subprocess.TimeoutExpired) as exc:
                    print(type(exc).__name__,str(exc),flush=True)
                    time.sleep(55)


if __name__=="__main__":
    main()
