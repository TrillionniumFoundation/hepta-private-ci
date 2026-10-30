"""Small JAX reference models, not production kernels or a Mamba reproduction."""

import jax
import jax.numpy as jnp
import numpy as np


KINDS = ("hcsn", "sigmoid", "gru", "transformer")


def init_model(kind, key, input_dim, hidden_dim, output_dim):
    """Return a plain parameter pytree; all models receive log(1+dt)."""
    if kind not in KINDS:
        raise ValueError(kind)
    d, h, k = input_dim + 1, hidden_dim, output_dim
    keys = iter(jax.random.split(key, 20))
    def weight(a, b, scale=1.):
        return jax.random.normal(next(keys), (a, b)) * (scale / np.sqrt(a))
    p = {"out": weight(h, k), "out_bias": jnp.zeros(k)}
    if kind in ("hcsn", "sigmoid"):
        p.update(inp=weight(d, h), recurrent=weight(h, h, .2),
                 bias=jnp.zeros(h), boundary=jnp.zeros(h),
                 tau_fast=jnp.full(h, -1.5), tau_slow=jnp.full(h, -1.),
                 regen=jnp.full(h, 0.), recover=jnp.full(h, 0.),
                 call=jnp.full(h, -1.), read_y=weight(h, h, .1))
    elif kind == "gru":
        p.update(inp=weight(d, 3*h), recurrent=weight(h, 3*h, .5),
                 bias=jnp.zeros(3*h))
    else:
        p.update(inp=weight(d, h), bias=jnp.zeros(h), query=weight(h, h),
                 key=weight(h, h), value=weight(h, h), attention_out=weight(h, h),
                 ff1=weight(h, 2*h), ff1_bias=jnp.zeros(2*h),
                 ff2=weight(2*h, h), ff2_bias=jnp.zeros(h),
                 norm1_scale=jnp.ones(h), norm1_bias=jnp.zeros(h),
                 norm2_scale=jnp.ones(h), norm2_bias=jnp.zeros(h))
    return p


def parameter_count(params):
    return sum(int(x.size) for x in jax.tree_util.tree_leaves(params))


def matched_width(kind, input_dim, output_dim, budget=6200):
    """Nearest discrete width, chosen before training using parameter count only."""
    counts = []
    d, k = input_dim+1, output_dim
    for width in range(4, 97):
        if kind in ("hcsn", "sigmoid"):
            n=2*width**2+(d+k+7)*width+k
        elif kind == "gru":
            n=3*width**2+(3*d+3+k)*width+k
        elif kind == "transformer":
            n=8*width**2+(d+k+8)*width+k
        else:
            raise ValueError(kind)
        counts.append((abs(n-budget), width, n))
    _, width, count = min(counts)
    return width, count


def gate(x, kind):
    e = jnp.exp(-jnp.abs(x))
    q = jnp.where(x < 0, .5*e, 1-.5*e)
    if kind == "sigmoid":
        # Matches q(0)=1/2 and q'(0)=1/2, changing only the put activation.
        q = jax.nn.sigmoid(2*x)
    restoring = jnp.where(x < 0, 1-2*e/(1+e*e), 0.)
    return q, restoring


def _norm(x, scale, bias):
    return (x-jnp.mean(x, -1, keepdims=True)) * jax.lax.rsqrt(
        jnp.var(x, -1, keepdims=True)+1e-5) * scale+bias


def apply_model(params, x, dt, kind):
    """x=(batch,time,features), dt=(batch,time) -> logits=(batch,classes)."""
    p = params
    u = jnp.concatenate([x, jnp.log1p(dt)[..., None]], axis=-1)
    batch, length, _ = u.shape
    width = p["out"].shape[0]
    if kind in ("hcsn", "sigmoid"):
        fast = .2+4.8*jax.nn.sigmoid(p["tau_fast"])
        slow = 2.+98.*jax.nn.sigmoid(p["tau_slow"])
        regen = 4.*jax.nn.sigmoid(p["regen"])
        recover = 6.*jax.nn.sigmoid(p["recover"])
        call = 2.*jax.nn.sigmoid(p["call"])
        def step(state, item):
            xx, yy = state
            incoming, delta = item
            q, a = gate(xx-p["boundary"], kind)
            drive = 3.*jnp.tanh(incoming@p["inp"]+(2*q-1)@p["recurrent"]+p["bias"])
            ef = jnp.exp(-delta[:, None]/fast)
            es = jnp.exp(-delta[:, None]/slow)
            # Frozen-gate exponential step: not the exact nonlinear ODE flow.
            xx = ef*xx+(1-ef)*(call*a+regen*q-yy+drive)
            yy = es*yy+(1-es)*(recover*q)
            return (xx, yy), None
        (xx, yy), _ = jax.lax.scan(step, (jnp.zeros((batch,width)), jnp.zeros((batch,width))),
                                    (u.swapaxes(0,1), dt.swapaxes(0,1)))
        features = jnp.tanh(xx-p["boundary"])+jnp.tanh(yy)@p["read_y"]
    elif kind == "gru":
        def step(state, incoming):
            proj = incoming@p["inp"]+p["bias"]
            rec = state@p["recurrent"]
            z = jax.nn.sigmoid(proj[:,:width]+rec[:,:width])
            r = jax.nn.sigmoid(proj[:,width:2*width]+rec[:,width:2*width])
            cand = jnp.tanh(proj[:,2*width:]+r*rec[:,2*width:])
            state = (1-z)*state+z*cand
            return state, None
        features, _ = jax.lax.scan(step, jnp.zeros((batch,width)), u.swapaxes(0,1))
    elif kind == "transformer":
        t = jnp.arange(length)[:,None]
        freq = jnp.exp(-jnp.log(10000.)*jnp.arange(0,width,2)/width)
        phase = t*freq
        pos = jnp.stack([jnp.sin(phase),jnp.cos(phase)],axis=-1).reshape(length,-1)[:,:width]
        z = u@p["inp"]+p["bias"]+.2*pos
        norm = _norm(z,p["norm1_scale"],p["norm1_bias"])
        q, k, v = norm@p["query"], norm@p["key"], norm@p["value"]
        scores = jnp.einsum("btd,bsd->bts",q,k)/jnp.sqrt(width)
        weights = jax.nn.softmax(scores, axis=-1)
        z = z+jnp.einsum("bts,bsd->btd",weights,v)@p["attention_out"]
        norm = _norm(z,p["norm2_scale"],p["norm2_bias"])
        z = z+jax.nn.gelu(norm@p["ff1"]+p["ff1_bias"])@p["ff2"]+p["ff2_bias"]
        features = z[:,-1]
    else:
        raise ValueError(kind)
    return features@p["out"]+p["out_bias"]
