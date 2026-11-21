"""Frozen finite-process channels and a small continuous-time impulse-control reference.

Rows of G are CTMC rates; probability is a row vector. Rewards are supplied task
outcomes/rates, never labels manufactured from this solver. Automatic events and
their post-event phases remain in G. Optional interventions jump to a *locked*
phase, so their value includes subsequent release, operation and future events.
The optimal intervention set need not be a threshold. This reference solves the
declared finite process, not a diffusion QVI or a learned task benchmark.
"""

from dataclasses import dataclass
import math

import torch


@dataclass(frozen=True)
class DelayLaw:
    """Zero-reward waiting time before reset; deterministic has no finite phases."""

    kind: str
    mean: float
    stages: int = 0

    def __post_init__(self):
        if (self.kind not in ("deterministic", "erlang")
                or not math.isfinite(self.mean) or self.mean <= 0
                or type(self.stages) is not int
                or (self.kind == "deterministic" and self.stages != 0)
                or (self.kind == "erlang" and self.stages < 1)):
            raise ValueError("declare deterministic delay or a positive Erlang phase count")

    def discount_factor(self, discount):
        """Only a continuation factor, not an interchangeable state propagator."""
        if not math.isfinite(discount) or discount <= 0:
            raise ValueError("positive finite discount required")
        if self.kind == "deterministic":
            return math.exp(-discount * self.mean)
        return math.exp(-self.stages * math.log1p(discount * self.mean / self.stages))


def _validate_generator(generator):
    if (generator.ndim != 2 or generator.shape[0] != generator.shape[1]
            or not 2 <= len(generator) <= 256 or generator.dtype != torch.float64
            or not bool(torch.isfinite(generator).all())):
        raise ValueError("finite FP64 square generator of size 2..256 required")
    off_diagonal = generator - torch.diag_embed(generator.diagonal())
    if (bool((off_diagonal < 0).any()) or bool((generator.diagonal() > 0).any())
            or float(generator.sum(-1).abs().max()) > 1e-10):
        raise ValueError("generator must have nonnegative off-diagonals and zero row sums")


def continuation_value(generator, running_reward, discount):
    """Differentiable resolvent, including all reset/refractory states already in G.

    Batch dimensions are allowed. The caller owns generator construction and its
    state-law validation; BatchedFlow uses this on its validated frozen process.
    """
    if (not math.isfinite(discount) or discount <= 0
            or generator.ndim < 2 or generator.shape[-2] != generator.shape[-1]
            or running_reward.shape != generator.shape[:-1]):
        raise ValueError("positive discount and matching generator/reward shapes required")
    identity = torch.eye(generator.shape[-1], dtype=generator.dtype, device=generator.device)
    return torch.linalg.solve(discount * identity - generator, running_reward.unsqueeze(-1)).squeeze(-1)


def frozen_channels(generator, event_rate, running_reward, *, discount, duration, event_destination):
    """Value, all-event count and first-event risk from one finite generator.

    First risk here includes initial phase mass that releases and later fires.
    BatchedFlow's narrower initial-active risk is obtained by weighting this
    vector only with its active starting mass, then adding boundary-jump hits.
    Marked events must be off-diagonal jumps to event_destination.
    """
    _validate_generator(generator)
    n = len(generator)
    if (type(event_destination) is not int or not 0 <= event_destination < n
            or event_rate.shape != (n,) or running_reward.shape != (n,)
            or any(t.dtype != generator.dtype or t.device != generator.device
                   or not bool(torch.isfinite(t).all()) for t in (event_rate, running_reward))
            or bool((event_rate < 0).any()) or event_rate[event_destination] != 0
            or not math.isfinite(duration) or duration <= 0):
        raise ValueError("matching finite rewards and nonnegative marked off-diagonal rates required")
    destination = torch.eye(n, dtype=generator.dtype, device=generator.device)[event_destination]
    marked = event_rate[:, None] * destination
    off_diagonal = generator - torch.diag_embed(generator.diagonal())
    if bool((marked > off_diagonal + 1e-12).any()):
        raise ValueError("marked event rate exceeds the corresponding generator edge")
    zero = generator.new_zeros(1, n + 1)
    counted = torch.cat((torch.cat((generator, event_rate[:, None]), -1), zero), 0)
    killed = generator - marked  # Keep the original holding/exit diagonal.
    first = torch.cat((torch.cat((killed, event_rate[:, None]), -1), zero), 0)
    counted_action = torch.matrix_exp(duration * counted)
    first_action = torch.matrix_exp(duration * first)
    return {
        "transition": counted_action[:n, :n],
        "expected_events": counted_action[:n, n],
        "first_event_probability": first_action[:n, n],
        "value": continuation_value(generator, running_reward, discount),
        "discounted_events": continuation_value(generator, event_rate, discount),
    }


def _control_inputs(generator, running_reward, reset_payoff, discount, active_count, reset_entry):
    _validate_generator(generator)
    n = len(generator)
    if (type(active_count) is not int or not 1 <= active_count < n
            or type(reset_entry) is not int or not active_count <= reset_entry < n
            or running_reward.shape != (n,) or reset_payoff.shape != (active_count,)
            or not math.isfinite(discount) or discount <= 0
            or any(t.dtype != generator.dtype or t.device != generator.device
                   or not bool(torch.isfinite(t).all()) for t in (running_reward, reset_payoff))):
        raise ValueError("finite matching task rewards and a locked post-reset state required")
    identity = torch.eye(n, dtype=generator.dtype, device=generator.device)
    payoffs = torch.cat((reset_payoff, generator.new_zeros(n - active_count)))
    return identity, payoffs


@torch.no_grad()
def evaluate_impulse_policy(generator, running_reward, reset_payoff, *, discount,
                            active_count, reset_entry, policy):
    """Evaluate a stationary active-state intervention policy with full continuation.

    reset_payoff is the NET instantaneous task reward/cost of a voluntary event.
    Natural event costs belong in running_reward through their rates. Waiting
    and release after voluntary reset are exactly those of reset_entry in G.
    """
    identity, payoffs = _control_inputs(generator, running_reward, reset_payoff, discount,
                                      active_count, reset_entry)
    if (policy.shape != (active_count,) or policy.dtype != torch.bool
            or policy.device != generator.device):
        raise ValueError("one boolean intervention decision per active state required")
    intervention = torch.cat((policy, torch.zeros(len(generator) - active_count,
                                                 dtype=torch.bool, device=generator.device)))
    equations = torch.where(intervention[:, None], identity - identity[reset_entry],
                            discount * identity - generator)
    rhs = torch.where(intervention, payoffs, running_reward)
    value = torch.linalg.solve(equations, rhs)
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError("nonfinite policy continuation")
    return value


@dataclass(frozen=True)
class ImpulseSolution:
    value: torch.Tensor
    reset_policy: torch.Tensor
    bellman_residual: float
    iterations: int


@torch.no_grad()
def solve_impulse_control(generator, running_reward, reset_payoff, *, discount,
                          active_count, reset_entry, tolerance=1e-10, max_iterations=128):
    """Howard iteration for the finite CTMC QVI; no assumed threshold ordering.

    Uniformization compares continue and reset in value units, not a mixture of
    reward rates and instantaneous rewards. Ties retain the current action.
    The returned residual is the uniformized Bellman value residual.
    """
    identity, _ = _control_inputs(generator, running_reward, reset_payoff, discount,
                                 active_count, reset_entry)
    if (not math.isfinite(tolerance) or tolerance <= 0
            or type(max_iterations) is not int or not 1 <= max_iterations <= 4096):
        raise ValueError("positive tolerance and bounded iteration budget required")
    rate = float((-generator.diagonal()).max())
    transition = (rate * identity + generator) / (discount + rate)
    reward = running_reward / (discount + rate)
    policy = torch.zeros(active_count, dtype=torch.bool, device=generator.device)
    for iteration in range(1, max_iterations + 1):
        value = evaluate_impulse_policy(generator, running_reward, reset_payoff, discount=discount,
                                        active_count=active_count, reset_entry=reset_entry, policy=policy)
        continuing = reward + transition @ value
        resetting = reset_payoff + value[reset_entry]
        difference = resetting - continuing[:active_count]
        next_policy = torch.where(difference.abs() <= tolerance, policy, difference > 0)
        target = torch.cat((torch.maximum(continuing[:active_count], resetting),
                            continuing[active_count:]))
        residual = float((target - value).abs().max())
        if torch.equal(policy, next_policy) and residual <= tolerance:
            return ImpulseSolution(value, policy, residual, iteration)
        policy = next_policy
    raise RuntimeError("finite impulse-control iteration did not meet its Bellman tolerance")
