"""Fixed v3 experiment on fresh data; test never participates in training."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import jax
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.data import make_data,fingerprint
from next.common import train_model,evaluate_model,measure_latency
from next.sequence.models import init_model,apply_model,matched_width,count_parameters,state_count


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_suite(task,seed,protocol):
    base=protocol["data_seed_base"]+1000*seed
    count=protocol["training_examples_per_length"]
    eval_count=protocol["evaluation_examples"]
    training=[make_data(task,base+length,count,length=length)
              for length in protocol["training_lengths"]]
    suite={"validation":make_data(task,base+201,eval_count,length=32)}
    for length in protocol["heldout_lengths"]:
        suite[f"test_{length}"]=make_data(task,base+300+length,eval_count,length=length)
    if task=="irregular":
        suite["corrupt_32"]=make_data(task,base+500,eval_count,length=32,noise=.35,missing=.5)
    hashes={f"train_{length}":fingerprint(data)
            for length,data in zip(protocol["training_lengths"],training)}
    hashes.update({name:fingerprint(data) for name,data in suite.items()})
    return training,suite,hashes


def summarize(rows):
    groups=[]
    for task in ("memory","retrieval","irregular"):
        for kind in ("hcsn","sigmoid","memory_only","gru","transformer","snn"):
            group=[row for row in rows if row["task"]==task and row["kind"]==kind]
            if not group:continue
            metrics={}
            for split in group[0]["metrics"]:
                values=np.array([row["metrics"][split]["accuracy"] for row in group])
                metrics[split]=dict(mean=float(values.mean()),
                    seed_sd=float(values.std(ddof=1)) if len(values)>1 else None,
                    min=float(values.min()),max=float(values.max()))
            groups.append(dict(task=task,kind=kind,seeds=[r["seed"] for r in group],
                parameters=group[0]["parameter_count"],state_scalars=group[0]["persistent_state_scalars"],
                metrics=metrics,
                mean_optimizer_execution_seconds=float(np.mean([r["timing"]["optimizer_execution_seconds"] for r in group])),
                mean_compilation_seconds=float(np.mean([r["timing"]["compilation_seconds"] for r in group]))))
    return groups


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path(__file__).parent)
    args=parser.parse_args()
    folder=Path(__file__).parent
    protocol=json.loads((folder/"protocol.json").read_text())
    args.output.mkdir(parents=True,exist_ok=True)
    checkpoints=args.output/"checkpoints";checkpoints.mkdir(exist_ok=True)
    applies={kind:(lambda p,x,dt,k=kind:apply_model(p,x,dt,k)) for kind in protocol["models"]}
    metadata=dict(protocol=protocol,protocol_sha256=sha(folder/"protocol.json"),
        source_sha256={str(path.relative_to(ROOT)):sha(path) for path in
                      [folder/"models.py",folder/"run.py",ROOT/"next/common.py",
                       ROOT/"benchmarks/models.py",ROOT/"benchmarks/snn_models.py",ROOT/"benchmarks/data.py"]},
        jax=jax.__version__,numpy=np.__version__,cpu_affinity=sorted(os.sched_getaffinity(0)),
        evaluation_policy="All architectural choices frozen; checkpoints chosen only by validation loss",
        limitations=["One shared synthetic task family; no real-world or backbone superiority",
                     "Matched updates/data/approximately parameters, not state size or FLOPs",
                     "Common training timings include first AOT dispatch but no compilation or warmup updates"])
    rows=[];start=time.perf_counter()
    result=args.output/"results.json"
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            train,suite,hashes=make_suite(task,seed,protocol)
            offset=seed%len(protocol["models"])
            kinds=protocol["models"][offset:]+protocol["models"][:offset]
            for kind in kinds:
                width,count=matched_width(kind,16,4,protocol["parameter_target"])
                params=init_model(kind,jax.random.PRNGKey(3000+seed),16,width,4)
                assert count_parameters(params)==count
                learned,history,timing=train_model(params,applies[kind],train,suite["validation"],
                    17000+seed,steps=protocol["updates"],batch_size=protocol["batch_size"],
                    lr=protocol["learning_rate"])
                metrics={name:evaluate_model(applies[kind],learned,data) for name,data in suite.items()}
                target=checkpoints/f"{task}_{kind}_seed{seed}.npz"
                np.savez_compressed(target,**{name:np.asarray(value) for name,value in learned.items()})
                row=dict(task=task,kind=kind,seed=seed,width=width,parameter_count=count,
                    persistent_state_scalars=state_count(kind,width),data_sha256=hashes,
                    history=history,timing=timing,metrics=metrics,
                    latency_test32_batch32=measure_latency(applies[kind],learned,suite["test_32"],repeats=20),
                    checkpoint_file=str(target.relative_to(args.output)),checkpoint_sha256=sha(target))
                rows.append(row)
                payload=dict(metadata=metadata,runs=rows,summary=summarize(rows),complete=False,
                    elapsed_seconds=time.perf_counter()-start)
                result.write_text(json.dumps(payload,indent=2)+"\n")
                print(json.dumps(dict(task=task,seed=seed,kind=kind,
                    accuracy={key:val["accuracy"] for key,val in metrics.items()},
                    optimizer_seconds=timing["optimizer_execution_seconds"])),flush=True)
    payload["complete"]=True
    result.write_text(json.dumps(payload,indent=2)+"\n")


if __name__=="__main__":
    main()
