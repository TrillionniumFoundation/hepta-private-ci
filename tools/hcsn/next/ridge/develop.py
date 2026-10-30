"""Small development-only sanity matrix; no confirmation test is constructed."""
import hashlib
import json
from pathlib import Path
import sys
import time

import jax
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.data import make_data,fingerprint
from next.common import train_model,evaluate_model
from next.ridge.models import init_model,apply_model,matched_width,count_parameters,state_count


def main():
    protocol=json.loads((HERE/"development_protocol.json").read_text())
    rows=[];started=time.perf_counter()
    for task_index,task in enumerate(protocol["tasks"]):
        base=protocol["data_seed_base"]+1000*task_index
        training=[make_data(task,base+length,protocol["training_examples_per_length"],length)
                  for length in protocol["training_lengths"]]
        validation=make_data(task,base+201,protocol["validation_examples"],32)
        for kind in protocol["models"]:
            apply=lambda p,x,dt,k=kind:apply_model(p,x,dt,k)
            width,count=matched_width(kind,16,4,protocol["parameter_target"])
            params=init_model(kind,jax.random.PRNGKey(3137),16,width,4)
            assert count_parameters(params)==count
            learned,history,timing=train_model(params,apply,training,validation,17137,
                steps=protocol["updates"],batch_size=protocol["batch_size"],lr=protocol["learning_rate"])
            row=dict(task=task,kind=kind,width=width,parameters=count,persistent_state_scalars=state_count(kind,width),
                     history=history,timing=timing,validation=evaluate_model(apply,learned,validation),
                     train_sha256=[fingerprint(x) for x in training],validation_sha256=fingerprint(validation))
            rows.append(row)
            result=dict(protocol=protocol,runs=rows,complete=False,confirmation_test_constructed=False,
                source_sha256={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in HERE.glob("*.py")},
                elapsed_seconds=time.perf_counter()-started)
            (HERE/"development_results.json").write_text(json.dumps(result,indent=2)+"\n")
            print(task,kind,row["validation"],flush=True)
    result["complete"]=True
    result["sanity_targets_passed"]=all(r["validation"]["accuracy"]>=protocol["development_sanity_targets"][r["task"]+"_validation"] for r in rows)
    (HERE/"development_results.json").write_text(json.dumps(result,indent=2)+"\n")
    print('SANITY',result["sanity_targets_passed"],flush=True)


if __name__=="__main__":main()
