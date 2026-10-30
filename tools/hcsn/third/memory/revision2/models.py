"""Same-graph gate controls and two explicitly different ridge conventions."""
from pathlib import Path
import sys

import jax
import jax.numpy as jnp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from next.ridge import models as prior
from next.full_kernel import full_gates


def family(variant):
    name, mode = variant.split("_")
    if name not in ("full", "sigmoid", "c1", "memory") or mode not in ("fixed", "mass"):
        raise ValueError(variant)
    return name, mode


def matched_width(variant, input_dim, output_dim, budget=6200):
    name, _ = family(variant)
    return prior.matched_width("ridge_memory_only" if name == "memory" else "full_hx",
                               input_dim, output_dim, budget)


def init_model(variant, key, input_dim, width, output_dim):
    name, _ = family(variant)
    return prior.init_model("ridge_memory_only" if name == "memory" else "full_hx",
                            key, input_dim, width, output_dim)


def gates(z, name):
    if name == "c1":
        magnitude = prior.closed_write(jnp.abs(z))
        q = .5 + .5 * jnp.where(z < 0, -magnitude, magnitude)
        return q, prior.closed_write(-z)
    q, a = full_gates(z, prior.financial_table())
    return (jax.nn.sigmoid(2 * z) if name == "sigmoid" else q), a


def read_statistics(gram, cross, inverse_mass, query, mode):
    if not jax.config.x64_enabled:
        raise RuntimeError("This declared mixed-precision solver requires JAX x64 enabled")
    g, h, r, q = (jnp.asarray(a, jnp.float64) for a in (gram, cross, inverse_mass, query))
    ridge = prior.RIDGE * (r if mode == "mass" else jnp.ones_like(r))
    matrix = .5 * (g + g.swapaxes(-1, -2)) + ridge[..., None] * jnp.eye(
        prior.KEY_DIM, dtype=jnp.float64)
    fitted = jnp.linalg.solve(matrix, h)
    read = jnp.einsum("bi,bih->bh", q, fitted).astype(gram.dtype)
    return read, matrix, fitted


def apply_model(p, x, dt, variant, return_aux=False):
    name, mode = family(variant)
    u = jnp.concatenate([x, jnp.log1p(dt)[..., None]], axis=-1)
    batch, width = x.shape[0], p["out"].shape[0]
    if name != "memory":
        fast = .2 + 4.8 * jax.nn.sigmoid(p["tau_fast"])
        slow = 2. + 98. * jax.nn.sigmoid(p["tau_slow"])
        regen = 4. * jax.nn.sigmoid(p["regen"])
        recover = 6. * jax.nn.sigmoid(p["recover"])
        call = 2. * jax.nn.sigmoid(p["call"])

    def token(xx, yy, incoming, delta):
        hidden = jnp.tanh(incoming @ p["inp"] + p["bias"])
        key = jnp.tanh(incoming @ p["key"] + p["key_bias"]) / jnp.sqrt(
            jnp.asarray(prior.KEY_DIM, x.dtype))
        candidate = hidden @ p["value"] + p["value_bias"]
        current = jnp.tanh(p["read_current"]) * hidden
        if name != "memory":
            boundary = p["boundary"] + incoming @ p["boundary_weights"]
            q, a = gates(xx - boundary, name)
            drive = 3. * jnp.tanh(hidden + .5 * jnp.tanh(p["recurrent_diag"]) * (2 * q - 1))
            ef = jnp.exp(-delta[:, None] / fast)
            es = jnp.exp(-delta[:, None] / slow)
            xx = ef * xx + (1. - ef) * (call * a + regen * q - yy + drive)
            yy = es * yy + (1. - es) * recover * q
            candidate = candidate + .1 * jnp.tanh(xx)
            current = current + jnp.tanh(p["read_fast"]) * jnp.tanh(xx)
            current = current + jnp.tanh(p["read_slow"]) * jnp.tanh(yy)
        return xx, yy, key, jnp.tanh(candidate), current

    def step(state, item):
        gram, cross, mass, xx, yy = state
        incoming, delta = item
        xx, yy, key, value, _ = token(xx, yy, incoming, delta)
        write = prior.closed_write(incoming @ p["write"] + p["write_bias"])
        gram, cross, mass = prior.update_statistics(gram, cross, mass, key, value, write)
        return (gram, cross, mass, xx, yy), None

    initial = (jnp.zeros((batch, prior.KEY_DIM, prior.KEY_DIM), x.dtype),
               jnp.zeros((batch, prior.KEY_DIM, width), x.dtype),
               jnp.ones((batch, 1), x.dtype), jnp.zeros((batch, width), x.dtype),
               jnp.zeros((batch, width), x.dtype))
    (gram, cross, mass, xx, yy), _ = jax.lax.scan(
        step, initial, (u[:, :-1].swapaxes(0, 1), dt[:, :-1].swapaxes(0, 1)))
    xx, yy, query, _, current = token(xx, yy, u[:, -1], dt[:, -1])
    read, matrix, fitted = read_statistics(gram, cross, mass, query, mode)
    logits = (jnp.tanh(read) + current) @ p["out"] + p["out_bias"]
    if return_aux:
        return logits, dict(gram=gram, cross=cross, inverse_mass=mass, matrix=matrix,
                            fitted=fitted, query=query, read=read, fast=xx, slow=yy)
    return logits


def resources(variant, width):
    name, _ = family(variant)
    return dict(persistent_state_scalars=prior.state_count(
        "ridge_memory_only" if name == "memory" else "full_hx", width),
        shared_fixed_operator_bytes=sum(v.nbytes for v in prior.financial_table().values())
        if name in ("full", "sigmoid") else 0)
