"""Gradient and zero-write-region checks for the independently defined v2."""

import json
from pathlib import Path
import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
try:
    from .v2_models import init_model,apply_model
    from .models import gate
except ImportError:
    from v2_models import init_model,apply_model
    from models import gate


def main():
    rows=[];write_checks=[]
    for kind in ("hcsn","sigmoid"):
        p=init_model(kind,jax.random.PRNGKey(71),5,8,3)
        x=jax.random.normal(jax.random.PRNGKey(72),(3,13,5))*.2
        dt=jnp.linspace(.1,1.5,39).reshape(3,13)
        fn=lambda pp:jnp.sum(apply_model(pp,x,dt,kind)**2)
        grads=jax.grad(fn)(p)
        for name,index in [("inp",(0,0)),("boundary_weights",(0,0)),
                           ("candidate_weights",(0,0)),("boundary",(0,)),
                           ("memory_feedback",(0,)),("tau_fast",(0,)),("tau_slow",(0,))]:
            eps=1e-5
            plus=dict(p);minus=dict(p)
            plus[name]=p[name].at[index].add(eps);minus[name]=p[name].at[index].add(-eps)
            fd=(fn(plus)-fn(minus))/(2*eps)
            analytic=grads[name][index]
            err=float(jnp.abs(fd-analytic))
            rows.append(dict(kind=kind,parameter=name,autodiff=float(analytic),
                             finite_difference=float(fd),absolute_error=err))
            assert err<2e-5,rows[-1]
        write=lambda s:gate(s,kind)[0]*gate(-s,kind)[1]
        for s in (-10.,-1.,-1e-6,0.,1e-6,1.,10.):
            value=float(write(jnp.array(s)));derivative=float(jax.grad(write)(jnp.array(s)))
            if s<=0:
                assert value==0. and derivative==0.
            assert 0<=value<=1.
            write_checks.append(dict(kind=kind,score=s,value=value,derivative=derivative))
        stress=apply_model(p,x*1e6,dt*100,kind)
        assert bool(jnp.all(jnp.isfinite(stress)))
    out=dict(passed=True,dtype="float64",epsilon=1e-5,checks=rows,write_gate_checks=write_checks,
             max_absolute_error=max(r["absolute_error"] for r in rows),
             scope="Executed frozen-gate discrete v2 update, not exact nonlinear ODE flow")
    Path(__file__).with_name("gradient_v2_validation.json").write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))


if __name__=="__main__":
    main()
