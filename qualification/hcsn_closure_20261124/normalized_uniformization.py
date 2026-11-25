"""Explicitly normalized truncated Poisson action, a new numerical variant.

This is a conditional finite Poisson mixture, not post-hoc density repair.
Relative to the unnormalized truncation, normalization changes the real-
arithmetic operator by at most its omitted probability for a stochastic
transition in the induced infinity norm. Relative to the infinite mixture,
the bound is twice that tail. Augmented reward actions need a first-moment
tail bound as well. Floating roundoff and gradients require separate tests.

The weighted-mean recurrence preserves a constant sequence of terms exactly
in floating arithmetic. It does not guarantee machine-exact conservation of
arbitrary matrix products, remaps, signed marks or arbitrarily long streams.
"""

import torch

from qualification.hcsn_adaptive.uniformized_flow import ActionBudget
from .fast_kernel import FastSignedHCSN


@torch.jit.script
def normalized_action(matrix: torch.Tensor, vectors: torch.Tensor,
                      rate: torch.Tensor, duration: float, column: bool,
                      substeps: int, order: int):
    transition = torch.eye(matrix.shape[-1], dtype=matrix.dtype,
                           device=matrix.device)+matrix/rate
    mean = rate*(duration/substeps)
    initial = torch.exp(-mean)
    result = vectors
    for _ in range(substeps):
        term = result
        total = term
        weight, cumulative = initial, initial
        for k in range(1, order+1):
            if column:
                term = transition @ term
            else:
                term = term @ transition
            weight = weight*mean/k
            cumulative = cumulative+weight
            total = total+(weight/cumulative)*(term-total)
        result = total
    return result


class NormalizedUniformizedHCSN(FastSignedHCSN):
    def _action(self, matrix, vectors, rate, duration, column=False):
        if self.config.backend != "uniformized":
            raise ValueError("normalized Poisson action requires uniformized backend")
        plan = ActionBudget().plan(float(rate.detach()), duration,
                                   max(1., float(rate.detach())))
        return normalized_action(matrix, vectors, rate, duration, column,
                                  plan["substeps"], plan["order"])
