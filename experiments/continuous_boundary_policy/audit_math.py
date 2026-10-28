"""Independent task ledgers/Bellman reference on the sealed numerical grid.

The finite grid constructor is shared and source-bound. Bellman induction,
causal features, scalar hit checks, random-stream identities and primitive
rewards are implemented here without importing policy or rollout functions.
"""

import hashlib
import math

import numpy as np
from scipy.special import log_ndtr, ndtr

from experiments.continuous_boundary_flow.math_model import TaskSpec, build_model


FULL = {"dual_flow", "generic_gru", "dual_event", "elman_mlp", "native_sparse"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, name, atol=2e-10):
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    require(
        a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(),
        f"Invalid finite shape for {name}",
    )
    require(bool(np.allclose(a, b, atol=atol, rtol=0)), f"Independent {name} mismatch")


def independent_hit(x, mu, sigma, duration, discount=0.0):
    require(
        x > 0 and sigma > 0 and duration > 0 and discount >= 0,
        "Invalid independent first-hit parameters",
    )
    scale = sigma * math.sqrt(duration)
    f = float(ndtr((-x - mu * duration) / scale)) + math.exp(
        -2 * mu * x / sigma**2 + float(log_ndtr((-x + mu * duration) / scale))
    )
    k = math.sqrt(mu**2 + 2 * discount * sigma**2)
    h = math.exp((k - mu) * x / sigma**2 + float(log_ndtr((-x - k * duration) / scale)))
    h += math.exp(
        (-k - mu) * x / sigma**2 + float(log_ndtr((-x + k * duration) / scale))
    )
    return min(1.0, max(0.0, f)), min(f, max(0.0, h))


def rng(seed, label):
    identity = int.from_bytes(
        hashlib.sha256(f"{seed}:{label}".encode()).digest()[:8], "big"
    )
    return np.random.Generator(np.random.Philox(identity)), identity


def expected_specs(seed, phase, count):
    """Replay the publicly registered task distribution with separate code."""
    generator, _ = rng(seed, "contexts:" + phase)
    result = []
    ood = phase == "test_ood"
    for _ in range(count):
        result.append(
            {
                "mu": float(
                    generator.uniform(-0.55, 0.08)
                    if ood
                    else generator.uniform(-0.32, -0.10)
                ),
                "sigma": float(
                    generator.uniform(0.22, 0.72)
                    if ood
                    else generator.uniform(0.30, 0.50)
                ),
                "dt": float(generator.choice([0.35, 0.65])) if ood else 0.5,
                "horizon": int(generator.choice([8, 16])) if ood else 12,
                "discount": float(
                    generator.uniform(0.02, 0.16)
                    if ood
                    else generator.uniform(0.035, 0.09)
                ),
                "production_rate": float(
                    generator.uniform(0.65, 1.2)
                    if ood
                    else generator.uniform(0.85, 1.15)
                ),
                "failure_cost": float(
                    generator.uniform(1.0, 5.5) if ood else generator.uniform(1.7, 3.3)
                ),
                "maintenance_cost": float(
                    generator.uniform(0.12, 0.95)
                    if ood
                    else generator.uniform(0.22, 0.50)
                ),
                "maintenance_reset": float(
                    generator.uniform(0.75, 1.75)
                    if ood
                    else generator.uniform(1.1, 1.5)
                ),
                "failure_reset": float(
                    generator.uniform(0.45, 1.2) if ood else generator.uniform(0.8, 1.1)
                ),
                "initial": float(
                    generator.uniform(0.3, 1.65)
                    if ood
                    else generator.uniform(0.75, 1.35)
                ),
            }
        )
    return result


def reference(spec, grid=64, upper=4.8):
    """Separate Bellman loop; shared source-bound finite numerical constructor."""
    model = build_model(TaskSpec(**spec), n_grid=grid, x_max=upper)
    n = model.n_states
    values, qs, boundaries = [np.zeros(n)], [], []
    for remaining in range(1, spec["horizon"] + 1):
        previous = values[-1]
        wait = model.reward + model.gamma * np.dot(model.transition, previous)
        repair = model.maintenance_reward + model.gamma * np.dot(
            model.maintenance_transition, previous
        )
        q = np.column_stack((wait, np.full(n, repair), np.zeros(n)))
        values.append(np.maximum.reduce(q.T))
        qs.append(q)
        advantage = repair - np.maximum(wait, 0)
        repair_states = np.flatnonzero(advantage > 0)
        if not len(repair_states):
            boundary = 0.0
        elif len(repair_states) == n:
            boundary = float(model.x[-1])
        else:
            require(
                np.array_equal(repair_states, np.arange(len(repair_states))),
                "Finite task boundary is not threshold-shaped",
            )
            index = len(repair_states) - 1
            fraction = advantage[index] / (advantage[index] - advantage[index + 1])
            boundary = float(
                model.x[index] + fraction * (model.x[index + 1] - model.x[index])
            )
        boundaries.append(boundary)
    for x, f, h in zip(model.x, model.F, model.H):
        independent = independent_hit(
            float(x), spec["mu"], spec["sigma"], spec["dt"], spec["discount"]
        )
        close([f, h], independent, "first-passage F/H", atol=2e-12)
    return {
        "model": model,
        "q": np.asarray(qs),
        "value": np.asarray(values),
        "boundaries": boundaries,
    }


def streams(seed, split, context_index, paths, ref):
    generator, identity = rng(seed, f"{split}:context:{context_index}:episode-streams")
    initial = np.searchsorted(
        np.cumsum(ref["model"].initial_distribution), generator.random(paths)
    )
    slots = generator.random((ref["model"].spec.horizon, paths, 6))
    return initial, slots, identity


def boundary_vector(spec, remaining):
    m, s, t = spec["mu"] / 0.6, spec["sigma"] / 0.6, remaining * spec["dt"] / 8
    cost, loss = spec["maintenance_cost"], spec["failure_cost"]
    return np.array(
        [
            1,
            remaining / 16,
            t,
            m,
            s,
            cost,
            loss / 6,
            spec["production_rate"] / 1.5,
            spec["discount"] / 0.2,
            spec["maintenance_reset"] / 2,
            spec["failure_reset"] / 2,
            spec["dt"],
            s * s,
            m * s,
            cost * s,
            cost / (1 + loss),
            t * s,
            t * m,
            t * cost,
            t * t,
        ]
    )


def expected_features(
    ref, checkpoint, state, remaining, previous_failed, previous_risk, previous_repair
):
    model, arm = ref["model"], checkpoint["arm"]
    s, x = vars(model.spec), float(model.x[state])
    if arm == "fixed_margin":
        boundary = checkpoint["candidate"]["fixed_boundary"]
    elif arm == "learned_margin":
        boundary = np.clip(
            boundary_vector(s, remaining) @ np.asarray(checkpoint["boundary_weights"]),
            0,
            model.x[-1],
        )
    else:
        boundary = ref["boundaries"][remaining - 1]
    margin = np.clip((x - boundary) / (s["sigma"] * np.sqrt(s["dt"])), -4, 4)
    scale = 1 + remaining * s["dt"] * s["production_rate"]
    put = s["failure_cost"] * model.H[state]
    call = (ref["q"][remaining - 1, state, 0] + put) / scale
    values = np.array(
        [
            x / 2,
            remaining / 16,
            s["mu"] / 0.6,
            s["sigma"] / 0.6,
            s["maintenance_cost"],
            s["failure_cost"] / 6,
            s["production_rate"] / 1.5,
            s["discount"] / 0.2,
            s["maintenance_reset"] / 2,
            s["failure_reset"] / 2,
            s["dt"],
            margin,
            call if arm in FULL or arm == "value_call" else 0,
            put / scale if arm in FULL else 0,
            model.F[state] if arm in FULL else 0,
            previous_risk / s["dt"],
            previous_failed,
            previous_repair,
        ]
    )
    reset = previous_failed if arm == "dual_event" else previous_risk
    if arm in {"elman_mlp", "native_sparse"}:
        reset = 0.0
    return np.clip(values, -4, 4), float(reset)


def verify_physics(step, ref):
    """Recompute primitive outcomes from the fixed six innovation slots."""
    model, spec = ref["model"], vars(ref["model"].spec)
    action, elapsed = step["action"], step["elapsed"]
    require(action in {"wait", "repair", "stop"}, "Unknown task action")
    u = np.asarray(step["uniforms"], dtype=float)
    require(
        u.shape == (6,) and np.isfinite(u).all() and np.all((u >= 0) & (u < 1)),
        "Invalid innovation slots",
    )
    state = step["state_idx"]
    require(
        isinstance(state, int)
        and not isinstance(state, bool)
        and 0 <= state < model.n_states,
        "Invalid physical state",
    )
    close(step["x"], model.x[state], "physical coordinate", atol=1e-13)
    if action == "stop":
        require(
            step["x_after_action"] is None
            and step["tau_hit"] is None
            and step["predicted_risk"] is None,
            "Stopped path contains physical exposure",
        )
        require(
            step["failed"] is False
            and step["active_time"] == 0
            and step["next_state_idx"] == -1,
            "Invalid absorbing-stop state",
        )
        reward, production, failure, maintenance = 0.0, 0.0, 0.0, 0.0
    else:
        after = (
            state
            if action == "wait"
            else int(
                np.searchsorted(
                    np.cumsum(model.maintenance_distribution), u[1], side="right"
                )
            )
        )
        x, probability = float(model.x[after]), float(model.F[after])
        close(step["x_after_action"], x, "post-action state", atol=1e-13)
        close(
            step["predicted_risk"], probability, "pre-outcome action risk", atol=2e-12
        )
        failed = bool(u[2] < probability)
        require(
            type(step["failed"]) is bool and step["failed"] == failed,
            "Failure disagrees with innovations",
        )
        if failed:
            hit = float(step["tau_hit"])
            require(0 < hit <= spec["dt"], "Hit time outside decision window")
            close(step["active_time"], hit, "active time at failure", atol=1e-13)
            hit_probability, _ = independent_hit(x, spec["mu"], spec["sigma"], hit)
            close(
                hit_probability,
                u[3] * probability,
                "conditional hit inversion",
                atol=2e-8,
            )
            next_state = int(
                np.searchsorted(
                    np.cumsum(model.failure_distribution), u[5], side="right"
                )
            )
        else:
            require(step["tau_hit"] is None, "Surviving path contains a hit time")
            close(step["active_time"], spec["dt"], "surviving active time", atol=1e-13)
            cumulative = np.cumsum(model.killed[after] / model.S[after])
            cumulative[-1] = 1.0
            next_state = int(np.sum(u[4] > cumulative))
        require(
            step["next_state_idx"] == next_state,
            "Next physical state disagrees with innovations",
        )
        t, q = float(step["active_time"]), spec["discount"]
        production = spec["production_rate"] * (-math.expm1(-q * t) / q if q else t)
        failure = spec["failure_cost"] * math.exp(-q * t) if failed else 0.0
        maintenance = spec["maintenance_cost"] if action == "repair" else 0.0
        reward = production - failure - maintenance
    discount = math.exp(-spec["discount"] * spec["dt"] * elapsed)
    close(step["reward"], reward, "window primitive reward", atol=2e-12)
    close(step["discounted_reward"], discount * reward, "discounted reward", atol=2e-12)
    return {
        "gross_utility": discount * reward,
        "production": discount * production,
        "failure_cost": discount * failure,
        "maintenance_cost": discount * maintenance,
    }
