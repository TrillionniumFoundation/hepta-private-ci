"""Opt-in banded uniformization ACTION for the existing frozen finite process.

No dense exponential, numerical cross-call cache, or change to the state law.
The generator is still built/validated by BatchedFlow; only its sparse bands,
phase chain and rank-one reset are reused within this interval. The value solve
is unchanged. Tail bounds below cover truncation in exact arithmetic, NOT roundoff
or gradients. Autograd differentiates the selected finite sum; order/splitting
are discrete numerical decisions. This is not the N256 bitwise-qualified backend.
"""

from dataclasses import dataclass
import math

import torch

from .batched_flow import BatchedFlow


@dataclass(frozen=True)
class ActionBudget:
    absolute_tail: float = 1e-14
    max_poisson_mean: float = 8.0
    max_substeps: int = 128
    max_order: int = 128

    def __post_init__(self):
        if (not math.isfinite(self.absolute_tail) or not 1e-16 <= self.absolute_tail <= 1e-10
                or not math.isfinite(self.max_poisson_mean) or not 1 <= self.max_poisson_mean <= 32
                or type(self.max_substeps) is not int or not 1 <= self.max_substeps <= 1024
                or type(self.max_order) is not int or not 16 <= self.max_order <= 512):
            raise ValueError("bounded positive uniformization action budget required")

    def plan(self, rate, duration, maximum_reward):
        """Geometric upper bounds for Poisson tails; no cancellation of a CDF.

        A row probability/mark has L1 norm <=1. A reward accumulator's omitted
        n-th term is bounded by n*max_reward/rate. The total time-split error is
        at most T*max_reward*substeps*P(N>=order). These bounds include propagated
        truncation from earlier substeps, but not floating-point rounding.
        """
        if (min(rate, duration) <= 0 or maximum_reward < 0
                or not all(map(math.isfinite, (rate, duration, maximum_reward)))):
            raise ValueError("finite positive rate and duration required")
        substeps = max(1, math.ceil(rate * duration / self.max_poisson_mean))
        if substeps > self.max_substeps:
            raise ValueError("uniformization substep budget exhausted")
        z = rate * duration / substeps
        for order in range(max(1, math.ceil(z)), self.max_order + 1):
            p = math.exp(-z + order * math.log(z) - math.lgamma(order + 1))
            tail_previous = p / (1 - z / (order + 1))
            tail = p * z / (order + 1) / (1 - z / (order + 2))
            state_bound = substeps * tail
            integral_bound = duration * maximum_reward * substeps * tail_previous
            if max(state_bound, integral_bound) <= self.absolute_tail:
                return {"substeps": substeps, "order": order, "poisson_mean": z,
                        "state_tail_bound": state_bound, "integral_tail_bound": integral_bound}
        raise ValueError("uniformization order budget exhausted")


class UniformizedFlow(BatchedFlow):
    """Same full BatchedFlow interface with O(order*states*marks) transport work.

    Dense generator construction and the differentiable value solve remain.
    Python/Torch loop overhead can dominate small grids. A speed advantage must
    be measured for a complete forward/backward, at the same numerical quality.
    """

    def __init__(self, config, action_budget=None):
        super().__init__(config)
        self.action_budget = action_budget or ActionBudget()
        self.last_action_report = None

    def _transport(self, written, generator, event, spatial, duration):
        n, r = self.config.bins, self.config.stages
        rate = (-generator.diagonal(dim1=-2, dim2=-1)).amax()
        plan = self.action_budget.plan(float(rate.detach()), duration,
                                       max(1., float(event.detach().amax())))
        self.last_action_report = {**plan, "backend": "banded_uniformization_action",
                                   "dense_exponentials": 0, "numerical_cross_call_cache": False}
        # These are legal interval-local views of a frozen G, retaining its AD graph.
        diagonal = generator.diagonal(dim1=-2, dim2=-1)
        above = generator.diagonal(offset=1, dim1=-2, dim2=-1)[:, :n-1]
        below = generator.diagonal(offset=-1, dim1=-2, dim2=-1)[:, :n-1]
        lower, upper = generator[:, :n, n], generator[:, :n, -1]
        release = generator[:, n+r-1, :n]
        phase_next = generator[:, n:n+r-1, n+1:n+r].diagonal(dim1=-2, dim2=-1)
        qdiag = spatial[:, :n, :n].diagonal(dim1=-2, dim2=-1)
        qabove = spatial[:, :n, :n].diagonal(offset=1, dim1=-2, dim2=-1)
        qbelow = spatial[:, :n, :n].diagonal(offset=-1, dim1=-2, dim2=-1)
        qlower, qupper = spatial[:, :n, n], spatial[:, :n, n+1]

        def row_action(v):
            active = v[..., :n]
            zero = torch.zeros_like(active[..., :1])
            operated = active * diagonal[:, None, :n]
            operated = operated + torch.cat((zero, active[..., :-1] * above[:, None]), -1)
            operated = operated + torch.cat((active[..., 1:] * below[:, None], zero), -1)
            operated = operated + v[..., n+r-1:n+r] * release[:, None]
            phases = v[..., n:n+r] * diagonal[:, None, n:n+r]
            phases = phases + torch.cat(((active * lower[:, None]).sum(-1, keepdim=True),
                                         v[..., n:n+r-1] * phase_next[:, None]), -1)
            escape = (active * upper[:, None]).sum(-1, keepdim=True)
            return torch.cat((operated, phases, escape), -1)

        def column_action(v):
            active = v[:, :n]
            zero = torch.zeros_like(active[:, :1])
            operated = qdiag * active
            operated = operated + torch.cat((qabove * active[:, 1:], zero), -1)
            operated = operated + torch.cat((zero, qbelow * active[:, :-1]), -1)
            operated = operated + qlower * v[:, n:n+1] + qupper * v[:, n+1:n+2]
            return torch.cat((operated, v.new_zeros(len(v), 2)), -1)

        def reward_action(v):
            return torch.stack(((v * event[:, None]).sum(-1), v[..., :n].sum(-1)), -1)

        dt = duration / plan["substeps"]
        z = rate * dt
        probability_zero = torch.exp(-z)
        density = written
        integral = written.new_zeros(*written.shape[:-1], 2)
        hit = torch.cat((written.new_zeros(len(written), n), written.new_ones(len(written), 1),
                         written.new_zeros(len(written), 1)), -1)
        for _ in range(plan["substeps"]):
            term, count_term, hit_term = density, torch.zeros_like(integral), hit
            weight = probability_zero
            density_sum, count_sum, hit_sum = weight * term, weight * count_term, weight * hit_term
            for order in range(1, plan["order"] + 1):
                count_term = count_term + reward_action(term) / rate
                term = term + row_action(term) / rate
                hit_term = hit_term + column_action(hit_term) / rate
                weight = weight * z / order
                density_sum = density_sum + weight * term
                count_sum = count_sum + weight * count_term
                hit_sum = hit_sum + weight * hit_term
            density, hit = density_sum, hit_sum
            integral = integral + count_sum
        return density, integral, hit[:, :n]
