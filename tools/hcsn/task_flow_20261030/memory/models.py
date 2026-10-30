"""Projected normalized delta memory inside the existing HCSN content graph."""
from pathlib import Path
import sys

import jax
import jax.numpy as jnp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from next.ridge import models as prior
from third.memory import models as baseline

EPSILON = 1e-4
COLUMN_RADIUS = 8.0
VARIANTS = ("full_delta", "sigmoid_delta", "c1_delta", "full_fixed", "full_mass")


def matched_width(variant, input_dim, output_dim, budget=6200):
    if variant not in VARIANTS:
        raise ValueError(variant)
    return prior.matched_width("full_hx", input_dim, output_dim, budget)


def init_model(variant, key, input_dim, width, output_dim):
    if variant not in VARIANTS:
        raise ValueError(variant)
    return prior.init_model("full_hx", key, input_dim, width, output_dim)


def delta_update(memory, key, value, write):
    """A residual write followed by nonexpansive columnwise ball projection.

    For fixed key/value/write, the unprojected linear part has eigenvalues 1
    and 1-w*||k||²/(epsilon+||k||²), in [0,1]. Projection bounds each column
    by radius8. This is not a guarantee on gradients through learned keys.
    """
    prediction = jnp.einsum("bk,bkh->bh", key, memory)
    gain = write / (EPSILON + jnp.sum(key * key, axis=-1, keepdims=True))
    updated = memory + gain[..., None] * key[..., None] * (value - prediction)[:, None, :]
    squared = jnp.sum(updated * updated, axis=-2, keepdims=True)
    scale = jnp.sqrt(jnp.minimum(1., COLUMN_RADIUS ** 2 / jnp.maximum(squared, 1e-20)))
    return updated * scale


def initial_state(params, batch, dtype=jnp.float32):
    width = params["out"].shape[0]
    return (jnp.zeros((batch, prior.KEY_DIM, width), dtype),
            jnp.zeros((batch, width), dtype), jnp.zeros((batch, width), dtype))


def token(params, xx, yy, incoming, delta, name):
    """Unchanged learned projections and fast/slow event dynamics."""
    p = params
    hidden = jnp.tanh(incoming @ p["inp"] + p["bias"])
    key = jnp.tanh(incoming @ p["key"] + p["key_bias"]) / jnp.sqrt(
        jnp.asarray(prior.KEY_DIM, incoming.dtype))
    candidate = hidden @ p["value"] + p["value_bias"]
    boundary = p["boundary"] + incoming @ p["boundary_weights"]
    q, a = baseline.gates(xx - boundary, name)
    drive = 3. * jnp.tanh(hidden + .5 * jnp.tanh(p["recurrent_diag"]) * (2 * q - 1))
    fast = .2 + 4.8 * jax.nn.sigmoid(p["tau_fast"])
    slow = 2. + 98. * jax.nn.sigmoid(p["tau_slow"])
    ef, es = jnp.exp(-delta[:, None] / fast), jnp.exp(-delta[:, None] / slow)
    xx = ef * xx + (1 - ef) * (2. * jax.nn.sigmoid(p["call"]) * a
         + 4. * jax.nn.sigmoid(p["regen"]) * q - yy + drive)
    yy = es * yy + (1 - es) * 6. * jax.nn.sigmoid(p["recover"]) * q
    candidate = jnp.tanh(candidate + .1 * jnp.tanh(xx))
    current = (jnp.tanh(p["read_current"]) * hidden
               + jnp.tanh(p["read_fast"]) * jnp.tanh(xx)
               + jnp.tanh(p["read_slow"]) * jnp.tanh(yy))
    return xx, yy, key, candidate, current


def step(params, state, x, dt, variant="full_delta", write_memory=True):
    """Process one observation; this is an event API, not no-observation flow."""
    if variant not in VARIANTS[:3]:
        raise ValueError("step is defined for the three delta variants")
    memory, xx, yy = state
    incoming = jnp.concatenate([x, jnp.log1p(dt)[:, None]], axis=-1)
    xx, yy, key, value, current = token(params, xx, yy, incoming, dt, variant.split("_")[0])
    read = jnp.einsum("bk,bkh->bh", key, memory)
    logits = (jnp.tanh(read) + current) @ params["out"] + params["out_bias"]
    write = prior.closed_write(incoming @ params["write"] + params["write_bias"])
    if write_memory:
        memory = delta_update(memory, key, value, write)
    return logits, (memory, xx, yy), dict(read=read, key=key, write=write)


def apply_model(params, x, dt, variant, return_aux=False):
    if variant in VARIANTS[3:]:
        return baseline.apply_model(params, x, dt, variant, return_aux)
    if variant not in VARIANTS[:3]:
        raise ValueError(variant)
    def advance(state, item):
        _, state, _ = step(params, state, item[0], item[1], variant)
        return state, None
    state, _ = jax.lax.scan(advance, initial_state(params, len(x), x.dtype),
                            (x[:, :-1].swapaxes(0, 1), dt[:, :-1].swapaxes(0, 1)))
    logits, state, aux = step(params, state, x[:, -1], dt[:, -1], variant, False)
    if return_aux:
        aux.update(memory=state[0], fast=state[1], slow=state[2])
        return logits, aux
    return logits


def resources(variant, width):
    if variant in VARIANTS[3:]:
        return baseline.resources(variant, width)
    return dict(persistent_state_scalars=prior.KEY_DIM * width + 2 * width,
                shared_fixed_operator_bytes=sum(a.nbytes for a in prior.financial_table().values())
                if variant.startswith(("full", "sigmoid")) else 0,
                final_query_solve=False, column_radius=COLUMN_RADIUS)
