"""Bounded normalized Gram/cross-value associative memory, fixed ridge 0.01.

Keys and queries share a learned projection over every input coordinate.
No key IDs, task markers, value coordinates, or answers are hard-coded.
"""
from pathlib import Path
import sys

import jax
import jax.numpy as jnp
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks import models as old
from benchmarks import snn_models
from next.full_kernel import as_jax_table,full_gates

KEY_DIM=16
RIDGE=.01
KINDS=("full_hx","hcsn","sigmoid","ridge_memory_only","gru","transformer","snn")
_TABLE=None


def financial_table():
    global _TABLE
    if _TABLE is None:
        path=ROOT/"next/full_kernel/baseline_table.npz"
        _TABLE=as_jax_table(dict(np.load(path)),jnp.float32)
    return _TABLE


def count_parameters(params):
    return sum(int(a.size) for a in jax.tree_util.tree_leaves(params))


def matched_width(kind,input_dim,output_dim,budget=6200):
    if kind in ("gru","transformer"):
        return old.matched_width(kind,input_dim,output_dim,budget)
    if kind=="snn":return snn_models.matched_width(input_dim,output_dim,budget)
    d,k=input_dim+1,output_dim
    extra=0 if kind=="ridge_memory_only" else 9
    constant=d*KEY_DIM+KEY_DIM+d+1+k+(0 if kind=="ridge_memory_only" else d)
    _,h,n=min((abs(h*h+(d+k+3+extra)*h+constant-budget),h,
               h*h+(d+k+3+extra)*h+constant) for h in range(4,129))
    return h,n


def init_model(kind,key,input_dim,hidden_dim,output_dim):
    if kind in ("gru","transformer"):
        return jax.tree_util.tree_map(lambda a:jnp.asarray(a,dtype=jnp.float32),
            old.init_model(kind,key,input_dim,hidden_dim,output_dim))
    if kind=="snn":return snn_models.init_model(key,input_dim,hidden_dim,output_dim)
    d,h,k=input_dim+1,hidden_dim,output_dim
    keys=iter(jax.random.split(key,10))
    def weight(a,b,gain=1.):
        return jax.random.normal(next(keys),(a,b),dtype=jnp.float32)*np.float32(gain/np.sqrt(a))
    def full(n,value):return jnp.full((n,),value,dtype=jnp.float32)
    p=dict(inp=weight(d,h),bias=full(h,0.),value=weight(h,h),value_bias=full(h,0.),
        key=weight(d,KEY_DIM),key_bias=full(KEY_DIM,0.),write=weight(d,1,.1),
        write_bias=full(1,.5),out=weight(h,k),out_bias=full(k,0.),read_current=full(h,.1))
    if kind!="ridge_memory_only":
        p.update(tau_fast=full(h,-1.5),tau_slow=full(h,-1.),regen=full(h,0.),
            recover=full(h,0.),call=full(h,-1.),recurrent_diag=full(h,0.),
            boundary=full(h,0.),boundary_weights=weight(d,1,.05),
            read_fast=full(h,.1),read_slow=full(h,.1))
    return p


def closed_write(score):
    """The same relu(score)^2/(1+relu(score)^2), with safe extreme branches."""
    positive=jax.nn.relu(score)
    small=jnp.where(positive>1.,1.,positive)
    large=jnp.where(positive<1.,1.,positive)
    inverse=1./large
    return jnp.where(positive>1.,1./(1.+inverse*inverse),small*small/(1.+small*small))


def update_statistics(gram,cross,inverse_mass,key,value,write):
    """Normalized cumulative statistics; write=0 preserves all state exactly."""
    mass_next=inverse_mass/(1.+write*inverse_mass)
    alpha=write*mass_next
    kk=jnp.einsum("bi,bj->bij",key,key)
    kv=jnp.einsum("bi,bj->bij",key,value)
    gram=(1.-alpha[...,None])*gram+alpha[...,None]*kk
    cross=(1.-alpha[...,None])*cross+alpha[...,None]*kv
    return gram,cross,mass_next


def read_statistics(gram,cross,query):
    matrix=.5*(gram+jnp.swapaxes(gram,-1,-2))+RIDGE*jnp.eye(KEY_DIM,dtype=gram.dtype)
    fitted=jnp.linalg.solve(matrix,cross)
    return jnp.einsum("bi,bih->bh",query,fitted)


def apply_model(p,x,dt,kind,return_aux=False):
    if kind in ("gru","transformer"):return old.apply_model(p,x,dt,kind)
    if kind=="snn":return snn_models.apply_model(p,x,dt)
    u=jnp.concatenate([x,jnp.log1p(dt)[...,None]],axis=-1)
    batch=x.shape[0];width=p["out"].shape[0]
    if kind!="ridge_memory_only":
        fast=.2+4.8*jax.nn.sigmoid(p["tau_fast"])
        slow=2.+98.*jax.nn.sigmoid(p["tau_slow"])
        regen=4.*jax.nn.sigmoid(p["regen"])
        recover=6.*jax.nn.sigmoid(p["recover"])
        call=2.*jax.nn.sigmoid(p["call"])
    def token(xx,yy,incoming,delta):
        hidden=jnp.tanh(incoming@p["inp"]+p["bias"])
        key=jnp.tanh(incoming@p["key"]+p["key_bias"])/jnp.sqrt(jnp.asarray(KEY_DIM,x.dtype))
        candidate=hidden@p["value"]+p["value_bias"]
        current=jnp.tanh(p["read_current"])*hidden
        if kind!="ridge_memory_only":
            boundary=p["boundary"]+incoming@p["boundary_weights"]
            q,a=full_gates(xx-boundary,financial_table()) if kind=="full_hx" else old.gate(xx-boundary,kind)
            drive=3.*jnp.tanh(hidden+.5*jnp.tanh(p["recurrent_diag"])*(2*q-1))
            ef=jnp.exp(-delta[:,None]/fast);es=jnp.exp(-delta[:,None]/slow)
            xx=ef*xx+(1.-ef)*(call*a+regen*q-yy+drive)
            yy=es*yy+(1.-es)*recover*q
            candidate=candidate+.1*jnp.tanh(xx)
            current=current+jnp.tanh(p["read_fast"])*jnp.tanh(xx)
            current=current+jnp.tanh(p["read_slow"])*jnp.tanh(yy)
        return xx,yy,key,jnp.tanh(candidate),current
    def step(state,item):
        gram,cross,mass,xx,yy=state
        incoming,delta=item
        xx,yy,key,value,_=token(xx,yy,incoming,delta)
        write=closed_write(incoming@p["write"]+p["write_bias"])
        gram,cross,mass=update_statistics(gram,cross,mass,key,value,write)
        return (gram,cross,mass,xx,yy),None
    initial=(jnp.zeros((batch,KEY_DIM,KEY_DIM),x.dtype),jnp.zeros((batch,KEY_DIM,width),x.dtype),
        jnp.ones((batch,1),x.dtype),jnp.zeros((batch,width),x.dtype),jnp.zeros((batch,width),x.dtype))
    (gram,cross,mass,xx,yy),_=jax.lax.scan(step,initial,
        (u[:,:-1].swapaxes(0,1),dt[:,:-1].swapaxes(0,1)))
    # Sequence-to-one contract: final query reads prefix statistics before writing.
    xx,yy,query,_,current=token(xx,yy,u[:,-1],dt[:,-1])
    read=read_statistics(gram,cross,query)
    features=jnp.tanh(read)+current
    logits=features@p["out"]+p["out_bias"]
    if return_aux:return logits,dict(gram=gram,cross=cross,inverse_mass=mass,fast=xx,slow=yy,read=read)
    return logits


def state_count(kind,width):
    if kind=="gru":return width
    if kind=="transformer":return None
    if kind=="snn":return 3*width
    return KEY_DIM*KEY_DIM+KEY_DIM*width+1+(0 if kind=="ridge_memory_only" else 2*width)
