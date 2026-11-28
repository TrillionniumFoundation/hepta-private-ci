"""Relay the independently verified fixed-gate replays and sealed Fisher study."""
import json
import sys
import time
from pathlib import Path, PurePosixPath
from subprocess import TimeoutExpired

from publish_results import run, SSH, HOST_DIR, push
from archive import sha


def download(names, remote, local):
    if any(PurePosixPath(n).name!=n or not n for n in names):
        raise ValueError("all expected secondary artifacts are flat files")
    local.mkdir(exist_ok=True,parents=True)
    run(["rsync","-a","--files-from=-","-e","ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
         "ai395:"+HOST_DIR+"/"+remote+"/",str(local)+"/"],("\n".join(names)+"\n").encode())


def remote_text(folder, file):
    try:
        return json.loads(run(SSH+["cat",HOST_DIR+"/"+folder+"/"+file]))
    except RuntimeError as error:
        if "No such file" in str(error):
            return None
        raise


def stage(root,kind,folder,trigger):
    marker=remote_text(folder,trigger)
    if marker is None:
        return False
    local=root/kind
    if kind=="fisher":
        seal=remote_text(folder,"development_seal.json")
        if len(seal["candidates"])!=12:
            raise ValueError("candidate count")
        rows=[r for group in seal["candidates"].values() for r in group]
        names=["development_seal.json","terminal.json"]+[r["path"] for r in rows]+[r["path"][:-3]+".npz" for r in rows]
        download(names,folder,local)
        if sha(local/"development_seal.json")!=marker["seal_sha256"] or any(sha(local/r["path"])!=r["file_sha256"] for r in rows):
            raise ValueError("candidate weights differ")
        # This verifier recomputes all primary and secondary scores and paired actor intervals.
        from verify_discriminant import verify
        checked=verify(local)
        (local/"independent_verification.json").write_text(json.dumps(checked,indent=2)+"\n")
        names.append("independent_verification.json")
    else:
        if marker["verified"] is not True or marker["actual_optimization_seconds"]<37800:
            raise ValueError("incomplete gate replay")
        records=[r for cell in marker["cells"].values() for r in cell["independent_replay"].values()]
        names=["VERIFIED.json"]+[r["scores_file"] for r in records]
        if len(set(names))!=len(names):
            raise ValueError("duplicate score files")
        download(names,folder,local)
        if any(sha(local/r["scores_file"])!=r["scores_sha256"] for r in records):
            raise ValueError("replayed score hash mismatch")
    commit=push(kind,[local/n for n in names],root)
    receipt=dict(commit=commit,files=len(names),marker_sha256=sha(local/trigger),utc=time.time())
    (root/(kind+"-receipt.json")).write_text(json.dumps(receipt,indent=2)+"\n")
    print(kind,json.dumps(receipt),flush=True)
    return True


if __name__=="__main__":
    root=Path(sys.argv[1]).resolve()
    root.mkdir(exist_ok=True,parents=True)
    for kind,folder,trigger in [("fisher","fisher_run","terminal.json"),("gate_replay","gate_replay","VERIFIED.json")]:
        while not (root/(kind+"-receipt.json")).is_file():
            try:
                if stage(root,kind,folder,trigger):
                    break
            except (RuntimeError,TimeoutExpired) as exc:
                print(kind,str(exc),flush=True)
            time.sleep(45)
