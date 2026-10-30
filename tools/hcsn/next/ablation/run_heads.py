"""Fixed complete-formula and component ablations on new shared encoder data."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.models import parameter_count
from benchmarks.v2_models import matched_width
from next.ablation.models import VARIANTS,init_model,apply_model,effective_states
from next.common import train_model,evaluate_model,predict_model,measure_latency
from next.full_kernel import as_jax_table


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("dataset",choices=("ag_news","cifar10"))
    parser.add_argument("--features",type=Path,required=True)
    args=parser.parse_args()
    output=Path(__file__).parent
    weights=output/(args.dataset+"_checkpoints");weights.mkdir(exist_ok=True)
    table_file=ROOT/"next/full_kernel/baseline_table.npz"
    table=as_jax_table(dict(np.load(table_file)),jnp.float32)
    raw=np.load(args.features)
    data={s:{k:raw[s+"_"+k] for k in ("x","dt","y")}
          for s in ("train","validation","test","corrupted_test")}
    classes=int(data["train"]["y"].max()+1);dimension=data["train"]["x"].shape[-1]
    width,_=matched_width("hcsn",dimension,classes,6000)
    sources=list(output.glob("*.py"))+[ROOT/"next/common.py"]+list((ROOT/"next/full_kernel").glob("*.py"))
    results={"metadata":{"dataset":args.dataset,"feature_sha256":sha(args.features),
        "protocol":json.loads((output/"protocol.json").read_text()),"width":width,
        "source_sha256":{str(p.relative_to(ROOT)):sha(p) for p in sources},
        "table_sha256":sha(table_file),"table_float32_bytes":sum(v.size*4 for v in table.values()),
        "jax":jax.__version__,"devices":str(jax.devices()),
        "data_shapes":{s:list(v["x"].shape) for s,v in data.items()}},"runs":[],"complete":False}
    started=time.perf_counter()
    for seed in range(5):
        # Rotate model order, fixed independent of any scores.
        order=VARIANTS[seed%len(VARIANTS):]+VARIANTS[:seed%len(VARIANTS)]
        for variant in order:
            fn=lambda p,x,dt,v=variant:apply_model(p,x,dt,v,table)
            initial=init_model(variant,jax.random.PRNGKey(seed),dimension,width,classes)
            learned,history,timing=train_model(initial,fn,data["train"],data["validation"],seed)
            metrics={s:evaluate_model(fn,learned,data[s]) for s in ("validation","test","corrupted_test")}
            checkpoint=weights/f"{variant}_seed{seed}.npz"
            np.savez_compressed(checkpoint,**{k:np.asarray(v) for k,v in learned.items()})
            predictions=predict_model(fn,learned,data["test"]).argmax(1).tolist()
            row=dict(variant=variant,seed=seed,parameter_count=parameter_count(initial),
                effective_persistent_state_scalars=effective_states(variant,width),
                metrics=metrics,timing=timing,history=history,
                latency_batch32=measure_latency(fn,learned,data["test"]),
                checkpoint_file=str(checkpoint.relative_to(output)),checkpoint_sha256=sha(checkpoint),
                test_predictions=predictions)
            results["runs"].append(row)
            (output/(args.dataset+"_results.json")).write_text(json.dumps(results,indent=2)+"\n")
            print(args.dataset,variant,seed,"test",metrics["test"]["accuracy"],flush=True)
    summary={}
    for variant in VARIANTS:
        rows=[r for r in results["runs"] if r["variant"]==variant]
        summary[variant]={s:{"mean":float(np.mean([r["metrics"][s]["accuracy"] for r in rows])),
            "sd":float(np.std([r["metrics"][s]["accuracy"] for r in rows],ddof=1))}
            for s in ("validation","test","corrupted_test")}
    results["summary"]=summary
    results["feature_sha_after_training"]=sha(args.features)
    assert results["feature_sha_after_training"]==results["metadata"]["feature_sha256"]
    results["elapsed_seconds"]=time.perf_counter()-started
    results["complete"]=True
    (output/(args.dataset+"_results.json")).write_text(json.dumps(results,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__":
    main()
