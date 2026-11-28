"""Preserve original endpoints on notification; independently replay matched stages."""
from hashlib import sha256
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CELLS={f"{a}-{s}" for a in ("stationary","irreversible","returning","lif","sdpa") for s in (137,311,557)}
RUNG=("epoch1","time120","time900","time2600")


def digest(path):
    with path.open("rb") as f:
        return __import__("hashlib").file_digest(f,"sha256").hexdigest()


def run(study,data):
    out=study/"run"
    archive=study/"independent"
    where=study/"first-observed"
    where.mkdir(exist_ok=True)
    with (where/"observer.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        seen={}
        cmd=[sys.executable,"-u",str(study/"strict_replay.py"),str(out),str(data),str(study),
             str(study/"study.py"),str(archive)]
        while True:
            current={}
            for cell in sorted(CELLS):
                path=out/cell/"progress.json"
                if not path.exists():continue
                info=json.loads(path.read_text())
                current[cell]=set(info["history"])
                stored=where/cell
                stored.mkdir(exist_ok=True)
                for r in info["history"].values():
                    for name,expected in ((r["file"],r["weight_sha"]),(r["score_file"],r["score_sha"])):
                        if Path(name).name!=name:
                            raise ValueError("invalid first-observation filename")
                        key=(cell,name)
                        if key in seen:
                            if seen[key]!=expected:raise ValueError("progress changed a previous endpoint")
                            continue
                        dest=stored/name
                        try:os.link(path.parent/name,dest)
                        except FileExistsError:pass
                        if digest(dest)!=expected:
                            raise ValueError("first observed bytes differ at "+cell+"/"+name)
                        seen[key]=expected
            for tag in RUNG:
                flag=where/(tag+".verified")
                if not flag.exists() and set(current)==CELLS and all(tag in row for row in current.values()):
                    subprocess.run(cmd+["--development-only"],check=True)
                    with flag.open("x") as f:f.write(json.dumps(dict(tag=tag,when=time.time(),files=len(seen)))+"\n")
                    print("qualified development stage",tag,len(seen),flush=True)
            if (out/"terminal.json").exists():
                subprocess.run(cmd,check=True)
                print("verified original arrays",flush=True)
                return
            time.sleep(10)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("study",type=Path)
    parser.add_argument("data",type=Path)
    a=parser.parse_args()
    run(a.study,a.data)
