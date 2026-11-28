"""Continue the same recipe after a worker loss and verify its released predictions."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def held(path):
    with path.open("a") as f:
        try:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def verify_sources(study,out):
    recipe=json.loads((out/"recipe.json").read_text())
    for key,digest in recipe["sources"].items():
        if hashlib.sha256((study/key).read_bytes()).hexdigest()!=digest:
            raise ValueError("study source changed")


def run(study,source):
    out=study/"run"
    with (study/"supervisor.lock").open("a") as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        misses=0
        while not (out/"terminal.json").exists():
            if not (out/"recipe.json").exists():
                raise ValueError("normal launch has not confirmed its recipe")
            misses=0 if held(out/"worker.lock") else misses+1
            if misses>=2 and not (out/"terminal.json").exists():
                verify_sources(study,out)
                with (study/"restarts.jsonl").open("a") as f:
                    f.write(json.dumps(dict(when=time.time(),reason="original writer lock vacant"))+"\n")
                code=subprocess.run([sys.executable,"-u",str(study/"train.py"),str(source),str(out),
                                     str(study/"study.py")],cwd=study).returncode
                if code not in (0,-9,-15,-1):
                    raise RuntimeError(f"resumed training failed with status {code}")
                misses=0
            else:
                time.sleep(45)
        verify_sources(study,out)
        subprocess.run([sys.executable,str(study/"verify_terminal.py"),str(out),str(source/"data/data.npz")],check=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("study",type=Path)
    p.add_argument("source",type=Path)
    a=p.parse_args()
    run(a.study,a.source)
