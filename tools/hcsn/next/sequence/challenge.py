"""New duration/capacity challenges evaluated on already selected v3 checkpoints."""
import hashlib
import json
from pathlib import Path
import sys

import jax
import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.data import make_data,fingerprint
from benchmarks.v2_models import apply_model as apply_v2
from next.common import predict_model,classification_metrics
from next.full_kernel import as_jax_table,full_gates
from next.sequence.models import apply_model
from next.sequence.with_operators import apply_operator_model


def retrieval(seed,count,length,associations,noise):
    rng=np.random.default_rng(seed)
    x=np.zeros((count,length,16),np.float32)
    labels=np.zeros(count,np.int32)
    for index in range(count):
        keys=rng.choice(8,associations,replace=False)
        values=rng.integers(0,4,associations)
        positions=np.sort(rng.choice(length-2,associations,replace=False))
        x[index,positions,keys]=1.
        x[index,positions,8+values]=1.
        x[index,positions,12]=1.
        query=rng.integers(associations)
        x[index,-1,keys[query]]=1.
        x[index,-1,13]=1.
        labels[index]=values[query]
    filler=x[:,:,12]+x[:,:,13]==0
    x[:,:,:12]+=(rng.normal(0,noise,x[:,:,:12].shape)*filler[:,:,None]).astype(np.float32)
    return dict(x=x,dt=np.ones((count,length),np.float32),y=labels)


def main():
    folder=Path(__file__).parent
    protocol=json.loads((folder/"challenge_protocol.json").read_text())
    trained=json.loads((folder/"results.json").read_text())
    assert trained["complete"]
    applies={kind:(lambda p,x,dt,k=kind:apply_model(p,x,dt,k))
             for kind in trained["metadata"]["protocol"]["models"]}
    all_trained=list(trained["runs"])
    reference=json.loads((folder/"v2_reference_results.json").read_text())
    full=json.loads((folder/"full_results.json").read_text())
    assert reference["complete"] and full["complete"]
    all_trained.extend(reference["runs"])
    all_trained.extend(full["runs"])
    table=as_jax_table(dict(np.load(ROOT/"next/full_kernel/baseline_table.npz")),jnp.float32)
    applies["hcsn_v2_reference"]=lambda p,x,dt:apply_v2(p,x,dt,"hcsn")
    applies["full_hx"]=lambda p,x,dt:apply_operator_model(p,x,dt,lambda z:full_gates(z,table))
    rows=[]
    for challenge_index,spec in enumerate(protocol["tasks"]):
        for seed in protocol["training_seeds"]:
            data_seed=protocol["data_seed_base"]+1000*seed+challenge_index
            if spec["trained_task"]=="memory":
                data=make_data("memory",data_seed,spec["examples"],length=spec["length"])
            else:
                data=retrieval(data_seed,spec["examples"],spec["length"],spec["associations"],spec["filler_noise"])
            for row in all_trained:
                if row["task"]!=spec["trained_task"] or row["seed"]!=seed:continue
                path=folder/row["checkpoint_file"]
                assert hashlib.sha256(path.read_bytes()).hexdigest()==row["checkpoint_sha256"]
                params={key:jnp.asarray(value) for key,value in np.load(path).items()}
                logits=predict_model(applies[row["kind"]],params,data,batch_size=32)
                metrics=classification_metrics(logits,data["y"])
                rows.append(dict(challenge=spec["name"],kind=row["kind"],seed=seed,
                    data_sha256=fingerprint(data),checkpoint_sha256=row["checkpoint_sha256"],metrics=metrics))
    summary=[]
    for spec in protocol["tasks"]:
        for kind in applies:
            values=[r["metrics"]["accuracy"] for r in rows if r["challenge"]==spec["name"] and r["kind"]==kind]
            summary.append(dict(challenge=spec["name"],kind=kind,mean=float(np.mean(values)),
                seed_sd=float(np.std(values,ddof=1)),min=float(np.min(values)),max=float(np.max(values))))
    result=dict(complete=True,protocol=protocol,runs=rows,summary=summary,
        variants=list(applies),
        source_sha256={name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
                       for name in ("challenge.py","challenge_protocol.json","models.py")},
        training_performed=False,checkpoint_reselection=False)
    (folder/"challenge_results.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
