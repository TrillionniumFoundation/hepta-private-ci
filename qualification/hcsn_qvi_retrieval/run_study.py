"""Run freezes before held-out scoring. Never overwrite an attempt or its log."""

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MOD = "qualification.hcsn_qvi_retrieval.campaign"
ROOT = Path(__file__).parent
PLAN = json.loads((ROOT / "protocol.json").read_text())
ARMS = list(itertools.product(PLAN["modes"], PLAN["methods"], PLAN["seed"]))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path, data):
    with path.open("x") as fh:
        json.dump(data, fh, allow_nan=False, indent=2, sort_keys=True)
        fh.write("\n")


def run(phase, key, args, data, evidence):
    parent = evidence / phase
    parent.mkdir(parents=True, exist_ok=True)
    stem = parent / key
    output = stem.with_suffix(".json")
    log = stem.with_suffix(".log")
    cost = stem.with_suffix(".cost.json")
    if any(p.exists() for p in (output, log, cost)):
        raise FileExistsError(f"prior attempt exists for {stem}")
    env = {**os.environ, "OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1"}
    started = time.time()
    with log.open("xb") as fh:
        command = [sys.executable,"-m",MOD,phase,str(data),str(output),*args]
        proc = subprocess.run(command,env=env,stdout=fh,stderr=subprocess.STDOUT)
    finished=time.time()
    put(cost,dict(returncode=proc.returncode,wall_seconds=finished-started,start_unix=started,
                  end_unix=finished,log_sha=sha(log),output_sha=sha(output) if output.is_file() else None))
    if proc.returncode:
        raise RuntimeError(f"{key} exited {proc.returncode}; original {log}")
    print(phase, key, round(finished-started,3), flush=True)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=["diagnose","fit","confirm"])
    parser.add_argument("data",type=Path)
    parser.add_argument("evidence",type=Path)
    args=parser.parse_args()
    data,evidence=args.data.resolve(),args.evidence.resolve()
    evidence.mkdir(exist_ok=True,parents=True)
    seal=evidence/"selection_seal.json"
    if args.phase=="diagnose":
        for mode in PLAN["modes"]:
            seed=PLAN["seed"][0]
            run("diagnose",mode,["--mode", mode,"--seed",str(seed)],data,evidence)
        return
    if args.phase=="fit":
        if seal.exists(): raise FileExistsError(seal)
        done={}
        for mode,method,seed in ARMS:
            key=f"{mode}-{method}-{seed}"
            path=run("fit",key,["--mode",mode,"--method",method,"--seed",str(seed)],data,evidence)
            done[path.name]=sha(path)
        put(seal,{"files":done,"arms":ARMS,"protocol":sha(ROOT/"protocol.json"),
                  "fit_source":{p.name:sha(p) for p in ROOT.glob("*.py")} })
        return
    frozen=json.loads(seal.read_text())
    expected={f"{m}-{a}-{s}.json" for m,a,s in ARMS}
    if set(frozen["files"])!=expected or any(sha(evidence/"fit"/f)!=h for f,h in frozen["files"].items()):
        raise ValueError("selection seal missing a required fit or contents changed")
    for mode,method,seed in ARMS:
        key=f"{mode}-{method}-{seed}"
        run("confirm",key,["--seal",str(seal),"--fit",str(evidence/"fit"/(key+".json"))],data,evidence)


if __name__=="__main__":
    main()
