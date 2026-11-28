"""Collect and publish verified experiment archives to the existing private results branch."""
import json
from pathlib import Path
import sys
import time
from subprocess import TimeoutExpired

from archive import sha
from publish_results import HOST_DIR,SSH,push,run


def stage(root,kind):
    local=root/kind;local.mkdir(exist_ok=True,parents=True)
    remote=HOST_DIR+"/followup_archives/"+kind
    try:manifest=json.loads(run(SSH+["cat",remote+"/manifest.json"]))
    except RuntimeError as e:
        if "No such file" in str(e):return False
        raise
    names=["manifest.json"]+[r["name"] for r in manifest["parts"]]
    if not all(Path(n).name==n and "\n" not in n for n in names):raise ValueError("unexpected part")
    run(["rsync","-a","--files-from=-","-e","ssh -o BatchMode=yes -o StrictHostKeyChecking=yes","ai395:"+remote+"/",str(local)+"/"],
        ("\n".join(names)+"\n").encode())
    for r in manifest["parts"]:
        if sha(local/r["name"])!=r["sha256"]:raise ValueError("part mismatch")
    commit=push(kind,[local/n for n in names],root)
    rec=dict(files=manifest["file_count"],parts=len(manifest["parts"]),archive_sha256=manifest["archive_sha256"],
             terminal_sha256=manifest["terminal_sha256"],commit=commit,utc=time.time())
    (root/(kind+"-receipt.json")).write_text(json.dumps(rec,indent=2)+"\n")
    print(kind,json.dumps(rec),flush=True)
    return True


if __name__=="__main__":
    root=Path(sys.argv[1]).resolve();root.mkdir(exist_ok=True,parents=True)
    for kind in ("whole_corpus","null_space"):
        while not (root/(kind+"-receipt.json")).is_file():
            try:
                if stage(root,kind):break
            except (RuntimeError,TimeoutExpired) as e:print(kind,type(e).__name__,str(e),flush=True)
            time.sleep(45)
