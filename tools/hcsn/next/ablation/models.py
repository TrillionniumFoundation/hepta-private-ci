"""Full financial table gates inside the existing v2 neural recurrence.

Financial parameters and their compiled table are fixed. The neural projection,
boundary coordinate, time constants, memory and weights are learned. This is
not a time-dependent solution of the financial stopping problem.
"""
import jax
import jax.numpy as jnp

from benchmarks import v2_models
from next.full_kernel import full_gates

VARIANTS=("full","full_sigmoid","no_call","no_recovery","static_boundary",
          "no_memory","memory_only")


def init_model(variant,key,input_dim,width,output_dim):
    if variant not in VARIANTS:
        raise ValueError(variant)
    params=v2_models.init_model("hcsn",key,input_dim,width,output_dim)
    remove=[]
    if variant=="no_call":
        remove+=["call"]
    if variant=="no_recovery":
        remove+=["tau_slow","recover","read_slow"]
    if variant=="static_boundary":
        remove+=["boundary_weights","memory_feedback"]
    if variant=="no_memory":
        remove+=["candidate_weights","memory_feedback"]
    if variant=="memory_only":
        remove+=["inp","recurrent","bias","tau_fast","tau_slow","regen",
                 "recover","call","read_fast","read_slow"]
    for name in remove:
        params.pop(name)
    return params


def ordinary_write(score):
    positive=jax.nn.relu(score)
    return positive*positive/(1+positive*positive)


def apply_model(p,x,dt,variant,table):
    u=jnp.concatenate([x,jnp.log1p(dt)[...,None]],axis=-1)
    batch=x.shape[0];width=p["out"].shape[0]
    dynamics=variant!="memory_only"
    recovery=dynamics and variant!="no_recovery"
    memory=variant!="no_memory"
    if dynamics:
        fast=.2+4.8*jax.nn.sigmoid(p["tau_fast"])
        regen=4.*jax.nn.sigmoid(p["regen"])
        call=0. if variant=="no_call" else 2.*jax.nn.sigmoid(p["call"])
    if recovery:
        slow=2.+98.*jax.nn.sigmoid(p["tau_slow"])
        recover=6.*jax.nn.sigmoid(p["recover"])
    def gates(z):
        if variant=="memory_only":
            return jax.nn.sigmoid(2*z),ordinary_write(-z)
        q,a=full_gates(z,table)
        if variant=="full_sigmoid":
            q=jax.nn.sigmoid(2*z)
        return q,a
    def step(state,item):
        xx,yy,stored=state
        incoming,delta=item
        boundary=p["boundary"]
        if variant!="static_boundary":
            boundary=boundary+incoming@p["boundary_weights"]
            if memory:
                boundary=boundary+jnp.tanh(p["memory_feedback"])*stored
        score=-boundary
        read_gate,_=gates(score)
        if variant in ("no_call","memory_only"):
            write_shape=ordinary_write(score)
        else:
            _,write_shape=gates(-score)
        write_gate=read_gate*write_shape
        if dynamics:
            q,a=gates(xx-boundary)
            drive=3.*jnp.tanh(incoming@p["inp"]+(2*q-1)@p["recurrent"]+p["bias"])
            ef=jnp.exp(-delta[:,None]/fast)
            xx=ef*xx+(1-ef)*(call*a+regen*q-yy+drive)
            if recovery:
                es=jnp.exp(-delta[:,None]/slow)
                yy=es*yy+(1-es)*(recover*q)
        features=read_gate*stored
        if dynamics:
            features=features+jnp.tanh(p["read_fast"])*jnp.tanh(xx)
        if recovery:
            features=features+jnp.tanh(p["read_slow"])*jnp.tanh(yy)
        if memory:
            candidate=jnp.tanh(incoming@p["candidate_weights"]+xx)
            stored=stored+write_gate*(candidate-stored)
        return (xx,yy,stored),features
    zero=jnp.zeros((batch,width),dtype=x.dtype)
    _,features=jax.lax.scan(step,(zero,zero,zero),(u.swapaxes(0,1),dt.swapaxes(0,1)))
    return features[-1]@p["out"]+p["out_bias"]


def effective_states(variant,width):
    return width*(1 if variant=="memory_only" else 2 if variant in ("no_memory","no_recovery") else 3)
