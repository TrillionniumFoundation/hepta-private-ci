"""Run a fixed-budget, seed-paired sequence experiment and retain all results."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import time
import numpy as np
import jax
import jax.numpy as jnp

try:
    from .data import INPUT_DIM, OUTPUT_DIM, TASKS, dataset_suite, fingerprint
    from .models import KINDS, init_model, matched_width, parameter_count, apply_model
    from .train import make_trainer, train_model, evaluate_dataset
except ImportError:
    from data import INPUT_DIM, OUTPUT_DIM, TASKS, dataset_suite, fingerprint
    from models import KINDS, init_model, matched_width, parameter_count, apply_model
    from train import make_trainer, train_model, evaluate_dataset


def source_hashes():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))}


def gradient_check(kind,width):
    p=init_model(kind,jax.random.PRNGKey(99),INPUT_DIM,width,OUTPUT_DIM)
    x=jax.random.normal(jax.random.PRNGKey(101),(2,7,INPUT_DIM))*.2
    dt=jnp.ones((2,7))
    # Check a parameter in the actual temporal dynamics, not merely the readout.
    objective=lambda pp:jnp.sum(jnp.square(apply_model(pp,x,dt,kind)))
    grad=jax.grad(objective)(p)["inp"][0,0]
    epsilon=.002
    plus=dict(p);minus=dict(p)
    plus["inp"]=p["inp"].at[0,0].add(epsilon)
    minus["inp"]=p["inp"].at[0,0].add(-epsilon)
    fd=(objective(plus)-objective(minus))/(2*epsilon)
    return dict(autodiff=float(grad),finite_difference=float(fd),epsilon=epsilon,
                absolute_error=float(jnp.abs(grad-fd)),dtype="float32")


def summarize(rows):
    groups={}
    for row in rows:
        key=(row["task"],row["kind"])
        groups.setdefault(key,[]).append(row)
    result=[]
    for (task,kind),group in groups.items():
        entry=dict(task=task,kind=kind,seeds=[r["seed"] for r in group],
                   parameter_count=group[0]["parameter_count"])
        for split in group[0]["metrics"]:
            vals=np.array([r["metrics"][split]["accuracy"] for r in group])
            entry[split]=dict(mean_accuracy=float(vals.mean()),
                sample_sd=float(vals.std(ddof=1)) if len(vals)>1 else None,
                min_accuracy=float(vals.min()),max_accuracy=float(vals.max()))
        entry["mean_warm_training_seconds"]=float(np.mean([r["timing"]["warm_training_seconds"] for r in group]))
        entry["mean_latency_ms_batch32"]=float(np.mean([r["latency_ms_batch32"] for r in group]))
        result.append(entry)
    paired=[]
    for task in TASKS:
        for baseline in ("sigmoid","gru","transformer"):
            aa={r["seed"]:r for r in rows if r["task"]==task and r["kind"]=="hcsn"}
            bb={r["seed"]:r for r in rows if r["task"]==task and r["kind"]==baseline}
            seeds=sorted(set(aa)&set(bb))
            if seeds:
                deltas=np.array([aa[s]["metrics"]["test"]["accuracy"]-bb[s]["metrics"]["test"]["accuracy"] for s in seeds])
                paired.append(dict(task=task,baseline=baseline,seeds=seeds,
                    delta_per_seed=deltas.tolist(),mean_delta=float(deltas.mean()),
                    sample_sd=float(deltas.std(ddof=1)) if len(seeds)>1 else None))
    return dict(groups=result,paired_hcsn_minus_baseline=paired)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--steps",type=int,default=300)
    parser.add_argument("--seeds",type=int,default=5)
    parser.add_argument("--out",default="sequence_results.json")
    parser.add_argument("--tasks",nargs="+",default=list(TASKS))
    parser.add_argument("--kinds",nargs="+",default=list(KINDS))
    args=parser.parse_args()
    out=Path(args.out)
    rows=[]
    metadata=dict(scope="Synthetic sequence microbenchmarks; not LLM or multimodal pretraining",
        protocol=dict(parameter_budget=6200,steps=args.steps,batch_size=32,lr=.003,
                      seeds=list(range(args.seeds)),train_count=2048,eval_count=512,
                      train_length=32,ood_length=64,selection="lowest validation loss at steps 50,100,...",
                      tuning="No hyperparameter search; same learning rate/update budget for all models",
                      timing="Warm CPU update time excludes first update; evaluation JIT excluded from latency"),
        environment=dict(python=platform.python_version(),jax=jax.__version__,numpy=np.__version__,
                         devices=[str(x) for x in jax.devices()],cpu_affinity=sorted(os.sched_getaffinity(0))),
        source_hashes=source_hashes(),gradient_checks={})
    widths={kind:matched_width(kind,INPUT_DIM,OUTPUT_DIM) for kind in args.kinds}
    for kind,(width,count) in widths.items():
        actual=parameter_count(init_model(kind,jax.random.PRNGKey(0),INPUT_DIM,width,OUTPUT_DIM))
        assert actual==count,(kind,count,actual)
        metadata["gradient_checks"][kind]=gradient_check(kind,width)
    trainers={kind:make_trainer(kind) for kind in args.kinds}
    start_all=time.perf_counter()
    for task in args.tasks:
        for seed in range(args.seeds):
            suite=dataset_suite(task,seed)
            hashes={name:fingerprint(data) for name,data in suite.items()}
            # Rotate execution order to reduce association between model and CPU drift.
            kinds=list(args.kinds)
            offset=seed%len(kinds)
            for kind in kinds[offset:]+kinds[:offset]:
                width,count=widths[kind]
                p=init_model(kind,jax.random.PRNGKey(1000+seed),INPUT_DIM,width,OUTPUT_DIM)
                trained,history,timing=train_model(p,kind,suite["train"],suite["validation"],seed,
                    steps=args.steps,trainer=trainers[kind])
                evaluate=trainers[kind][3]
                metrics={name:evaluate_dataset(evaluate,trained,data) for name,data in suite.items() if name!="train"}
                batch=[jnp.asarray(suite["test"][k][:32]) for k in ("x","dt","y")]
                evaluate(trained,*batch)[0].block_until_ready()
                latencies=[]
                for _ in range(20):
                    begin=time.perf_counter();evaluate(trained,*batch)[0].block_until_ready()
                    latencies.append(1000*(time.perf_counter()-begin))
                row=dict(task=task,kind=kind,seed=seed,width=width,parameter_count=count,
                    data_sha256=hashes,history=history,timing=timing,metrics=metrics,
                    latency_ms_batch32=float(np.median(latencies)),
                    process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                rows.append(row)
                payload=dict(metadata=metadata,runs=rows,summary=summarize(rows),
                             elapsed_seconds=time.perf_counter()-start_all,complete=False)
                out.write_text(json.dumps(payload,indent=2))
                print(json.dumps(dict(task=task,seed=seed,kind=kind,
                    test=metrics["test"]["accuracy"],long=metrics["long"]["accuracy"],
                    seconds=timing["warm_training_seconds"])),flush=True)
    payload["complete"]=True
    out.write_text(json.dumps(payload,indent=2))


if __name__=="__main__":
    main()
