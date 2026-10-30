"""Fixed recurrent LIF reference with hard forward spikes and surrogate BPTT.

The surrogate is an optimization rule, not the derivative of a hard threshold.
General method: Neftci, Mostafa and Zenke (2019), arXiv:1901.09948.
This small reference is not a reproduction of a paper's benchmark system.
"""

import jax
import jax.numpy as jnp
import numpy as np


@jax.custom_jvp
def hard_spike(z):
    """Hard 0/1 forward; threshold is z >= 0."""
    return (z >= 0).astype(z.dtype)


@hard_spike.defjvp
def _hard_spike_jvp(primals, tangents):
    z, = primals
    dz, = tangents
    surrogate = 1. / (1. + 5. * jnp.abs(z)) ** 2
    return hard_spike(z), surrogate * dz


def init_model(key, input_dim, hidden_dim, output_dim):
    """All arrays are strong float32, avoiding legacy weak-scalar JIT changes."""
    d, h, k = input_dim + 1, hidden_dim, output_dim
    keys = jax.random.split(key, 3)
    def weight(key, a, b, gain=1.):
        return jax.random.normal(key, (a, b), dtype=jnp.float32) * np.float32(gain / np.sqrt(a))
    return dict(inp=weight(keys[0], d, h), recurrent=weight(keys[1], h, h, .1),
                bias=jnp.full((h,), 1.25, dtype=jnp.float32),
                tau_membrane=jnp.full((h,), np.log(1. / 8.), dtype=jnp.float32),
                tau_readout=jnp.full((h,), np.log(.25), dtype=jnp.float32),
                out=weight(keys[2], h, k), out_bias=jnp.zeros((k,), dtype=jnp.float32))


def matched_width(input_dim, output_dim, budget=6200):
    d, k = input_dim + 1, output_dim
    candidates = [(abs(h*h+(d+k+3)*h+k-budget), h, h*h+(d+k+3)*h+k)
                  for h in range(4, 129)]
    _, width, count = min(candidates)
    return width, count


def apply_model(params, x, dt, return_aux=False):
    """Return sequence logits; optional aux exposes actual hard spike traces.

    States: membrane after soft reset, previous binary spike, low-pass readout.
    One event at most per unit/time bin; no sub-bin threshold interpolation.
    All inputs, including log1p(dt), are current encoded as in other references.
    """
    p = params
    u = jnp.concatenate([x, jnp.log1p(dt)[..., None]], axis=-1)
    batch, _, _ = u.shape
    width = p["out"].shape[0]
    tau_m = 2. + 18. * jax.nn.sigmoid(p["tau_membrane"])
    tau_r = 4. + 60. * jax.nn.sigmoid(p["tau_readout"])
    def step(state, item):
        v, previous_spike, filtered_spike = state
        incoming, delta = item
        current = incoming @ p["inp"] + previous_spike @ p["recurrent"] + p["bias"]
        decay_m = jnp.exp(-delta[:, None] / tau_m)
        before_reset = decay_m * v + (1. - decay_m) * current
        spike = hard_spike(before_reset - 1.)
        # Detach only the reset branch; spike readout/recurrent paths use the surrogate.
        v = before_reset - jax.lax.stop_gradient(spike)
        decay_r = jnp.exp(-delta[:, None] / tau_r)
        filtered_spike = decay_r * filtered_spike + (1. - decay_r) * spike
        return (v, spike, filtered_spike), spike
    zero = jnp.zeros((batch, width), dtype=x.dtype)
    final, spikes = jax.lax.scan(step, (zero, zero, zero),
                                (u.swapaxes(0, 1), dt.swapaxes(0, 1)))
    logits = final[2] @ p["out"] + p["out_bias"]
    if return_aux:
        return logits, dict(spikes=spikes.swapaxes(0, 1), final_membrane=final[0],
                            final_filtered_spike=final[2], tau_membrane=tau_m,
                            tau_readout=tau_r)
    return logits
