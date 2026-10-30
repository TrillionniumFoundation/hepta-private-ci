"""Validate C1 closing, autodiff and explicit-state bounds of the v3 operator."""
import hashlib
import json
from pathlib import Path
import sys

import jax
jax.config.update("jax_enable_x64",True)
import jax.numpy as jnp
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from next.sequence.models import init_model,apply_model,closed_write,matched_width,count_parameters


def main():
    rows=[]
    rng=np.random.default_rng(86213)
    x=jnp.asarray(rng.normal(size=(3,12,16)),dtype=jnp.float64)
    dt=jnp.asarray(rng.uniform(.05,2.,size=(3,12)),dtype=jnp.float64)
    for kind in ("hcsn","sigmoid","memory_only"):
        p=jax.tree_util.tree_map(lambda a:a.astype(jnp.float64),
            init_model(kind,jax.random.PRNGKey(7),16,8,4))
        def loss(params):
            z=apply_model(params,x,dt,kind)
            return jnp.mean(z*z)
        gradients=jax.grad(loss)(p)
        checks=[]
        for name in p:
            index=(0,)*p[name].ndim
            eps=1e-5
            plus=dict(p);minus=dict(p)
            plus[name]=p[name].at[index].add(eps)
            minus[name]=p[name].at[index].add(-eps)
            fd=float((loss(plus)-loss(minus))/(2*eps))
            ad=float(gradients[name][index])
            checks.append(dict(parameter=name,ad=ad,finite_difference=fd,absolute_error=abs(ad-fd)))
        maxerr=max(c["absolute_error"] for c in checks)
        huge=apply_model(p,x*1e6,dt*100.,kind)
        assert np.isfinite(np.asarray(huge)).all()
        assert maxerr<2e-7,(kind,maxerr)
        h,count=matched_width(kind,16,4)
        assert count_parameters(init_model(kind,jax.random.PRNGKey(0),16,h,4))==count
        rows.append(dict(kind=kind,checks=checks,max_gradient_absolute_error=maxerr,
            large_input_outputs_finite=True,parameters=count,width=h))
    scores=jnp.asarray([-1.,-1e-8,0.,1e-8,1.],dtype=jnp.float64)
    values=jax.vmap(closed_write)(scores)
    slopes=jax.vmap(jax.grad(closed_write))(scores)
    assert np.array_equal(np.asarray(values[:3]),np.zeros(3))
    assert np.array_equal(np.asarray(slopes[:3]),np.zeros(3))
    folder=Path(__file__).parent
    result=dict(passed=True,jax=jax.__version__,dtype="float64",runs=rows,
        write_gate=dict(scores=np.asarray(scores).tolist(),values=np.asarray(values).tolist(),
                        derivatives=np.asarray(slopes).tolist()),
        boundedness="Each memory scalar is a convex interpolation of its previous value and tanh(candidate), hence remains in [-1,1] from zero; learned financial-neuron parameters remain constrained and x/y bounds from the prior model apply",
        source_sha256={name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
                       for name in ("models.py","validate.py")},
        scope="Discrete implemented gradients; no claim of exact nonlinear ODE flow or stable long-time gradients")
    (folder/"validation.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"passed":True,"max_errors":{r["kind"]:r["max_gradient_absolute_error"] for r in rows}}))


if __name__=="__main__":
    main()
