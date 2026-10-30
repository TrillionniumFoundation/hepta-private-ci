"""Run the single predeclared v2 repair on fresh train/validation/test seeds."""

import json
import os
from pathlib import Path
import resource
import time
import numpy as np
import jax
import jax.numpy as jnp
from jax.example_libraries import optimizers
try:
    from .data import make_data,fingerprint,INPUT_DIM,OUTPUT_DIM
    from .models import parameter_count
    from .v2_models import init_model,apply_model,matched_width
    from .train import train_model,evaluate_dataset
    from .run_benchmarks import source_hashes,summarize
except ImportError:
    from data import make_data,fingerprint,INPUT_DIM,OUTPUT_DIM
    from models import parameter_count
    from v2_models import init_model,apply_model,matched_width
    from train import train_model,evaluate_dataset
    from run_benchmarks import source_hashes,summarize


def make_trainer(kind):
    init,update,get=optimizers.adam(.003)
    def loss_fn(p,x,dt,y):
        z=apply_model(p,x,dt,kind)
        return -jnp.mean(jax.nn.log_softmax(z)[jnp.arange(y.shape[0]),y])
    @jax.jit
    def step(i,state,x,dt,y):
        loss,g=jax.value_and_grad(loss_fn)(get(state),x,dt,y)
        norm=jnp.sqrt(sum(jnp.sum(a*a) for a in jax.tree_util.tree_leaves(g)))
        g=jax.tree_util.tree_map(lambda a:a*jnp.minimum(1.,1./(norm+1e-8)),g)
        return update(i,g,state),loss,norm
    @jax.jit
    def evaluate(p,x,dt,y):
        z=apply_model(p,x,dt,kind);prob=jax.nn.softmax(z)
        return (-jnp.mean(jax.nn.log_softmax(z)[jnp.arange(y.shape[0]),y]),
                jnp.mean(jnp.argmax(z,-1)==y),
                jnp.mean(jnp.sum((prob-jax.nn.one_hot(y,z.shape[-1]))**2,axis=-1)))
    return init,step,get,evaluate


def main():
    folder=Path(__file__).parent
    protocol=json.loads((folder/"v2_protocol.json").read_text())
    kinds=protocol["models"]
    trainers={kind:make_trainer(kind) for kind in kinds}
    rows=[]
    metadata=dict(protocol=protocol,source_hashes=source_hashes(),
        jax=jax.__version__,cpu_affinity=sorted(os.sched_getaffinity(0)),
        scope="One fixed v2 repair, fresh synthetic data; no backbone promotion implied")
    start=time.perf_counter()
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            base=900000+100*seed
            suite={"train":make_data(task,base,2048),"validation":make_data(task,base+1,512),
                   "test":make_data(task,base+2,512),"long":make_data(task,base+3,512,length=64)}
            hashes={k:fingerprint(v) for k,v in suite.items()}
            offset=seed%len(kinds)
            for kind in kinds[offset:]+kinds[:offset]:
                width,count=matched_width(kind,INPUT_DIM,OUTPUT_DIM)
                p=init_model(kind,jax.random.PRNGKey(2000+seed),INPUT_DIM,width,OUTPUT_DIM)
                assert parameter_count(p)==count,(kind,parameter_count(p),count)
                trained,history,timing=train_model(p,kind,suite["train"],suite["validation"],
                    9000+seed,steps=300,trainer=trainers[kind])
                evaluate=trainers[kind][3]
                metrics={k:evaluate_dataset(evaluate,trained,v) for k,v in suite.items() if k!="train"}
                batch=[jnp.asarray(suite["test"][k][:32]) for k in ("x","dt","y")]
                evaluate(trained,*batch)[0].block_until_ready()
                times=[]
                for _ in range(20):
                    tt=time.perf_counter();evaluate(trained,*batch)[0].block_until_ready()
                    times.append(1000*(time.perf_counter()-tt))
                state_count=3*width if kind in ("hcsn","sigmoid") else width if kind=="gru" else None
                row=dict(task=task,seed=seed,kind=kind,architecture_version=2,width=width,
                    parameter_count=count,persistent_state_scalars=state_count,
                    transformer_note="Full-sequence implementation, no streaming KV cache benchmark" if kind=="transformer" else None,
                    data_sha256=hashes,history=history,timing=timing,metrics=metrics,
                    latency_ms_batch32=float(np.median(times)),
                    process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                rows.append(row)
                payload=dict(metadata=metadata,runs=rows,summary=summarize(rows),complete=False,
                             elapsed_seconds=time.perf_counter()-start)
                (folder/"sequence_v2_results.json").write_text(json.dumps(payload,indent=2))
                print(json.dumps(dict(task=task,seed=seed,kind=kind,test=metrics["test"]["accuracy"],
                    long=metrics["long"]["accuracy"],params=count,state_scalars=state_count)),flush=True)
    payload["complete"]=True
    (folder/"sequence_v2_results.json").write_text(json.dumps(payload,indent=2))


if __name__=="__main__":
    main()
