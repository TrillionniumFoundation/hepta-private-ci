"""Functional observation/gap interface suitable for JIT, AD and checkpointing.

A gap is propagated BEFORE assimilating an observation arriving at its end.
Observation writes take zero physical time. Gap content obeys dh/dt=-rate*h;
it is coupled to the physical distribution by the next observation's gate,
not by an unclaimed nonlinear continuous ODE.
"""

import json

import jax
import jax.numpy as jnp
import numpy as np

from . import kernel


def init_parameters(input_dim=3, width=4, seed=0, dtype=jnp.float32):
    rng = np.random.default_rng(seed)
    weight = lambda a, b: jnp.asarray(rng.normal(size=(a, b)) / np.sqrt(a), dtype=dtype)
    return dict(input=weight(input_dim, width), recurrent=0.2 * weight(width, width),
                bias=jnp.zeros(width, dtype=dtype), gate_input=weight(input_dim, width),
                gate_physical=0.2 * weight(kernel.SIZE, width), gate_bias=jnp.zeros(width, dtype=dtype),
                dynamics=0.25 * weight(input_dim, 3), raw_physical=jnp.zeros(5, dtype=dtype),
                raw_decay=jnp.full(width, -1., dtype=dtype), raw_cost=jnp.array(-1., dtype=dtype))


def initial_state(params):
    theta = kernel.physical(params["raw_physical"])
    probability = jnp.pad(kernel.point_weights(theta, 0.), (0, kernel.PHASES))
    scalar = jnp.array(0., dtype=theta.dtype)
    return dict(probability=probability, content=jnp.zeros_like(params["bias"]), physical=theta,
                decay=0.02 + 0.18 * jax.nn.sigmoid(params["raw_decay"]),
                cost=0.1 + 0.4 * jax.nn.sigmoid(params["raw_cost"]),
                elapsed=scalar, events=scalar, reward=scalar, observations=jnp.array(0, dtype=jnp.int32))


def observe(params, observation, state):
    """Assimilate one real observation once; do not advance physical time."""
    raw = params["raw_physical"].at[:3].add(observation @ params["dynamics"])
    theta = kernel.physical(raw).at[3:].set(state["physical"][3:])
    probability, events, reward = kernel.remap(state["probability"], state["physical"], theta, state["cost"])
    candidate = jnp.tanh(observation @ params["input"] + state["content"] @ params["recurrent"] + params["bias"])
    gate = jax.nn.sigmoid(observation @ params["gate_input"] + probability @ params["gate_physical"] + params["gate_bias"])
    content = (1 - gate) * state["content"] + gate * candidate
    return dict(state, probability=probability, content=content, physical=theta,
                events=state["events"] + events, reward=state["reward"] + reward,
                observations=state["observations"] + 1)


def propagate(state, duration):
    """No observation is accepted; frozen coefficients and phases continue."""
    transition, event_vector = kernel.operator(state["physical"], duration)
    events = state["probability"] @ event_vector
    return dict(state, probability=state["probability"] @ transition,
                content=state["content"] * jnp.exp(-state["decay"] * duration),
                elapsed=state["elapsed"] + duration, events=state["events"] + events,
                reward=state["reward"] + (state["physical"][2] - state["cost"]) * events)


def checked_propagate(state, duration):
    """Host boundary for external callers; pure propagate is the JIT core."""
    kernel.error_bounds(float(duration))
    validate_state(state)
    return propagate(state, duration)


def validate_state(state):
    if not all(np.isfinite(np.asarray(value)).all() for value in state.values()):
        raise ValueError("State must be finite")
    probability, theta = np.asarray(state["probability"]), np.asarray(state["physical"])
    tolerance = 1e-5 if probability.dtype == np.float32 else 1e-10
    if probability.shape != (kernel.SIZE,) or probability.min() < -tolerance or abs(probability.sum() - 1) > tolerance:
        raise ValueError("Full active and refractory probability mass must equal one")
    lower, upper = np.array([-.3, .3, .35, -.3, .3]), np.array([.5, .6, 1.5, .1, 1.2])
    if theta.shape != (5,) or np.any(theta < lower - 1e-7) or np.any(theta > upper + 1e-7):
        raise ValueError("Physical parameters outside certified domain")
    if np.asarray(state["content"]).shape != np.asarray(state["decay"]).shape or np.any(np.asarray(state["decay"]) <= 0):
        raise ValueError("Content and positive decay dimensions must match")
    if float(state["elapsed"]) < 0 or float(state["events"]) < -tolerance or int(state["observations"]) < 0:
        raise ValueError("Invalid cumulative counters")


def run_sequence(params, observations, gaps, state=None):
    """Each gap precedes its arriving observation; gaps alone use propagate."""
    state = initial_state(params) if state is None else state
    def step(carry, item):
        observation, gap = item
        carry = observe(params, observation, propagate(carry, gap))
        return carry, carry["content"]
    return jax.lax.scan(step, state, (observations, gaps))


def save_checkpoint(path, params, state):
    validate_state(state)
    arrays = {f"params__{key}": np.asarray(value) for key, value in params.items()}
    arrays.update({f"state__{key}": np.asarray(value) for key, value in state.items()})
    arrays["schema"] = np.array("hcsn_observation_gap_state_v1")
    np.savez(path, **arrays)


def load_checkpoint(path):
    with np.load(path, allow_pickle=False) as archive:
        if str(archive["schema"]) != "hcsn_observation_gap_state_v1":
            raise ValueError("Unknown checkpoint schema")
        params = {key[8:]: jnp.asarray(archive[key]) for key in archive.files if key.startswith("params__")}
        state = {key[7:]: jnp.asarray(archive[key]) for key in archive.files if key.startswith("state__")}
    validate_state(state)
    return params, state


if __name__ == "__main__":
    params = init_parameters()
    state = observe(params, jnp.array([1., 0., -0.5]), initial_state(params))
    state = checked_propagate(state, 2.0)
    print(json.dumps({key: np.asarray(value).tolist() for key, value in state.items()}, sort_keys=True))
