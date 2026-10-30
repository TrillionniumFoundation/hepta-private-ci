"""Regression check for AOT timing without changing four-step optimizer results."""
import hashlib
import json
from pathlib import Path
import sys

import jax
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmarks.models import init_model,apply_model
from benchmarks.train import train_model as legacy_train
from next.common import train_model,strong_parameters,signature


def main():
    rng=np.random.default_rng(7)
    x=rng.normal(size=(64,8,3)).astype("float32")
    data=dict(x=x,dt=np.ones((64,8),"float32"),y=(x[:,0,0]>0).astype("int32"))
    rows=[]
    for kind in ("hcsn","sigmoid","gru","transformer"):
        initial=init_model(kind,jax.random.PRNGKey(7),3,8,2)
        strong=strong_parameters(initial)
        assert all(np.array_equal(np.asarray(initial[k]),np.asarray(strong[k])) for k in initial)
        old,_,old_timing=legacy_train(initial,kind,data,data,7,steps=4,eval_every=4)
        fn=lambda p,x,dt,k=kind:apply_model(p,x,dt,k)
        new,_,timing=train_model(initial,fn,data,data,7,steps=4,eval_every=4)
        error=max(float(np.max(np.abs(np.asarray(old[k])-np.asarray(new[k])))) for k in new)
        assert error<2e-6,(kind,error)
        rows.append(dict(kind=kind,max_parameter_abs_difference=error,
            strong_conversion_value_preserving=True,
            original_weak_leaf_count=sum(s[2] for s in signature(initial)),
            new_weak_leaf_count=sum(s[2] for s in signature(strong)),
            old_timing=old_timing,new_timing=timing))
    # Separate variable-length executable coverage, with no discarded updates.
    long=dict(x=np.tile(x,(1,2,1)),dt=np.ones((64,16),"float32"),y=data["y"])
    initial=init_model("hcsn",jax.random.PRNGKey(7),3,8,2)
    _,_,multiple=train_model(initial,lambda p,x,dt:apply_model(p,x,dt,"hcsn"),
                            [data,long],data,7,steps=4,eval_every=4)
    assert multiple["compiled_training_shapes"]==2
    result=dict(passed=True,scope="Software regression fixtures, not new task accuracy trials",
        rows=rows,multiple_shapes=multiple,
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (Path(__file__),Path(__file__).with_name("common.py"))})
    Path(__file__).with_name("training_validation.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"passed":True,"max_parameter_abs_difference":max(r["max_parameter_abs_difference"] for r in rows),
        "aot_training_shapes":multiple["compiled_training_shapes"],"applied_updates":4,
        "discarded_warmup_updates":multiple["warmup_optimizer_updates"]},indent=2))


if __name__=="__main__":
    main()
