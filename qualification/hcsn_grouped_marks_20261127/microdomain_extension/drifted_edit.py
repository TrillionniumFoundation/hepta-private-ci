"""Derivative-free numerical inverse at general fixed drift, for an interior local target."""
import math
from typing import NamedTuple
import torch
from microdomain import IndependentFirstHit,LocalTarget


class BoundedWrite(NamedTuple):
    local: LocalTarget
    achieved_probability: float
    iterations: int
    bracket_normalized_drive: tuple[float,float]
    limiting_probabilities: tuple[float,float]


def invert_drifted_probability(probability: float, market_state: float, base_principal: float,
                              intercept: float, slope: float, fractional_drive: float,
                              law: IndependentFirstHit, tolerance: float=1e-12) -> BoundedWrite:
    """Invert an open-interval target numerically. No gradients or learned parameters change here."""
    pars=(probability,market_state,base_principal,intercept,slope,fractional_drive,tolerance)
    if not all(math.isfinite(v) for v in pars) or min(market_state,base_principal,slope,tolerance)<=0:
        raise ValueError('supply finite parameters, positive state, principal, slope and tolerance')
    if not 0<probability<1 or not 0<fractional_drive<1:raise ValueError('expected interior risk and bounded-drive coefficient')
    if intercept+slope*base_principal*(1-fractional_drive)<=0:raise ValueError('all possible walls must be positive')
    def evaluate(z):
        principal=base_principal*(1+fractional_drive*z);bound=intercept+slope*principal
        x=math.log(market_state/bound)
        q=law(torch.tensor(x,dtype=torch.float64)).release.item()
        return principal,bound,x,q
    with torch.no_grad():
        lo,hi=-1.,1.;qlo=evaluate(lo)[3];qhi=evaluate(hi)[3]
        if not qlo<probability<qhi:raise ValueError('target outside open limiting risk range')
        for it in range(1,100):
            z=(lo+hi)*.5
            if z in (lo,hi):raise ArithmeticError('target cannot be resolved at requested precision')
            principal,bound,x,q=evaluate(z)
            if abs(q-probability)<=tolerance:
                return BoundedWrite(LocalTarget(x,bound,principal,math.atanh(z),probability),q,it,(lo,hi),(qlo,qhi))
            if q<probability:lo=z
            else:hi=z
    raise ArithmeticError('did not converge in 99 steps')
