"""Finite fully observed control with interventions that alter the owner state."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ...addressed_decision_r15_20261101.law import Law


PROTOCOL = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
STOP, RUN, RESET = 0, 1, 2


class Model:
    def __init__(self):
        started = time.process_time()
        self.law = Law(theta=PROTOCOL["theta"])
        self.horizon = PROTOCOL["horizon"]
        self.reward_rate = np.r_[np.tile(PROTOCOL["active_net_reward_rate_by_content"], 8),
                                np.full(8, PROTOCOL["recovery_net_reward_rate"])]
        self.salvage = np.r_[np.tile(PROTOCOL["active_stop_value_by_content"], 8),
                            np.full(8, PROTOCOL["recovery_stop_value"])]
        self.transitions = {float(dt): self.law.transition(dt) for dt in
                            PROTOCOL["iid_dt"] + PROTOCOL["ood_dt"]}
        self.kernels, self.fees = {}, {}
        for kind, spec in PROTOCOL["reset_content_kernels"].items():
            for recovery, rec in PROTOCOL["reset_recovery_states"].items():
                name = f"{kind}:{recovery}"
                matrix = np.zeros((40, 40))
                for state in range(40):
                    content = state % 4
                    if kind == "retain":
                        probabilities = np.full(4, spec["other_each"])
                        probabilities[content] = spec["same_content_probability"]
                    elif kind == "repair":
                        probabilities = np.eye(4)[0] * spec["target_zero_mixture"]
                        probabilities += np.eye(4)[content] * spec["retain_mixture"]
                    elif kind == "rebuild":
                        probabilities = np.full(4, spec["uniform_mixture"] / 4)
                        probabilities[0] += spec["target_zero_mixture"]
                    else:
                        raise ValueError("Unknown reset kernel")
                    matrix[state, 4 * rec["phase"]:4 * rec["phase"] + 4] = probabilities
                assert np.allclose(matrix.sum(1), 1, rtol=0, atol=1e-14)
                self.kernels[name] = matrix
                self.fees[name] = float(spec["fee"] + rec["extra_fee"])
        self.preparation_cpu = time.process_time() - started

    def threshold(self, boundary=1, stop_steps=1):
        policy = np.zeros((self.horizon + 1, 40), dtype=np.int8)
        states = np.arange(40)
        active, score = states // 4 < 8, states // 4 - 2 * (states % 4)
        for remaining in range(stop_steps + 1, self.horizon + 1):
            policy[remaining] = np.where(active & (score <= boundary), RESET, RUN)
        return policy

    def dp(self, kernel, dt):
        """All three actions are available at every positive remaining horizon."""
        transition, reset = self.transitions[float(dt)], self.kernels[kernel]
        value = self.salvage.copy()
        policy = np.zeros((self.horizon + 1, 40), dtype=np.int8)
        values = [value.copy()]
        for remaining in range(1, self.horizon + 1):
            run = self.reward_rate * dt + transition @ value
            reset_value = reset @ run - self.fees[kernel]
            q = np.stack((self.salvage, run, reset_value))
            # Same exact tie order STOP, RUN, RESET for both model labels.
            policy[remaining] = np.argmax(q, axis=0)
            value = np.max(q, axis=0)
            values.append(value.copy())
        return policy, np.asarray(values)

    def exact(self, policy, kernel, dt):
        transition, reset = self.transitions[float(dt)], self.kernels[kernel]
        value = self.salvage.copy()
        for remaining in range(1, self.horizon + 1):
            run = self.reward_rate * dt + transition @ value
            reset_value = reset @ run - self.fees[kernel]
            value = np.choose(policy[remaining], (self.salvage, run, reset_value))
        return float(self.law.prior @ value)


def tape(fit, namespace, count, domain, horizon):
    """Public dt plus owner-only draws, coupled across compared actions."""
    key = f"hcsn-r16-control:{fit}:{namespace}:{domain}"
    digest = hashlib.sha256(key.encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:16], "big"))
    return dict(namespace=namespace, fit=fit, domain=domain,
                dt=rng.choice(PROTOCOL[f"{domain}_dt"], count),
                initial=rng.random(count),
                transition=rng.random((horizon, count)),
                reset=rng.random((horizon, count)))


def rollout(model, tapes, kernel, policies, capture=False):
    """Only owner code receives random draws; policy tables see (h, state, dt)."""
    started = time.process_time()
    count = len(tapes["initial"])
    state = np.searchsorted(np.cumsum(model.law.prior), tapes["initial"], side="right")
    total = np.zeros(count)
    active = np.ones(count, dtype=bool)
    resets, runs, stops = np.zeros(count, int), np.zeros(count, int), np.zeros(count, int)
    trace = []
    kernel_cdf = np.cumsum(model.kernels[kernel], axis=1)
    transition_cdf = {dt: np.cumsum(matrix, axis=1) for dt, matrix in model.transitions.items()}
    for step in range(model.horizon + 1):
        if not active.any():
            break
        remaining = model.horizon - step
        for dt in np.unique(tapes["dt"]):
            ids = np.flatnonzero(active & (tapes["dt"] == dt))
            if not len(ids):
                continue
            before = state[ids].copy()
            action = policies[float(dt)][remaining, before]
            terminal = ids[action == STOP]
            total[terminal] += model.salvage[state[terminal]]
            stops[terminal] += 1
            active[terminal] = False
            continuing = ids[action != STOP]
            resetting = ids[action == RESET]
            if len(resetting):
                state[resetting] = np.sum(
                    tapes["reset"][step, resetting, None] >= kernel_cdf[state[resetting]], axis=1)
                total[resetting] -= model.fees[kernel]
                resets[resetting] += 1
            reset_state = state[ids].copy()
            if len(continuing):
                total[continuing] += model.reward_rate[state[continuing]] * dt
                state[continuing] = np.sum(
                    tapes["transition"][step, continuing, None]
                    >= transition_cdf[float(dt)][state[continuing]], axis=1)
                runs[ids[action == RUN]] += 1
            if capture:
                trace.append(dict(step=step, dt=float(dt), indices=ids.tolist(),
                                  before=before.tolist(), actions=action.tolist(),
                                  intervention_state=reset_state.tolist(),
                                  after=state[ids].tolist(), cumulative=total[ids].tolist()))
    if active.any() or np.any(stops != 1) or not np.isfinite(total).all():
        raise RuntimeError("Invalid finite owner termination")
    return dict(returns=total.tolist(), resets=resets.tolist(), runs=runs.tolist(),
                stops=stops.tolist(), mean=float(total.mean()), trace=trace if capture else None,
                cpu_seconds=time.process_time() - started)


def policies_for(model, spec):
    started = time.process_time()
    if spec["kind"] == "dp":
        policies = {dt: model.dp(spec["kernel"], dt)[0] for dt in model.transitions}
    else:
        policy = model.threshold(spec["boundary"], spec["stop_steps"])
        policies = {dt: policy for dt in model.transitions}
    return policies, time.process_time() - started
