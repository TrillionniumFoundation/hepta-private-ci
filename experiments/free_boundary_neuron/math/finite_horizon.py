"""Explicit finite-state Bermudan oracle for native owner engineering tests.

Gaussian increments are binned, with tail mass saturating endpoint states.
This numerical MDP is not claimed to equal continuous optimal stopping.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import ndtr


PROFILE_PATH = Path(__file__).with_name("PROFILE.json")
READOUT_PATH = Path(__file__).parent / "results" / "readout_affine_v1.json"


def gaussian_transition(states, dt, mu, sigma, killing_rate=0.0):
    """Substochastic transition: missing row mass is zero-recovery killing."""
    states = np.asarray(states, dtype=float)
    values = np.asarray([dt, mu, sigma, killing_rate], dtype=float)
    if (
        states.ndim != 1
        or states.size < 3
        or not np.all(np.isfinite(states))
        or not np.all(np.diff(states) > 0)
        or not np.all(np.isfinite(values))
        or dt <= 0
        or sigma <= 0
        or killing_rate < 0
    ):
        raise ValueError(
            "ordered finite states, positive dt/sigma, nonnegative hazard required"
        )
    edges = np.concatenate(([-np.inf], 0.5 * (states[:-1] + states[1:]), [np.inf]))
    cdf = ndtr((edges[None, :] - states[:, None] - mu * dt) / (sigma * np.sqrt(dt)))
    return np.diff(cdf, axis=1) * np.exp(-killing_rate * dt)


def solve_bermudan(
    states, horizon_steps, dt, mu, sigma, rho, killing_rate, payoff_cost, running_cost
):
    """Backward Bellman solve for stop, continue, and zero-valued abstain."""
    states = np.asarray(states, dtype=float)
    if (
        not isinstance(horizon_steps, int)
        or horizon_steps < 1
        or not np.all(np.isfinite([rho, payoff_cost, running_cost]))
        or rho < 0
        or running_cost < 0
    ):
        raise ValueError(
            "positive integer horizon and finite nonnegative rates/cost required"
        )
    transition = gaussian_transition(states, dt, mu, sigma, killing_rate)
    stop = states - payoff_cost
    value = np.zeros((horizon_steps + 1, len(states)))
    continuation = np.zeros_like(value)
    action = np.full(value.shape, "abstain", dtype="<U8")
    value[0] = np.maximum(stop, 0)
    action[0, stop > 0] = "stop"
    for n in range(1, horizon_steps + 1):
        continuation[n] = -running_cost * dt + np.exp(-rho * dt) * transition.dot(
            value[n - 1]
        )
        value[n] = np.maximum(np.maximum(stop, continuation[n]), 0)
        positive = value[n] > 0
        action[n, positive & (stop >= continuation[n])] = "stop"
        action[n, positive & (stop < continuation[n])] = "continue"
    return {
        "states": states,
        "transition": transition,
        "value": value,
        "continuation": continuation,
        "stop_value": stop,
        "action": action,
    }


def build_readout(profile=None):
    """Build the exact exported numerical MDP, including all transition rows."""
    if profile is None:
        profile = json.loads(PROFILE_PATH.read_text())
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    profile_id = (
        "affine_gaussian_v1_" + hashlib.sha256(canonical.encode()).hexdigest()[:16]
    )
    parameter_names = (
        "dt",
        "mu",
        "sigma",
        "rho",
        "killing_rate",
        "payoff_cost",
        "running_cost",
    )
    parameters = {key: profile[key] for key in parameter_names}
    states = np.linspace(
        profile["state_min"], profile["state_max"], profile["state_count"]
    )
    arrays = solve_bermudan(states, profile["horizon_steps"], **parameters)
    return {
        "schema": "hepta.free-boundary.readout.v1",
        "profile_id": profile_id,
        "transition_kind": "survival_weighted_gaussian_bins",
        "evidence_scope": "engineering_correctness_only",
        **parameters,
        **{key: value.tolist() for key, value in arrays.items()},
    }


def export_readout(destination=READOUT_PATH):
    data = build_readout()
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    Path(destination).write_text(
        json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n"
    )
    return data["profile_id"]


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "path": str(READOUT_PATH),
                "profile_id": export_readout(),
                "evidence_scope": "engineering_correctness_only",
            }
        )
    )
