"""Bounded eight-slot associative memory with optional continuous neuron dynamics."""
from pathlib import Path
import sys

import jax
import jax.numpy as jnp
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from benchmarks import models as old
from benchmarks import snn_models

SLOTS=8
KINDS=("hcsn","sigmoid","memory_only","gru","transformer","snn")


def count_parameters(p):
    return sum(int(v.size) for v in jax.tree_util.tree_leaves(p))


def matched_width(kind,input_dim,output_dim,budget=6200):
    if kind in ("gru","transformer"):
        return old.matched_width(kind,input_dim,output_dim,budget)
    if kind=="snn":
        return snn_models.matched_width(input_dim,output_dim,budget)
    d,k=input_dim+1,output_dim
    extra=0 if kind=="memory_only" else 9
    constant=d*SLOTS+SLOTS+d+k+2+(0 if kind=="memory_only" else d)
    _,h,n=min((abs(h*h+(d+k+3+extra)*h+constant-budget),h,
               h*h+(d+k+3+extra)*h+constant) for h in range(4,129))
    return h,n


def init_model(kind,key,input_dim,hidden_dim,output_dim):
    if kind in ("gru","transformer"):
        return jax.tree_util.tree_map(lambda a:jnp.asarray(a,dtype=jnp.float32),
            old.init_model(kind,key,input_dim,hidden_dim,output_dim))
    if kind=="snn":
        return snn_models.init_model(key,input_dim,hidden_dim,output_dim)
    d,h,k=input_dim+1,hidden_dim,output_dim
    keys=iter(jax.random.split(key,10))
    def weight(a,b,gain=1.):
        return jax.random.normal(next(keys),(a,b),dtype=jnp.float32)*np.float32(gain/np.sqrt(a))
    def full(n,value):
        return jnp.full((n,),value,dtype=jnp.float32)
    p=dict(inp=weight(d,h),bias=full(h,0.),value=weight(h,h),value_bias=full(h,0.),
        key=weight(d,SLOTS),key_bias=full(SLOTS,0.),write=weight(d,1,.1),
        write_bias=full(1,.5),temperature=full(1,-1.),out=weight(h,k),
        out_bias=full(k,0.),read_current=full(h,.1))
    if kind!="memory_only":
        p.update(tau_fast=full(h,-1.5),tau_slow=full(h,-1.),regen=full(h,0.),
            recover=full(h,0.),call=full(h,-1.),recurrent_diag=full(h,0.),
            boundary=full(h,0.),boundary_weights=weight(d,1,.05),
            read_fast=full(h,.1),read_slow=full(h,.1))
    return p


def closed_write(score):
    """Ordinary C1 write gate, independent of financial operators."""
    positive=jax.nn.relu(score)
    square=positive*positive
    return square/(1.+square)


def apply_model(p,x,dt,kind):
    if kind in ("gru","transformer"):
        return old.apply_model(p,x,dt,kind)
    if kind=="snn":
        return snn_models.apply_model(p,x,dt)
    u=jnp.concatenate([x,jnp.log1p(dt)[...,None]],axis=-1)
    batch=x.shape[0];width=p["out"].shape[0]
    temperature=1.+15.*jax.nn.sigmoid(p["temperature"])
    if kind!="memory_only":
        fast=.2+4.8*jax.nn.sigmoid(p["tau_fast"])
        slow=2.+98.*jax.nn.sigmoid(p["tau_slow"])
        regen=4.*jax.nn.sigmoid(p["regen"])
        recover=6.*jax.nn.sigmoid(p["recover"])
        call=2.*jax.nn.sigmoid(p["call"])
    def step(state,item):
        memory,xx,yy=state
        incoming,delta=item
        hidden=jnp.tanh(incoming@p["inp"]+p["bias"])
        address=jax.nn.softmax(temperature*(incoming@p["key"]+p["key_bias"]),axis=-1)
        write=closed_write(incoming@p["write"]+p["write_bias"])
        # Query and key share a projection; no task marker is hard-coded.
        read=jnp.einsum("bs,bsh->bh",address,memory)
        features=read+jnp.tanh(p["read_current"])*hidden
        candidate=hidden@p["value"]+p["value_bias"]
        if kind!="memory_only":
            boundary=p["boundary"]+incoming@p["boundary_weights"]
            q,a=old.gate(xx-boundary,kind)
            drive=3.*jnp.tanh(hidden+.5*jnp.tanh(p["recurrent_diag"])*(2*q-1))
            ef=jnp.exp(-delta[:,None]/fast);es=jnp.exp(-delta[:,None]/slow)
            xx=ef*xx+(1.-ef)*(call*a+regen*q-yy+drive)
            yy=es*yy+(1.-es)*recover*q
            candidate=candidate+.1*jnp.tanh(xx)
            features=features+jnp.tanh(p["read_fast"])*jnp.tanh(xx)
            features=features+jnp.tanh(p["read_slow"])*jnp.tanh(yy)
        candidate=jnp.tanh(candidate)
        weights=write*address
        memory=memory+weights[...,None]*(candidate[:,None,:]-memory)
        return (memory,xx,yy),features
    initial=(jnp.zeros((batch,SLOTS,width),x.dtype),jnp.zeros((batch,width),x.dtype),
             jnp.zeros((batch,width),x.dtype))
    _,features=jax.lax.scan(step,initial,(u.swapaxes(0,1),dt.swapaxes(0,1)))
    return features[-1]@p["out"]+p["out_bias"]


def state_count(kind,width):
    if kind=="memory_only":return SLOTS*width
    if kind in ("hcsn","sigmoid"):return (SLOTS+2)*width
    if kind=="snn":return 3*width
    if kind=="gru":return width
    return None
