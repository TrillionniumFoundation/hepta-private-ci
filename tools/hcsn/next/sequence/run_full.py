"""Train the frozen full-HX numerical operator inside the unchanged v3 graph."""
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
from benchmarks.models import gate
from next.common import train_model,evaluate_model,measure_latency
from next.full_kernel import as_jax_table,full_gates
from next.sequence.models import init_model,apply_model,matched_width
from next.sequence.with_operators import apply_operator_model
from next.sequence.run import make_suite


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integration_checks(full_apply):
    rng=np.random.default_rng(2776)
    p=init_model("hcsn",jax.random.PRNGKey(4),16,8,4)
    x=jnp.asarray(rng.normal(size=(2,12,16)),jnp.float32)
    dt=jnp.asarray(rng.uniform(.1,2.,size=(2,12)),jnp.float32)
    old_apply=lambda p,x,dt:apply_model(p,x,dt,"hcsn")
    injected=lambda p,x,dt:apply_operator_model(p,x,dt,lambda z:gate(z,"hcsn"))
    old_z=jax.jit(old_apply)(p,x,dt)
    new_z=jax.jit(injected)(p,x,dt)
    error=float(jnp.max(jnp.abs(old_z-new_z)))
    assert error==0.,error
    original_grad=jax.grad(lambda p:jnp.sum(old_apply(p,x,dt)))(p)
    injected_grad=jax.grad(lambda p:jnp.sum(injected(p,x,dt)))(p)
    grad_error=max(float(jnp.max(jnp.abs(original_grad[name]-injected_grad[name]))) for name in p)
    assert grad_error==0.,grad_error
    full_z=jax.jit(full_apply)(p,x,dt)
    full_grad=jax.grad(lambda p:jnp.mean(full_apply(p,x,dt)**2))(p)
    norms={name:float(jnp.linalg.norm(g)) for name,g in full_grad.items()}
    assert np.isfinite(np.asarray(full_z)).all()
    assert all(np.isfinite(v) for v in norms.values())
    return dict(legacy_injection_logits_max_error=error,legacy_injection_gradient_max_error=grad_error,
        full_operator_short_bptt_finite=True,full_parameter_gradient_norms=norms)


def main():
    folder=Path(__file__).parent
    protocol=json.loads((folder/"protocol.json").read_text())
    full_protocol=json.loads((folder/"full_protocol.json").read_text())
    table_path=ROOT/full_protocol["table"]
    assert sha(table_path)==full_protocol["table_sha256"]
    table=as_jax_table(dict(np.load(table_path)),jnp.float32)
    full_apply=lambda p,x,dt:apply_operator_model(p,x,dt,lambda z:full_gates(z,table))
    checks=integration_checks(full_apply)
    metadata=dict(protocol=protocol,full_protocol=full_protocol,integration_checks=checks,
        fixed_operator_table_file_bytes=table_path.stat().st_size,
        fixed_operator_table_array_bytes=sum(int(a.size*a.dtype.itemsize)
                                            for a in jax.tree_util.tree_leaves(table)),
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),
            folder/"with_operators.py",folder/"models.py",folder/"run.py",ROOT/"next/common.py",
            ROOT/"next/full_kernel/kernel.py",ROOT/"next/full_kernel/tables.py"]})
    checkpoints=folder/"full_checkpoints";checkpoints.mkdir(exist_ok=True)
    rows=[];start=time.perf_counter()
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            train,suite,hashes=make_suite(task,seed,protocol)
            width,count=matched_width("hcsn",16,4,protocol["parameter_target"])
            params=init_model("hcsn",jax.random.PRNGKey(3000+seed),16,width,4)
            learned,history,timing=train_model(params,full_apply,train,suite["validation"],17000+seed,
                steps=protocol["updates"],batch_size=protocol["batch_size"],lr=protocol["learning_rate"])
            metrics={name:evaluate_model(full_apply,learned,data) for name,data in suite.items()}
            target=checkpoints/f"{task}_seed{seed}.npz"
            np.savez_compressed(target,**{key:np.asarray(val) for key,val in learned.items()})
            rows.append(dict(task=task,seed=seed,kind="full_hx",width=width,
                parameter_count=count,persistent_state_scalars=10*width,data_sha256=hashes,
                history=history,timing=timing,metrics=metrics,
                checkpoint_file=str(target.relative_to(folder)),checkpoint_sha256=sha(target),
                latency_test32_batch32=measure_latency(full_apply,learned,suite["test_32"],repeats=20)))
            payload=dict(metadata=metadata,runs=rows,complete=False,elapsed_seconds=time.perf_counter()-start)
            (folder/"full_results.json").write_text(json.dumps(payload,indent=2)+"\n")
            print(json.dumps(dict(task=task,seed=seed,accuracy={k:v["accuracy"] for k,v in metrics.items()},
                                 optimizer_seconds=timing["optimizer_execution_seconds"])),flush=True)
    payload["complete"]=True
    (folder/"full_results.json").write_text(json.dumps(payload,indent=2)+"\n")


if __name__=="__main__":
    main()
