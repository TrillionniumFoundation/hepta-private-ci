"""Frozen text marginal with an independently adapted RGB image-policy branch.

This is for the published finite RGB task, NOT the missing round04 digit models.
The raw text probability array is returned without renormalization or rounding.
Both controls execute two model forwards; this is a matched-work qualification
implementation, not an inference-optimized or deployed service.
"""
import numpy as np

from utility import joint_value_and_grad


class SplitPolicy:
    def __init__(self, base, mode):
        if mode not in ("joint", "protected"):
            raise ValueError("unknown mode")
        self.mode = mode
        self.frozen = base.clone()
        self.adapted = base.clone()
        for value in self.frozen.params.values():
            value.flags.writeable = False
        self.frozen_digest = self.frozen.digest()

    def forward(self, x):
        fixed_p, _ = self.frozen.forward(x)
        adapted_p, q = self.adapted.forward(x)
        return (fixed_p if self.mode == "protected" else adapted_p), q

    def step(self, x, labels, rewards, objective, rho, anchor, lr):
        if objective not in ("additive", "ndu"):
            raise ValueError("unknown objective")
        if not 0 <= anchor <= 1:
            raise ValueError("invalid anchor")
        p, q = self.forward(x)
        labels = np.asarray(labels)
        if (labels.dtype.kind not in "iu" or labels.shape != (len(p),)
                or np.any(labels < 0) or np.any(labels >= p.shape[1])):
            raise ValueError("invalid labels")
        dp, dq = p.copy(), q.copy()
        dp[np.arange(len(p)), labels] -= 1
        dq[np.arange(len(p)), labels] -= 1
        dp /= 2 * len(p)
        dq /= 2 * len(p)
        # Both exact finite-law profiles are computed in every arm, as upstream.
        _, ap, aq = joint_value_and_grad(p, q, rewards, 0)
        _, np_, nq = joint_value_and_grad(p, q, rewards, rho)
        gp, gq = (ap, aq) if objective == "additive" else (np_, nq)
        dt, di = anchor * dp + gp, anchor * dq + gq
        if self.mode == "protected":
            dt = np.zeros_like(dt)
        # The clone's encoder is image-only in protected mode. Its text head
        # is unused at serving. A zero text logit pullback does not freeze q.
        self.adapted.train_step(x, dt, di, lr)

    def verify_frozen(self):
        if self.frozen.digest() != self.frozen_digest:
            raise ValueError("frozen text branch mutated")
        for key in ("decoder", "decoder_bias"):
            if not np.array_equal(self.adapted.params[key], self.frozen.params[key]):
                raise ValueError("decoder unexpectedly changed")
