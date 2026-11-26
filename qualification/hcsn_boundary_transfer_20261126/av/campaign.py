"""Supervise cold workers and seal all candidates before any test scoring."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, payload):
    with path.open("x") as stream:
        json.dump(payload,stream,indent=2,sort_keys=True)
        stream.write("\n")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("stage", choices=("fit","confirm"))
    p.add_argument("work", type=Path)
    p.add_argument("data", type=Path)
    p.add_argument("--workers", type=int, default=4)
    args=p.parse_args()
    args.work.mkdir(exist_ok=True)
    arms="centered raw joint signed learned fixed attention gru lif diagonal linear".split()
    rows=list(itertools.product(arms,(6101,6102,6103)))
    random.Random(81082026).shuffle(rows)
    if args.stage == "confirm" and not (args.work/"seal.json").is_file():
        raise ValueError("global seal needed")
    def run(pair):
        arm,seed=pair
        stem=f"{arm}-{seed}"
        receipt=args.work/f"{stem}-{args.stage}-process.json"
        if receipt.exists():
            original=json.loads(receipt.read_text())
            if original["returncode"] == 0:
                return
            raise RuntimeError("failed attempt retained: "+stem)
        t=time.perf_counter()
        with (args.work/f"{stem}-{args.stage}.log").open("x") as log:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name("study.py")),args.stage,
                 str(args.work),str(args.data),arm,str(seed)],stdout=log,stderr=subprocess.STDOUT)
        row={"arm":arm,"seed":seed,"phase":args.stage,"wall_seconds":time.perf_counter()-t,
             "returncode":result.returncode}
        write(receipt,row)
        print(row,flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run,rows))
    if args.stage=="fit":
        seal={}
        for arm,seed in rows:
            stem=f"{arm}-{seed}"
            path=args.work/stem
            seal[stem]={"fit":digest(path/"fit.json"),"weights":digest(path/"weights.pt")}
        write(args.work/"seal.json",seal)
        print("Global seal",digest(args.work/"seal.json"),flush=True)

if __name__=="__main__":
    main()
