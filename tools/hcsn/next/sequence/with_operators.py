"""The frozen v3 HCSN graph with one explicit operator injection point.

Used for full-model/legacy equivalence checks without modifying the already
executed v3 source. An injected financial table is fixed, not part of params.
"""
import jax
import jax.numpy as jnp


def apply_operator_model(p,x,dt,gate_fn):
    u=jnp.concatenate([x,jnp.log1p(dt)[...,None]],axis=-1)
    batch=x.shape[0];width=p["out"].shape[0]
    temperature=1.+15.*jax.nn.sigmoid(p["temperature"])
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
        positive=jax.nn.relu(incoming@p["write"]+p["write_bias"])
        square=positive*positive
        write=square/(1.+square)
        read=jnp.einsum("bs,bsh->bh",address,memory)
        features=read+jnp.tanh(p["read_current"])*hidden
        candidate=hidden@p["value"]+p["value_bias"]
        boundary=p["boundary"]+incoming@p["boundary_weights"]
        q,a=gate_fn(xx-boundary)
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
    initial=(jnp.zeros((batch,8,width),x.dtype),jnp.zeros((batch,width),x.dtype),
             jnp.zeros((batch,width),x.dtype))
    _,features=jax.lax.scan(step,initial,(u.swapaxes(0,1),dt.swapaxes(0,1)))
    return features[-1]@p["out"]+p["out_bias"]
