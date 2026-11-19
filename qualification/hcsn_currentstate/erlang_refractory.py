"""Fixed-law Erlang refractory approximation, not an exact deterministic delay.

An active lower hit enters phase 1. K exponential stages at rate K/d then
return mass and each signed mark to the single active state. The model retains
the original cumulative observables. It has no event-time parameter metadata
and makes no claim about varying-input/reset continuation.
"""

from dataclasses import dataclass, fields
from fractions import Fraction

import torch


@dataclass(frozen=True)
class Physics:
    rate: torch.Tensor
    stage_rate: torch.Tensor
    discount: torch.Tensor
    generator: torch.Tensor
    firing: torch.Tensor
    occupation_weight: torch.Tensor

    def tensor_bytes(self):
        return {f.name: getattr(self, f.name).numel()*getattr(self, f.name).element_size() for f in fields(self)}


@dataclass(frozen=True)
class State:
    time: Fraction
    active: torch.Tensor
    phase: torch.Tensor
    upper: torch.Tensor
    hits: torch.Tensor
    discounted_hits: torch.Tensor
    occupation: torch.Tensor
    value: torch.Tensor
    discount_factor: torch.Tensor

    def tensor_bytes(self):
        return {f.name: getattr(self, f.name).numel()*getattr(self, f.name).element_size()
                for f in fields(self) if f.name != 'time'}


def physics(rate, stages, delay=Fraction(1,5), discount=.15):
    if rate.ndim or rate.dtype != torch.float64 or not bool(torch.isfinite(rate)) or not bool(rate > 0):
        raise ValueError('positive finite FP64 scalar rate required')
    if type(stages) is not int or not 2 <= stages <= 128 or not isinstance(delay, Fraction) or delay <= 0:
        raise ValueError('fixed 2..128 stages and positive rational mean delay required')
    stage_rate = rate.new_tensor(float(Fraction(stages)/delay))
    rates = torch.cat((rate.reshape(1), stage_rate.expand(stages)))
    wrap = rate.new_zeros(stages+1, stages+1)
    wrap[-1,0] = stage_rate
    generator = torch.diag(-rates)+torch.diag(rates[:-1],1)+wrap
    firing = torch.cat((rate.reshape(1), rate.new_zeros(stages)))
    occupation = torch.cat((rate.new_ones(1), rate.new_zeros(stages)))
    return Physics(rate, stage_rate, rate.new_tensor(discount), generator, firing, occupation)


def initial(marks, stages):
    zero = marks.new_zeros(marks.shape)
    return State(Fraction(0), marks[:,None], marks.new_zeros(marks.numel(),stages),
                 zero, zero, zero, zero, zero, marks.new_ones(()))


def _integrals(generator, weights, duration, work):
    n = generator.shape[0]
    augmented = torch.cat((torch.cat((generator, weights),1), generator.new_zeros(2,n+2)),0)
    work['explicit_exponentials'] += 1
    work['largest_matrix'] = max(work['largest_matrix'], n+2)
    work['augmented_input_bytes'].append(augmented.numel()*augmented.element_size())
    transition = torch.matrix_exp(augmented*duration)
    if not bool(torch.isfinite(transition).all()):
        raise FloatingPointError('nonfinite Erlang semigroup')
    return transition[:n,:n], transition[:n,n:]


def advance(state, law, target, work):
    if not isinstance(target, Fraction) or target < state.time:
        raise ValueError('nondecreasing rational time required')
    duration = float(target-state.time)
    mass = torch.cat((state.active,state.phase),1)
    transition, integral = _integrals(law.generator,
        torch.stack((law.firing,law.occupation_weight),1), duration, work)
    current, increments = mass@transition, mass@integral
    _, discounted = _integrals(law.generator-law.discount*torch.eye(
        law.generator.shape[0], dtype=law.generator.dtype, device=law.generator.device),
        torch.stack((law.firing,torch.zeros_like(law.firing)),1), duration, work)
    credit = state.discount_factor*(mass@discounted)[:,0]
    # Active/escape reward is zero, spike reward is one, terminal payoff zero.
    return State(target,current[:,:1],current[:,1:],state.upper,
        state.hits+increments[:,0],state.discounted_hits+credit,
        state.occupation+increments[:,1]+duration*state.upper,state.value+credit,
        state.discount_factor*torch.exp(-law.discount*duration))
