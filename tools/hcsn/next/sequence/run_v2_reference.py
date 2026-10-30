"""Unchanged v2 under the same new data, curriculum and 600-update budget."""
import hashlib
import json
from pathlib import Path
import sys
import time

import jax
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.v2_models import init_model,apply_model,matched_width
from next.common import train_model,evaluate_model,measure_latency
from next.sequence.run import make_suite


def main():
    folder=Path(__file__).parent
    protocol=json.loads((folder/"protocol.json").read_text())
    apply=lambda p,x,dt:apply_model(p,x,dt,"hcsn")
    metadata=dict(protocol=protocol,architecture="Unchanged previously published HCSN v2",
        declaration="Added after initial v3 memory scores to isolate architecture from the changed curriculum/update budget; no v2 design or tuning changes",
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [Path(__file__),folder/"run.py",ROOT/"benchmarks/v2_models.py",ROOT/"next/common.py"]})
    checkpoints=folder/"v2_reference_checkpoints";checkpoints.mkdir(exist_ok=True)
    rows=[];start=time.perf_counter()
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            train,suite,hashes=make_suite(task,seed,protocol)
            width,count=matched_width("hcsn",16,4,protocol["parameter_target"])
            params=init_model("hcsn",jax.random.PRNGKey(3000+seed),16,width,4)
            learned,history,timing=train_model(params,apply,train,suite["validation"],17000+seed,
                steps=protocol["updates"],batch_size=protocol["batch_size"],lr=protocol["learning_rate"])
            metrics={name:evaluate_model(apply,learned,data) for name,data in suite.items()}
            target=checkpoints/f"{task}_seed{seed}.npz"
            np.savez_compressed(target,**{key:np.asarray(val) for key,val in learned.items()})
            rows.append(dict(task=task,seed=seed,kind="hcsn_v2_reference",width=width,
                parameter_count=count,persistent_state_scalars=3*width,data_sha256=hashes,
                history=history,timing=timing,metrics=metrics,
                checkpoint_file=str(target.relative_to(folder)),
                checkpoint_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                latency_test32_batch32=measure_latency(apply,learned,suite["test_32"],repeats=20)))
            payload=dict(metadata=metadata,runs=rows,complete=False,elapsed_seconds=time.perf_counter()-start)
            (folder/"v2_reference_results.json").write_text(json.dumps(payload,indent=2)+"\n")
            print(json.dumps(dict(task=task,seed=seed,accuracy={k:v["accuracy"] for k,v in metrics.items()})),flush=True)
    payload["complete"]=True
    (folder/"v2_reference_results.json").write_text(json.dumps(payload,indent=2)+"\n")


if __name__=="__main__":
    main()
