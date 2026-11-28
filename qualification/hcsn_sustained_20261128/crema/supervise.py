"""Resume the one existing wall-clock study only after its writer lock is vacant."""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def digest(p):
    with p.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def alive(path):
    with path.open("a") as f:
        try:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def run(base,source):
    out=base/"run"
    expected=json.loads((out/"sessions.jsonl").read_text().splitlines()[0])
    if digest(base/"study.py")!=expected["source"] or any(digest(source/k)!=v for k,v in expected["input_hashes"].items()):
        raise ValueError("original source or data differ")
    with (base/"study-recovery.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        missed=0
        while not (out/"terminal.json").exists():
            if alive(out/"study.lock"):
                missed=0
            else:
                missed+=1
            if missed>=2:
                if (out/"terminal.json").exists():break
                rec=base/"study-restarts.jsonl"
                with rec.open("a") as f:
                    f.write(json.dumps(dict(start_unix=time.time(),reason="original study writer lock remained vacant over two observations"))+"\n")
                with (base/"study-resumed.log").open("ab") as outputs:
                    p=subprocess.Popen([sys.executable,"-u",str(base/"study.py"),str(source),str(out)],
                        stdout=outputs,stderr=subprocess.STDOUT,env={**os.environ,"OMP_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","MKL_NUM_THREADS":"1"})
                    code=p.wait()
                with rec.open("a") as f:f.write(json.dumps(dict(exit_unix=time.time(),return_code=code))+"\n")
                if code and code not in (-15,-9,-1):
                    raise RuntimeError("original runner stopped with a reproducible error; see study-resumed.log")
                missed=0
            else:
                time.sleep(45)
        print("original study terminal",digest(out/"terminal.json"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("base",type=Path);p.add_argument("source",type=Path)
    a=p.parse_args();run(a.base.resolve(),a.source.resolve())
