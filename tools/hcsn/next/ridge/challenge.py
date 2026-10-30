"""Frozen duration/capacity/noise challenges for selected v4 checkpoints."""
import json
from pathlib import Path
import sys

import jax.numpy as jnp
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from benchmarks.data import make_data,fingerprint
from next.common import predict_model,classification_metrics
from next.sequence.challenge import retrieval
from next.ridge.models import apply_model
from next.ridge.run import verify_freeze,sha


def main():
    verify_freeze()
    protocol=json.loads((HERE/"challenge_protocol.json").read_text())
    trained=json.loads((HERE/"results.json").read_text())
    if not trained["complete"]:raise RuntimeError("Training confirmation matrix incomplete")
    kinds=trained["metadata"]["protocol"]["models"]
    applies={kind:(lambda p,x,dt,k=kind:apply_model(p,x,dt,k)) for kind in kinds}
    rows=[]
    for challenge_index,spec in enumerate(protocol["tasks"]):
        for seed in protocol["training_seeds"]:
            data_seed=protocol["data_seed_base"]+1000*seed+challenge_index
            data=make_data("memory",data_seed,spec["examples"],spec["length"]) if spec["trained_task"]=="memory" else retrieval(
                data_seed,spec["examples"],spec["length"],spec["associations"],spec["filler_noise"])
            for row in trained["runs"]:
                if row["task"]!=spec["trained_task"] or row["seed"]!=seed:continue
                path=HERE/row["checkpoint_file"]
                if sha(path)!=row["checkpoint_sha256"]:raise RuntimeError("Checkpoint changed")
                params={key:jnp.asarray(value) for key,value in np.load(path).items()}
                logits=predict_model(applies[row["kind"]],params,data,batch_size=32)
                metrics=classification_metrics(logits,data["y"])
                result=dict(challenge=spec["name"],kind=row["kind"],seed=seed,
                    data_sha256=fingerprint(data),checkpoint_sha256=row["checkpoint_sha256"],metrics=metrics)
                rows.append(result)
                print(json.dumps(result),flush=True)
    summary=[]
    for spec in protocol["tasks"]:
        for kind in kinds:
            values=np.asarray([r["metrics"]["accuracy"] for r in rows if r["challenge"]==spec["name"] and r["kind"]==kind])
            summary.append(dict(challenge=spec["name"],kind=kind,mean=float(values.mean()),
                seed_sd=float(values.std(ddof=1)),min=float(values.min()),max=float(values.max())))
    payload=dict(complete=True,protocol=protocol,runs=rows,summary=summary,
        freeze_sha256=sha(HERE/"freeze.json"),training_performed=False,checkpoint_reselection=False)
    (HERE/"challenge_results.json").write_text(json.dumps(payload,indent=2)+"\n")


if __name__=="__main__":main()
