"""One predeclared HCSN-v2 repair: dynamic boundary and gated residual memory.

This is a new architecture, not the He--Xiong value formula's exact time flow.
The v1 files are intentionally unchanged. GRU and Transformer reuse v1 code.
"""

import jax
import jax.numpy as jnp
import numpy as np
try:
    from . import models as v1
except ImportError:
    import models as v1


def matched_width(kind,input_dim,output_dim,budget=6200):
    if kind not in ("hcsn","sigmoid"):
        return v1.matched_width(kind,input_dim,output_dim,budget)
    d,k=input_dim+1,output_dim
    _,h,n=min((abs(h*h+(3*d+k+10)*h+k-budget),h,h*h+(3*d+k+10)*h+k)
               for h in range(4,97))
    return h,n


def init_model(kind,key,input_dim,hidden_dim,output_dim):
    if kind not in ("hcsn","sigmoid"):
        return v1.init_model(kind,key,input_dim,hidden_dim,output_dim)
    d,h,k=input_dim+1,hidden_dim,output_dim
    keys=iter(jax.random.split(key,12))
    def weight(a,b,scale=1.):
        return jax.random.normal(next(keys),(a,b))*scale/np.sqrt(a)
    return dict(out=weight(h,k),out_bias=jnp.zeros(k),inp=weight(d,h),
        recurrent=weight(h,h,.2),boundary_weights=weight(d,h,.05),
        candidate_weights=weight(d,h),bias=jnp.zeros(h),boundary=jnp.full(h,-.2),
        tau_fast=jnp.full(h,-1.5),tau_slow=jnp.full(h,-1.),regen=jnp.zeros(h),
        recover=jnp.zeros(h),call=jnp.full(h,-1.),memory_feedback=jnp.zeros(h),
        read_fast=jnp.full(h,.1),read_slow=jnp.full(h,.1))


def apply_model(p,x,dt,kind):
    if kind not in ("hcsn","sigmoid"):
        return v1.apply_model(p,x,dt,kind)
    u=jnp.concatenate([x,jnp.log1p(dt)[...,None]],axis=-1)
    batch=x.shape[0];width=p["out"].shape[0]
    fast=.2+4.8*jax.nn.sigmoid(p["tau_fast"])
    slow=2.+98.*jax.nn.sigmoid(p["tau_slow"])
    regen=4.*jax.nn.sigmoid(p["regen"])
    recover=6.*jax.nn.sigmoid(p["recover"])
    call=2.*jax.nn.sigmoid(p["call"])
    def step(state,item):
        xx,yy,memory=state
        incoming,delta=item
        boundary=p["boundary"]+incoming@p["boundary_weights"]+jnp.tanh(p["memory_feedback"])*memory
        score=-boundary
        read_gate,_=v1.gate(score,kind)
        _,call_gate=v1.gate(-score,kind)
        write_gate=read_gate*call_gate
        # write_gate is exactly zero for score <= 0, with zero first derivative.
        q,a=v1.gate(xx-boundary,kind)
        drive=3.*jnp.tanh(incoming@p["inp"]+(2*q-1)@p["recurrent"]+p["bias"])
        ef=jnp.exp(-delta[:,None]/fast);es=jnp.exp(-delta[:,None]/slow)
        xx=ef*xx+(1-ef)*(call*a+regen*q-yy+drive)
        yy=es*yy+(1-es)*(recover*q)
        candidate=jnp.tanh(incoming@p["candidate_weights"]+xx)
        # Read old memory before writing current token; the query cannot erase it.
        features=read_gate*memory+jnp.tanh(p["read_fast"])*jnp.tanh(xx)+jnp.tanh(p["read_slow"])*jnp.tanh(yy)
        memory=memory+write_gate*(candidate-memory)
        return (xx,yy,memory),features
    initial=tuple(jnp.zeros((batch,width)) for _ in range(3))
    _,features=jax.lax.scan(step,initial,(u.swapaxes(0,1),dt.swapaxes(0,1)))
    return features[-1]@p["out"]+p["out_bias"]
