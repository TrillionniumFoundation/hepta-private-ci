"""Vectorized interior-target inverse and fixed-key covariance-weighted edits."""
import math
import torch


def zero_drift_preactivations(target,market_state,base_principal,intercept,slope,fraction,volatility,horizon,copies):
    if target.dtype!=torch.float64 or not bool(torch.isfinite(target).all()) or not bool(((target>0)&(target<1)).all()):
        raise ValueError('expected finite float64 probabilities strictly between zero and one')
    constants=(market_state,base_principal,intercept,slope,fraction,volatility,horizon)
    if not all(math.isfinite(x) for x in constants) or min(market_state,base_principal,slope,volatility,horizon)<=0 or not 0<fraction<1 or type(copies) is not int or copies<1:
        raise ValueError('invalid zero-drift law or positive-principal drive parameters')
    if intercept+slope*base_principal*(1-fraction)<=0:raise ValueError('allowed boundary must stay positive')
    single=-torch.expm1(torch.log1p(-target)/copies)
    margin=-volatility*math.sqrt(horizon)*torch.special.ndtri(single/2)
    boundary=market_state*torch.exp(-margin)
    principal=(boundary-intercept)/slope
    drive=(principal/base_principal-1)/fraction
    if not bool(torch.isfinite(drive).all()) or not bool((drive.abs()<1).all()):raise ValueError('target outside finite tanh drive domain')
    return torch.atanh(drive)


def write_rows(weights,precomputed_directions,current,desired):
    """Each row direction is C^{-1}k/(k'C^{-1}k) for that row's frozen input key."""
    if weights.ndim!=2 or weights.shape!=precomputed_directions.shape or current.shape!=(weights.shape[0],) or desired.shape!=current.shape:
        raise ValueError('each independent weight row requires its own direction and scalar preactivations')
    return weights+(desired-current)[:,None]*precomputed_directions
