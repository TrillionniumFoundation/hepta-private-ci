"""Balanced-prior, one deadline-six READ reference; no kernel or hidden inputs.

The frozen sensing plan is optimized within this restricted class using the
TRAIN decoder model. Its Q entries describe the chosen plan, not optimal Q for
all actions or an unknown true environment. Actual execution belongs to Owner.
"""
import copy
import numpy as np


class DeadlineOnlyPolicy:
    def __init__(self, public, confusion):
        self.public = copy.deepcopy(public)
        confusion = np.asarray(confusion, dtype=np.float64)
        if confusion.shape != (2, 2) or not np.isfinite(confusion).all() or np.any(confusion <= 0) or not np.allclose(confusion.sum(1), 1.):
            raise ValueError("positive TRAIN-fitted stochastic decoder required")
        if public["deadline"] != 6 or public["target_tick"] != 6:
            raise ValueError("fixed deadline-six task required")
        r = public["reliability"][5]
        self.emission = np.array([[r, 1-r], [1-r, r]]) @ confusion
        self.tv = .5*float(np.abs(self.emission[1]-self.emission[0]).sum())
        self.expected_reward = (1-public["failure_probability"])*self.tv
        candidates = [(self.expected_reward-public["read_price"][t]-public["latency_price"]*sum(public["duration"]), t)
                      for t in range(6) if t+public["read_delay"][t] == 6]
        best = max(candidates, key=lambda pair: (pair[0], -pair[1])) if candidates else (0., None)
        self.request_tick = best[1] if best[0] > 0 else None
        self.plan_initial_utility = max(0., best[0])
        self.reference_scope = "balanced_prior_deadline_single_read_TRAIN_decoder"

    def predict(self, public, state):
        if public != self.public or state["terminal"]:
            raise ValueError("wrong public world or terminal state")
        observed = [h for h in state["history"] if h["observation_tick"] == 6]
        p = .5
        if observed:
            y = observed[-1]["observation"]
            p = float(self.emission[1, y]/self.emission[:, y].sum())
        q = [0., 0., 0., 0., 1-2*p, 2*p-1]
        t = state["tick"]
        if self.request_tick is not None and t < 6 and not state["broken"]:
            pending = state["pending"]
            valid_pending = pending is not None and pending["source_tick"] == self.request_tick and pending["due_tick"] == 6
            waiting = pending is None and t < self.request_tick
            requesting = pending is None and t == self.request_tick and state["budget"] > 0
            if valid_pending or waiting or requesting:
                future_fee = 0. if valid_pending else public["read_price"][self.request_tick]
                value = self.expected_reward-future_fee-public["latency_price"]*sum(public["duration"][t:])
                q[2 if requesting else 1] = value
        return dict(q=q, belief=p, reference_scope=self.reference_scope,
                    q_scope="chosen frozen one-read plan future reward minus unpaid costs; unused continuations zero, not optimal action Q",
                    request_tick=self.request_tick, initial_plan_utility=self.plan_initial_utility)
