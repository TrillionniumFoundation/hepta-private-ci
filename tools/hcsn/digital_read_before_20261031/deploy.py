"""Torch-free reference execution of the exact exported native policy schema."""
import copy
import json
from pathlib import Path
import time

import numpy as np

from .task import Owner, Oracle, fixed_action, history_features, legal, posterior, public_features

MASK64 = (1 << 64)-1


def splitmix64(state):
    state = (state+0x9E3779B97F4A7C15) & MASK64
    z = ((state ^ (state >> 30))*0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27))*0x94D049BB133111EB) & MASK64
    z ^= z >> 31
    return state, (z >> 11)*2.**-53


class Policy:
    def __init__(self, artifact):
        if artifact["schema"] != "digital-read-before-policy-v1":
            raise ValueError("unsupported policy schema")
        self.artifact = artifact
        network = artifact["network"]
        self.w1, self.b1, self.w2, self.b2 = [np.asarray(network[k], dtype=np.float64) for k in ("w1", "b1", "w2", "b2")]
        if (self.w1.shape != (32, 48) or self.b1.shape != (32,) or self.w2.shape != (7, 32) or self.b2.shape != (7,)):
            raise ValueError("incompatible network dimensions")
        if not all(np.isfinite(x).all() for x in (self.w1, self.b1, self.w2, self.b2)):
            raise ValueError("nonfinite weights")
        self.kernel = artifact["kernel"]
        self.tables = {}
        if self.kernel is not None:
            for row in self.kernel["contexts"]:
                key = (row["dt"], row["symbol"], row["reliability"])
                if key in self.tables:
                    raise ValueError("duplicate context")
                self.tables[key] = row

    def context(self, dt, state):
        return self.tables[(dt, state["last_symbol"], state["last_reliability"])]

    def predict(self, public, state, cell_index):
        representation = (history_features(state) if self.kernel is None else
                          np.asarray(self.context(0., state)["features"])[cell_index])
        x = np.concatenate((public_features(public, state), representation))
        output = self.w2 @ np.tanh(self.w1 @ x+self.b1)+self.b2
        belief = float(1/(1+np.exp(-np.clip(output[6], -700, 700))))
        return dict(q=output[:6].tolist(), belief=belief, belief_logit=float(output[6]))

    def advance(self, public, before, index, rng):
        if self.kernel is None:
            return index, rng, dict(event=False, recovery=False, probability=0., sampled=False)
        table = self.context(public["duration"][before["tick"]], before)
        probabilities = np.asarray(table["transition"])[index]
        rng, uniform = splitmix64(rng)
        after = min(int(np.searchsorted(np.cumsum(probabilities), uniform, side="right")), len(probabilities)-1)
        return after, rng, dict(event=index < 15 and after >= 15,
                               recovery=index >= 15 and after < 15,
                               probability=table["event_probability"][index],
                               uniform=uniform, sampled=True, before=index, after=after)


def run_python(public, folder, adapter, artifact, controller, seed, confusion=None):
    """Reference modes receive only the same observed history as every learner."""
    policy = None if artifact is None else Policy(artifact)
    oracle = Oracle(public, confusion) if artifact is None else None
    owner, index, rng, decisions = Owner(public, folder, adapter), 7, seed & MASK64, []
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    while not owner.state["terminal"]:
        before = copy.deepcopy(owner.state)
        mask = legal(public, before)
        wall, cpu = time.perf_counter(), time.process_time()
        if policy is None:
            q = oracle.q(before)
            scores = dict(q=[float(x) if good else 0. for x, good in zip(q, mask)],
                          belief=posterior(public, before, confusion))
        else:
            scores = policy.predict(public, before, index)
        action = (fixed_action(before, mask, scores["belief"]) if controller == "fixed" else
                  int(np.argmax(np.where(mask, scores["q"], -np.inf))))
        control_wall, control_cpu = time.perf_counter()-wall, time.process_time()-cpu
        old_index, old_rng = index, rng
        event = dict(event=False, recovery=False, probability=0., sampled=False)
        if action not in (0, 4, 5) and policy is not None:
            index, rng, event = policy.advance(public, before, index, rng)
        receipt = owner.step(action)
        decisions.append(dict(**receipt, q=scores["q"], belief=scores["belief"],
                              cell_before=old_index, cell_after=index, rng_before=old_rng,
                              rng_after=rng, event=event, control_wall_seconds=control_wall,
                              control_cpu_seconds=control_cpu))
    return dict(schema="digital-read-before-episode-v1", backend="python-reference",
                decisions=decisions, final_state=owner.state, final_cell_index=index,
                rng=rng, wall_seconds=time.perf_counter()-start_wall,
                cpu_seconds=time.process_time()-start_cpu)
