"""Real owner payoffs under exact reflected-Brownian endpoints on a decision mesh.

This does not simulate exact continuous first-crossing stopping times. A policy
can act only on the public registered mesh. Reset consumes the full recovery
lag and then returns an actual sampled content mode, with remaining time kept.
"""

import hashlib
import math

from scipy.special import expit

from .solver import choose


INITIAL = [(-1.5, 0), (-.25, 0), (.30, 0), (1.2, 0),
           (-1.5, 1), (-.25, 1), (.30, 1), (1.2, 1)]


def randoms(seed, time_index, namespace):
    digest = hashlib.sha256(f"r18-owner:{seed}:{time_index}:{namespace}".encode()).digest()
    return tuple((int.from_bytes(digest[j:j + 8], "big") + .5) / 2 ** 64 for j in (0, 8))


def execute(solution, seed, initial, policy="free", thresholds=None):
    config, dt, lag = solution["config"], solution["dt"], solution["lag"]
    remaining, elapsed, fee = len(solution["times"]) - 1, 0, 0.
    x, mode = float(initial[0]), int(initial[1])
    trace, resets = [], []
    while True:
        if not remaining or policy == "stop_now":
            action = "STOP"
        elif policy == "free":
            action = choose(solution, remaining, x, mode)
        elif policy == "fixed_mode":
            low, high = thresholds[mode]
            if x >= high or (remaining < lag and x <= low):
                action = "STOP"
            else:
                action = "RESET" if x <= low and remaining >= lag else "WAIT"
        else:
            raise ValueError("Unknown owner policy")
        trace.append(action[0])
        if action == "STOP":
            probability = config["reward_base"][mode] + config["reward_amplitude"][mode] * expit(config["reward_slope"] * x)
            uniform, _ = randoms(seed, elapsed, 2)
            success = int(uniform < probability)
            break
        if action == "RESET":
            if remaining < lag:
                raise RuntimeError("Recovery cannot finish before the fixed deadline")
            before = mode
            fee += config["reset_fee"][mode] + config["recovery_cost"] * config["recovery"]
            uniform, _ = randoms(seed, elapsed, 1)
            mode = 0 if uniform < config["content_transition"][mode][0] else 1
            resets.append(dict(start=elapsed, before=before, after=mode))
            x = config["reset_x"]
            remaining, elapsed = remaining - lag, elapsed + lag
        elif action == "WAIT":
            first, second = randoms(seed, elapsed, 0)
            normal = math.sqrt(-2 * math.log(first)) * math.cos(2 * math.pi * second)
            unconstrained = x + config["sigma"] * math.sqrt(dt) * normal
            width = config["upper"] - config["lower"]
            offset = (unconstrained - config["lower"]) % (2 * width)
            x = config["lower"] + (offset if offset <= width else 2 * width - offset)
            fee += config["wait_cost"] * dt
            remaining, elapsed = remaining - 1, elapsed + 1
        else:
            raise ValueError("Unknown action")
    return dict(seed=seed, initial=initial, policy=policy, thresholds=thresholds,
                actions="".join(trace), resets=resets, final_x=float(x), final_mode=mode,
                elapsed_steps=elapsed, remaining_steps=remaining, success=success,
                success_probability=float(probability), fee=fee,
                utility=float(success - fee), propensity_utility=float(probability - fee))
