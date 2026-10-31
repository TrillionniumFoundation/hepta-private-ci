"""Fixed-path score gradients and a predictable primal-dual multiplier.

This optimizes the declared exponential-moment plus supervised auxiliary
objective. A stochastic dual update is an optimization rule, not a certificate
that its population success constraint has been satisfied.
"""

from dataclasses import dataclass
import math

import torch

from ...abc_recovery.emission import score_function_objective


ARMS = ("mean", "risk", "risk_success")


@dataclass(frozen=True)
class DualState:
    """Multiplier chosen before the next batch's emissions are observed."""

    value: float = 0.
    updates: int = 0

    def advance(self, failure_gap, *, rate, cap):
        if (not all(math.isfinite(x) for x in (failure_gap, rate, cap, self.value))
                or not -1 <= failure_gap <= 1 or rate <= 0 or cap <= 0
                or not 0 <= self.value <= cap):
            raise ValueError("Invalid projected dual update")
        return DualState(min(cap, max(0., self.value + rate * failure_gap)),
                         self.updates + 1)


def objective(log_probability, utility, success, supervised, *, arm, dual,
              gamma=2., auxiliary_weight=.05):
    """Return a gradient surrogate using this batch's precommitted multiplier.

Success is an actual-output Boolean measurement. The reference model's failure
probability is theta-independent, so it is needed in the dual update but not in
the primal gradient. No normalized finite-batch CE gradient is claimed.
"""
    if arm not in ARMS or not isinstance(dual, DualState):
        raise ValueError("Unknown training treatment")
    if (utility.shape != success.shape or success.dtype != torch.bool
            or utility.requires_grad or not math.isfinite(auxiliary_weight)
            or auxiliary_weight < 0 or not math.isfinite(gamma) or gamma <= 0):
        raise ValueError("Invalid actual-output objective arguments")
    risk = score_function_objective(log_probability, -utility,
                                    risk_aversion=0. if arm == "mean" else gamma)
    failure = score_function_objective(log_probability, (~success).float(),
                                       risk_aversion=0.)
    multiplier = dual.value if arm == "risk_success" else 0.
    result = risk.surrogate + multiplier * failure.surrogate + auxiliary_weight * supervised
    if not torch.isfinite(result):
        raise FloatingPointError("Nonfinite risk/success objective")
    return result, {"risk_moment": risk.empirical_transformed_moment,
                    "empirical_utility_CE": -risk.empirical_joint_loss_ce,
                    "success": float(success.float().mean()),
                    "dual_used_before_current_emission": multiplier,
                    "auxiliary": float(supervised.detach())}
