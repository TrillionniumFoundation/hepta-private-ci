"""Execute a frozen finite CTMC intervention policy, including instantaneous resets.

Intervened active states have zero residence time: their incoming rates and
initial mass go to the locked reset phase. Event counts and state-dependent net
payments are retained even when this creates a marked self-transition. This is
the same Erlang/finite-state law as the supplied generator, not fixed delay.
"""

from dataclasses import dataclass
import math

import torch

from qualification.hcsn_adaptive.finite_control import _control_inputs, continuation_value


@dataclass(frozen=True)
class PolicyAdvance:
    density: torch.Tensor
    natural_events: torch.Tensor
    intervention_events: torch.Tensor
    first_event: torch.Tensor
    discounted_reward: torch.Tensor


@dataclass(frozen=True)
class ImpulseKernel:
    generator: torch.Tensor
    projection: torch.Tensor
    natural_rate: torch.Tensor
    intervention_rate: torch.Tensor
    running_reward: torch.Tensor
    immediate_reward: torch.Tensor
    immediate_events: torch.Tensor
    reset_destination: torch.Tensor
    discount: float

    def value(self):
        """Full infinite-horizon value before any time-zero intervention."""
        continuing = continuation_value(self.generator, self.running_reward, self.discount)
        return self.immediate_reward + self.projection @ continuing

    def advance(self, density, duration):
        """Propagate probability and bounded signed marks; no observation writes.

        Row zero is probability and remaining rows are signed content. First
        event includes initial waiting populations and time-zero interventions.
        Reward is discounted from the start of this interval; callers compose
        successive rewards with the appropriate additional discount.
        """
        g, n = self.generator, len(self.generator)
        if (density.ndim != 2 or density.shape[-1] != n or density.shape[0] < 1
                or density.dtype != g.dtype or density.device != g.device
                or not bool(torch.isfinite(density).all())
                or not math.isfinite(duration) or duration <= 0
                or bool((density[0] < -1e-10).any())
                or abs(float(density[0].sum()) - 1) > 1e-10
                or bool((density[1:].abs() > density[:1] + 1e-10).any())):
            raise ValueError("normalized FP64 probability with bounded signed marks required")
        start = density @ self.projection
        rates = torch.stack((self.natural_rate, self.intervention_rate), -1)
        augmented = torch.cat((torch.cat((g, rates), -1), g.new_zeros(2, n + 2)), 0)
        action = torch.matrix_exp(duration * augmented)
        transitioned = start @ action[:n, :n]
        events = start @ action[:n, n:]
        initial_events = density @ self.immediate_events
        total_rate = self.natural_rate + self.intervention_rate
        # Marked self-transitions must also subtract from the killed diagonal.
        killed = g - total_rate[:, None] * self.reset_destination
        first = torch.cat((torch.cat((killed, total_rate[:, None]), -1), g.new_zeros(1, n + 1)), 0)
        first_probability = torch.matrix_exp(duration * first)[:n, n]
        survivors = density * (1 - self.immediate_events)
        first_mass = initial_events + survivors @ first_probability
        value = continuation_value(g, self.running_reward, self.discount)
        finite_value = value - math.exp(-self.discount * duration) * (action[:n, :n] @ value)
        reward = density @ self.immediate_reward + start @ finite_value
        if (not bool(torch.isfinite(transitioned).all())
                or float((transitioned.sum(-1) - density.sum(-1)).abs().max()) > 1e-10
                or bool((transitioned[0] < -1e-10).any())
                or bool((transitioned[1:].abs() > transitioned[:1] + 1e-10).any())
                or not bool(torch.isfinite(reward).all())
                or not -1e-10 <= float(first_mass[0]) <= 1 + 1e-10):
            raise FloatingPointError("controlled propagation violated a mass, mark or reward invariant")
        return PolicyAdvance(transitioned, events[:, 0], initial_events + events[:, 1],
                             first_mass, reward)


def compile_impulse_policy(generator, event_rate, running_reward, reset_payoff, *, discount,
                           active_count, reset_entry, policy):
    """Eliminate zero-residence intervention states while retaining their payments.

    event_rate tags natural off-diagonal jumps to reset_entry. Net voluntary
    payoffs are per active state; natural costs already belong in running_reward.
    Generator phase states carry the complete waiting law and remain locked.
    """
    identity, payoffs = _control_inputs(generator, running_reward, reset_payoff, discount,
                                      active_count, reset_entry)
    if (policy.shape != (active_count,) or policy.dtype != torch.bool
            or policy.device != generator.device or event_rate.shape != (len(generator),)
            or event_rate.dtype != generator.dtype or event_rate.device != generator.device
            or not bool(torch.isfinite(event_rate).all()) or bool((event_rate < 0).any())):
        raise ValueError("matching active policy and finite nonnegative natural event rates required")
    off_diagonal = generator - torch.diag_embed(generator.diagonal())
    if bool((event_rate > off_diagonal[:, reset_entry] + 1e-12).any()):
        raise ValueError("natural event rates must tag existing edges to the locked reset state")
    chosen = torch.cat((policy.to(generator), generator.new_zeros(len(generator) - active_count)))
    keep = 1 - chosen
    destination = identity[reset_entry]
    projection = keep[:, None] * identity + chosen[:, None] * destination
    effective = keep[:, None] * (generator @ projection)
    immediate = chosen * payoffs
    control_rate = keep * (off_diagonal @ chosen)
    reward = keep * (running_reward + off_diagonal @ immediate)
    return ImpulseKernel(effective, projection, keep * event_rate, control_rate,
                         reward, immediate, chosen, destination, discount)
