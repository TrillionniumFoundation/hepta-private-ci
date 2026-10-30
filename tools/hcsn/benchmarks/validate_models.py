"""Independent float64 finite-difference checks of the executed model graphs."""

import json
from pathlib import Path
import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
try:
    from .models import init_model, apply_model, gate, KINDS
except ImportError:
    from models import init_model, apply_model, gate, KINDS


def main():
    rows=[]
    for kind in KINDS:
        p=init_model(kind,jax.random.PRNGKey(912),5,8,3)
        x=jax.random.normal(jax.random.PRNGKey(82),(3,11,5))*.3
        dt=jnp.linspace(.2,1.3,33).reshape(3,11)
        fn=lambda pp:jnp.sum(jnp.square(apply_model(pp,x,dt,kind)))
        grad=jax.grad(fn)(p)
        selected=[("inp",(0,0)),("recurrent",(0,0))] if kind!="transformer" else [("inp",(0,0)),("query",(0,0))]
        if kind in ("hcsn","sigmoid"):
            selected += [("boundary",(0,)),("tau_fast",(0,)),("tau_slow",(0,))]
        for name,index in selected:
            eps=1e-5
            plus=dict(p);minus=dict(p)
            plus[name]=p[name].at[index].add(eps)
            minus[name]=p[name].at[index].add(-eps)
            numeric=(fn(plus)-fn(minus))/(2*eps)
            analytic=grad[name][index]
            err=float(jnp.abs(numeric-analytic))
            rows.append(dict(kind=kind,parameter=name,index=index,analytic=float(analytic),
                             finite_difference=float(numeric),absolute_error=err))
            assert err < 2e-5,rows[-1]
    gate_rows=[]
    for kind in ("hcsn","sigmoid"):
        q_grad=float(jax.grad(lambda z:gate(z,kind)[0])(jnp.array(0.)))
        call_grad=float(jax.grad(lambda z:gate(z,kind)[1])(jnp.array(0.)))
        assert abs(q_grad-.5)<1e-12 and abs(call_grad)<1e-12
        neighbors=[]
        for xx in (-1e-6,0.,1e-6):
            actual=jax.grad(lambda z:gate(z,kind)[0])(jnp.array(xx))
            prob=jax.nn.sigmoid(2*xx)
            expected=.5*jnp.exp(-abs(xx)) if kind=="hcsn" else 2*prob*(1-prob)
            assert float(jnp.abs(actual-expected))<1e-12
            neighbors.append(dict(x=xx,actual=float(actual),expected=float(expected)))
        gate_rows.append(dict(kind=kind,q_gradient_at_boundary=q_grad,call_gradient_at_boundary=call_grad,
                             boundary_neighbors=neighbors))
    result=dict(dtype="float64",epsilon=1e-5,checks=rows,gate_checks=gate_rows,
                max_absolute_error=max(x["absolute_error"] for x in rows),passed=True,
                scope="Gradients of executed discrete update, not exact nonlinear ODE flow")
    out=Path(__file__).with_name("gradient_validation.json")
    out.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
