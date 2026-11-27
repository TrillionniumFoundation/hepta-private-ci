"""First-hit release for conditionally independent drift-diffusion microdomains."""
import math
from typing import NamedTuple

import torch
from torch import Tensor, nn


class Step(NamedTuple):
    release: Tensor
    next_margin: Tensor
    single_survival: Tensor
    single_unconditional_surviving_margin: Tensor


class IndependentFirstHit(nn.Module):
    """Reset on a first hit by any path; aggregate the mean endpoint if all survive.

    Each call conditions on a common starting distance and fixed parameters for this
    interval. Reusing the returned mean at the next step is a moment closure.
    """
    def __init__(self, copies: int, drift: float, volatility: float, horizon: float, reset: float):
        super().__init__()
        if type(copies) is not int or copies<1:
            raise ValueError('copies must be a positive integer')
        if not all(math.isfinite(p) for p in (drift,volatility,horizon,reset)):
            raise ValueError('diffusion and reset parameters must be finite')
        if volatility<=0 or horizon<=0 or reset<0:
            raise ValueError('volatility and horizon must be positive and reset nonnegative')
        self.copies=copies;self.drift=drift;self.volatility=volatility;self.horizon=horizon;self.reset=reset

    def forward(self, distance: Tensor) -> Step:
        if distance.dtype not in (torch.float32,torch.float64):
            raise TypeError('use float32 or float64 distances')
        x=distance.clamp_min(0.)
        drift_step=self.drift*self.horizon
        volatility_step=self.volatility*math.sqrt(self.horizon)
        reflected_log=-2*self.drift*x/(self.volatility**2)+torch.special.log_ndtr((drift_step-x)/volatility_step)
        log_hit=torch.logaddexp(torch.special.log_ndtr((-x-drift_step)/volatility_step),reflected_log).clamp_max(0.)
        hit=torch.exp(log_hit);survival=-torch.expm1(log_hit)
        # Reflection cancels the two normal-density terms in the first killed moment.
        first=(x+drift_step)*survival+2*x*torch.exp(reflected_log)
        if self.copies==1:
            release=hit;retained=first
        else:
            # The log branch preserves small hit probabilities. Its masked argument
            # avoids evaluating log1p(-1) with a spurious undefined derivative at the wall.
            small=hit<.5
            safe_hit=torch.where(small,hit,torch.zeros_like(hit))
            release=torch.where(small,-torch.expm1(self.copies*torch.log1p(-safe_hit)),1-survival.pow(self.copies))
            retained=first*survival.pow(self.copies-1)
        live=distance>0
        return Step(torch.where(live,release,1.),torch.where(live,retained+self.reset*release,self.reset),
                    torch.where(live,survival,0.),torch.where(live,first,0.))


class LocalTarget(NamedTuple):
    margin: float
    boundary: float
    principal: float
    preactivation: float
    target_probability: float


def invert_local_probability(probability: float, market_state: float, base_principal: float,
                             intercept: float, slope: float, fractional_drive: float,
                             law: IndependentFirstHit, current_preactivation: float=0.) -> LocalTarget:
    """Invert an interior live first-hit probability with fixed V, B(P)=intercept+slope*P.

    P=P0*(1+fractional_drive*tanh(preactivation)); probability=1 admits a stopped set.
    For an already stopped input, preserve the existing preactivation. Otherwise use
    the wall itself when reachable. At probability zero, finite boundaries never suffice.
    """
    parameters=(probability,market_state,base_principal,intercept,slope,fractional_drive,current_preactivation)
    if not all(math.isfinite(v) for v in parameters) or not 0<=probability<=1:
        raise ValueError('all parameters must be finite and probability must lie in [0,1]')
    if law.drift!=0.:raise ValueError('closed-form inversion requires zero log drift')
    if min(market_state,base_principal,slope)<=0 or not 0<fractional_drive<1:
        raise ValueError('invalid state or drive parameterization')
    if intercept+slope*base_principal*(1-fractional_drive)<=0:raise ValueError('allowed boundary must stay positive')
    if probability==0:raise ValueError('zero probability requires infinite live distance')
    def from_drive(z):return base_principal*(1+fractional_drive*math.tanh(z))
    if probability==1:
        current_principal=from_drive(current_preactivation);current_boundary=intercept+slope*current_principal
        if current_boundary>=market_state:
            return LocalTarget(math.log(market_state/current_boundary),current_boundary,current_principal,current_preactivation,probability)
        margin=0.
    else:
        # At zero drift F=2*Phi(-x/(sigma*sqrt(T))). expm1 retains small target probabilities.
        single_hit=-math.expm1(math.log1p(-probability)/law.copies)
        if single_hit/2==0:raise ValueError('positive target below floating point inverse resolution')
        z=float(torch.special.ndtri(torch.tensor(single_hit/2,dtype=torch.float64)))
        margin=-law.volatility*math.sqrt(law.horizon)*z
    boundary=market_state*math.exp(-margin)
    lo=intercept+slope*base_principal*(1-fractional_drive)
    hi=intercept+slope*base_principal*(1+fractional_drive)
    if not lo<boundary<hi:raise ValueError('requested boundary is outside the open tanh drive range')
    principal=(boundary-intercept)/slope
    drive=(principal/base_principal-1)/fractional_drive
    if not -1<drive<1:raise ValueError('target lies at finite-precision saturation')
    return LocalTarget(margin,boundary,principal,math.atanh(drive),probability)


def minimum_cost_write(weights: Tensor, keys: Tensor, desired_changes: Tensor, covariance: Tensor,
                       tolerance: float=1e-10) -> Tensor:
    """Return the minimum positive-definite covariance-cost row satisfying all key edits.

    Each row of keys is a frozen, deterministic input. A zero desired change protects
    that row's preactivation. The caller subtracts the fixed bias and previous logits.
    The solver refuses inconsistent linear constraints, including conflicting duplicates.
    """
    if weights.ndim!=1 or keys.ndim!=2 or keys.shape[1]!=weights.numel() or keys.shape[0]<1:
        raise ValueError('keys must be a nonempty matrix with one column per weight')
    if desired_changes.shape!=(keys.shape[0],) or covariance.shape!=(weights.numel(),weights.numel()):
        raise ValueError('incompatible constraint or covariance shapes')
    if any(t.dtype!=torch.float64 or t.device!=weights.device or not torch.isfinite(t).all() for t in (weights,keys,desired_changes,covariance)):
        raise ValueError('use finite float64 tensors on one device')
    if not math.isfinite(tolerance) or tolerance<=0:raise ValueError('tolerance must be positive')
    if not torch.allclose(covariance,covariance.T,rtol=tolerance,atol=tolerance):raise ValueError('cost matrix must be symmetric')
    chol,info=torch.linalg.cholesky_ex(covariance)
    if int(info)!=0:raise ValueError('cost matrix must be positive definite')
    whitened=torch.linalg.solve_triangular(chol,keys.T,upper=False).T
    whitened_delta=torch.linalg.pinv(whitened,rtol=tolerance)@desired_changes
    delta=torch.linalg.solve_triangular(chol.T,whitened_delta[:,None],upper=True)[:,0]
    if not torch.allclose(keys@delta,desired_changes,rtol=tolerance*10,atol=tolerance*10):
        raise ValueError('inconsistent or numerically unresolved frozen-key constraints')
    return weights+delta
