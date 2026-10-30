"""Same-graph gate controls and a frozen content bypass for new encoder probes."""
import jax
import jax.numpy as jnp

from benchmarks import v2_models
from next.ablation.models import init_model as init_full
from next.full_kernel import full_gates


KINDS = ("full_hx", "same_call_sigmoid", "ordinary_c1", "gru", "transformer")


def init_model(kind, key, input_dim, width, classes):
    if kind in ("gru", "transformer"):
        return v2_models.init_model(kind, key, input_dim, width, classes)
    if kind not in KINDS:
        raise ValueError(kind)
    return init_full("full", key, input_dim, width, classes)


def matched_width(kind, input_dim, classes, budget):
    base = kind if kind in ("gru", "transformer") else "hcsn"
    return v2_models.matched_width(base, input_dim, classes, budget)


def gates(z, kind, table):
    if kind == "ordinary_c1":
        bounded = z/jnp.hypot(z, 1.)
        q = .5 + .5*bounded*jnp.abs(bounded)
        positive = jax.nn.relu(-z)
        a = (positive/jnp.hypot(positive, 1.))**2
        return q, a
    q, a = full_gates(z, table)
    if kind == "same_call_sigmoid":
        q = jax.nn.sigmoid(2*z)
    return q, a


def apply_dynamic(p, x, dt, kind, table):
    if kind in ("gru", "transformer"):
        return v2_models.apply_model(p, x, dt, kind=kind)
    u = jnp.concatenate([x, jnp.log1p(dt)[..., None]], axis=-1)
    fast = .2+4.8*jax.nn.sigmoid(p["tau_fast"])
    slow = 2.+98.*jax.nn.sigmoid(p["tau_slow"])
    regen = 4.*jax.nn.sigmoid(p["regen"])
    recover = 6.*jax.nn.sigmoid(p["recover"])
    call = 2.*jax.nn.sigmoid(p["call"])

    def step(state, item):
        xx, yy, stored = state
        incoming, delta = item
        boundary = (p["boundary"]+incoming@p["boundary_weights"]
                    +jnp.tanh(p["memory_feedback"])*stored)
        score = -boundary
        read_gate, _ = gates(score, kind, table)
        _, write_shape = gates(-score, kind, table)
        write_gate = read_gate*write_shape
        q, a = gates(xx-boundary, kind, table)
        drive = 3.*jnp.tanh(incoming@p["inp"]+(2*q-1)@p["recurrent"]+p["bias"])
        ef = jnp.exp(-delta[:, None]/fast)
        xx = ef*xx+(1-ef)*(call*a+regen*q-yy+drive)
        es = jnp.exp(-delta[:, None]/slow)
        yy = es*yy+(1-es)*recover*q
        features = (read_gate*stored+jnp.tanh(p["read_fast"])*jnp.tanh(xx)
                    +jnp.tanh(p["read_slow"])*jnp.tanh(yy))
        candidate = jnp.tanh(incoming@p["candidate_weights"]+xx)
        stored = stored+write_gate*(candidate-stored)
        return (xx, yy, stored), features

    zero = jnp.zeros((x.shape[0], p["out"].shape[0]), dtype=x.dtype)
    _, features = jax.lax.scan(step, (zero, zero, zero),
                             (u.swapaxes(0, 1), dt.swapaxes(0, 1)))
    return features[-1]@p["out"]+p["out_bias"]


def make_apply(kind, table, linear=None):
    def apply(p, x, dt):
        logits = apply_dynamic(p, x, dt, kind, table)
        if linear is not None:
            logits = logits+x[:, -1]@linear["coef"].T+linear["intercept"]
        return logits
    return apply
