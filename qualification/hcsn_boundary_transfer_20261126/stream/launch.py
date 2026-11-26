"""Run independent one-thread slots, record launch-to-exit cost, seal all, then score."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ARMS = ("qvi_raw","qvi_centered","qvi_signed","qvi_joint","learned_centered",
        "fixed_centered","gru","lif","attention")
SEEDS = (601,1601,2601)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--data",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path);parser.add_argument("--workers",default=6,type=int)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    script=Path(__file__).with_name("run.py")
    def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    file_ids={p.name:digest(p) for p in (script,script.with_name("protocol.md"),Path(__file__))}
    slots=[(arm,seed) for seed in SEEDS for arm in ARMS]
    (output/"registration.json").write_text(json.dumps({"source_sha256":file_ids,"slots":slots,
        "workers":args.workers,"utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())},indent=2))
    available=sorted(os.sched_getaffinity(0))
    if args.workers>len(available):raise ValueError("insufficient CPU affinity")
    def execute(lane):
        core=available[lane]
        for arm,seed in slots[lane::args.workers]:
            cmd=["taskset","-c",str(core),sys.executable,str(script),"fit",
                 "--data",str(args.data),"--output",str(output),"--arm",arm,"--seed",str(seed)]
            start=time.perf_counter(); started=time.time()
            with (output/f"{arm}-{seed}.log").open("x") as log:
                p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=False)
            receipt={"arm":arm,"seed":seed,"affinity_cpu":core,"launch_epoch":started,
                     "exit":p.returncode,"launch_to_exit_s":time.perf_counter()-start}
            (output/f"{arm}-{seed}.receipt.json").write_text(json.dumps(receipt))
            print(receipt,flush=True)
            if p.returncode:raise RuntimeError(f"slot failed: {arm} {seed}")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(execute,range(args.workers)))
    if {p.name:digest(p) for p in (script,script.with_name("protocol.md"),Path(__file__))}!=file_ids:
        raise RuntimeError("runner source changed")
    subprocess.run([sys.executable,str(script),"confirm","--data",str(args.data),
        "--output",str(output)],check=True)
    print("ALL_COMPLETE",flush=True)


if __name__=="__main__":
    main()
