"""Differentiable finite regenerative semigroup; finite-space error remains.

The finite process and parameter domain follow PR4255's documented model.
This JAX implementation uses an augmented event accumulator and dyadic positive
uniformization. A deterministic refractory delay is not claimed: two phases
have an Erlang waiting law with the specified mean.
"""

import math

import jax
import jax.numpy as jnp


CELLS, PHASES, LOWER = 8, 2, -2.0
SIZE, RATE, TERMS, CHUNK, SQUARINGS = 10, 8.1, 21, 0.36, 10
MAX_DURATION = CHUNK * 2**SQUARINGS


def physical(raw):
    """Map five unconstrained parameters into the predeclared physical domain."""
    return jnp.array([0.1 + 0.4 * jnp.tanh(raw[0]),
                      0.3 + 0.3 * jax.nn.sigmoid(raw[1]),
                      0.35 + 1.15 * jax.nn.sigmoid(raw[2]),
                      -0.3 + 0.4 * jax.nn.sigmoid(raw[3]),
                      0.3 + 0.9 * jax.nn.sigmoid(raw[4])])


def geometry(theta):
    spacing = (theta[2] - LOWER) / CELLS
    edges = LOWER + jnp.arange(CELLS + 1, dtype=theta.dtype) * spacing
    return spacing, edges, (edges[:-1] + edges[1:]) / 2


def point_weights(theta, position):
    spacing, _, centers = geometry(theta)
    weights = jnp.maximum(1 - jnp.abs(centers - position) / spacing, 0)
    return weights / weights.sum()


def generator(theta):
    """Return row generator A and marked event rate lambda, without clipping."""
    mu, sigma, _, reset, tau = theta
    spacing, _, _ = geometry(theta)
    diffusion = sigma**2 / (2 * spacing**2)
    up = diffusion + jnp.maximum(mu, 0) / spacing
    down = diffusion + jnp.maximum(-mu, 0) / spacing
    exit_rate = 2 * diffusion + jnp.maximum(mu, 0) / spacing
    rows = jnp.arange(CELLS - 1)
    matrix = jnp.zeros((SIZE, SIZE), dtype=theta.dtype)
    matrix = matrix.at[rows, rows + 1].set(up)
    matrix = matrix.at[rows + 1, rows].set(down)
    matrix = matrix.at[CELLS - 1, CELLS].set(exit_rate)
    matrix = matrix.at[CELLS, CELLS + 1].set(PHASES / tau)
    matrix = matrix.at[CELLS + 1, :CELLS].set(PHASES / tau * point_weights(theta, reset))
    matrix = matrix - jnp.diag(matrix.sum(axis=1))
    event_rate = jnp.zeros(SIZE, dtype=theta.dtype).at[CELLS - 1].set(exit_rate)
    return matrix, event_rate


def _exponential(matrix, duration):
    """Conditional Poisson polynomial and bounded dyadic composition.

    Numerical integer branches are local per interval. Their derivatives are
    not claimed at branch changes. Invalid durations yield NaNs in pure JAX;
    the host checked API rejects them before calling this function.
    """
    duration = jnp.asarray(duration, dtype=matrix.dtype)
    levels = jnp.maximum(0, jnp.ceil(jnp.log2(jnp.maximum(duration / CHUNK, 1)))).astype(jnp.int32)
    small_time = duration / jnp.exp2(levels.astype(matrix.dtype))
    mean = RATE * small_time
    identity = jnp.eye(matrix.shape[0], dtype=matrix.dtype)
    transition = identity + matrix / RATE
    weight = jnp.exp(-mean)

    def term(k, carry):
        power, total, w, norm = carry
        power, w = power @ transition, w * mean / k
        return power, total + w * power, w, norm + w

    _, total, _, norm = jax.lax.fori_loop(1, TERMS + 1, term,
                                         (identity, weight * identity, weight, weight))
    total = total / norm

    def square(i, value):
        return jax.lax.cond(i < levels, lambda z: z @ z, lambda z: z, value)

    total = jax.lax.fori_loop(0, SQUARINGS, square, total)
    valid = jnp.isfinite(duration) & (duration >= 0) & (duration <= MAX_DURATION)
    return jnp.where(valid, total, jnp.full_like(total, jnp.nan))


def operator(theta, duration):
    """Return T and e: p_new=p@T; expected repeated emissions=p@e."""
    matrix, event_rate = generator(theta)
    augmented = jnp.zeros((SIZE + 1, SIZE + 1), dtype=theta.dtype)
    augmented = augmented.at[:SIZE, :SIZE].set(matrix)
    augmented = augmented.at[:SIZE, SIZE].set(event_rate)
    result = _exponential(augmented, duration)
    return result[:SIZE, :SIZE], result[:SIZE, SIZE]


def next_event_probability(probability, theta, duration):
    """Probability of at least one next exit, distinct from regenerative count."""
    matrix, _ = generator(theta)
    killed = matrix.at[CELLS - 1, CELLS].set(0)
    return 1 - jnp.sum(probability @ _exponential(killed, duration))


def remap(probability, old_theta, new_theta, cost):
    """One physical overlap remap, preserving the index of existing phases."""
    old_h, old_edges, _ = geometry(old_theta)
    _, new_edges, _ = geometry(new_theta)
    left = jnp.maximum(old_edges[:-1, None], new_edges[None, :-1])
    right = jnp.minimum(old_edges[1:, None], new_edges[None, 1:])
    overlap = jnp.maximum(right - left, 0) / old_h
    hit_left = jnp.maximum(old_edges[:-1], new_theta[2])
    fraction = jnp.maximum(old_edges[1:] - hit_left, 0) / old_h
    moment = fraction * (hit_left + old_edges[1:]) / 2
    result = jnp.concatenate((probability[:CELLS] @ overlap, probability[CELLS:]))
    events = probability[:CELLS] @ fraction
    result = result.at[CELLS].add(events)
    reward = probability[:CELLS] @ (moment - cost * fraction)
    same = old_theta[2] == new_theta[2]
    return jnp.where(same, probability, result), jnp.where(same, 0., events), jnp.where(same, 0., reward)


def error_bounds(duration):
    """Conservative absolute state/count bounds; excludes roundoff and space."""
    if not math.isfinite(duration) or not 0 <= duration <= MAX_DURATION:
        raise ValueError("Duration outside declared finite domain")
    levels = max(0, math.ceil(math.log2(max(duration / CHUNK, 1))))
    chunks, mean = 2**levels, RATE * duration / 2**levels
    if mean == 0:
        return {"state_l1": 0., "events_absolute": 0., "chunks": chunks}
    a = math.exp(-mean + (TERMS + 1) * math.log(mean) - math.lgamma(TERMS + 2))
    ratio = mean / (TERMS + 2)
    delta = a / (1 - ratio)
    first = a * ((TERMS + 1) / (1 - ratio) + ratio / (1 - ratio)**2)
    count = first + mean * delta / (1 - delta)
    return {"state_l1": 2 * chunks * delta,
            "events_absolute": chunks * count + chunks * (chunks - 1) * delta * mean,
            "chunks": chunks}
