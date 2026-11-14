"""Budget-observed sequence-model comparators for the RR-SNN experiment.

These are TRAINING PROXIES on a supplied observation grid, not the exact
continuous-time event simulator in ../runtime.  Hard modes emit binary events;
their backward rules are explicitly biased surrogates.  First-passage cells use
the killed-process conditional MEAN after survival, a moment closure rather
than an exact sampled state.  At most one internal spike is represented per
observation interval.  Results must not be represented as exact-runtime results.

All comparators have exactly the same trainable input matrix, recurrent matrix
and bias at fixed input_size/hidden_size.  Mechanism constants are fixed and
listed below.  Actual state usage differs and is reported by state_accounting.
The environment's legal-action mask and real budget ledger belong outside this
module.  The internal energy proxy is dimensionless and is not hardware energy.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Iterable, Sequence

import numpy as np
import torch
from torch import nn


CANONICAL_VARIANTS = (
    "lif", "alif", "resource_lif", "fp_no_maturity", "fp_multi_fixed",
    "rr_full", "ctrnn",
)
ALIASES = {
    "LIF": "lif", "ALIF": "alif", "LSNN": "alif",
    "resource-lif": "resource_lif", "resource-LIF": "resource_lif",
    "no_maturity": "fp_no_maturity", "first_passage": "fp_no_maturity",
    "multi_fixed": "fp_multi_fixed", "rr": "rr_full", "RR-SNN": "rr_full",
    "continuous_rnn": "ctrnn", "ct_rnn": "ctrnn",
}


@dataclass(frozen=True)
class MechanismConstants:
    lif_tau: float = 1.25
    lif_threshold: float = 0.65
    adaptation_tau: float = 3.0
    adaptation_strength: float = 0.30
    trace_tau: float = 2.5
    memory_tau: float = 4.0
    refractory: float = 0.10
    sigma: float = 0.40
    discount: float = 0.40
    emission_cost: float = 0.20
    resource_price: float = 0.30
    rollover_price: float = 0.12
    fixed_fp_threshold: float = 1.25
    energy_tau: float = 1.25
    proxy_spike_cost: float = 0.035
    proxy_hold_cost: float = 0.002
    renewal_unit_cost: float = 0.035
    horizon_scale: float = 4.0
    minimum_remaining: float = 0.25
    numerical_nodes: int = 48


def _as_double(*values):
    return [v.to(torch.float64) if torch.is_tensor(v)
            else torch.as_tensor(v, dtype=torch.float64) for v in values]


def first_hit_cdf(x, t, mu, sigma):
    """Stable analytic lower-boundary first passage on the positive interior.

    x,t must be positive.  The call site handles already-hit/zero-dt events.
    Internally using float64 limits cancellation; the result preserves x.dtype.
    """
    dtype = x.dtype
    xx, tt, mm = _as_double(x, t, mu)
    ss = torch.as_tensor(sigma, dtype=torch.float64, device=x.device)
    scale = ss * torch.sqrt(tt)
    log_a = torch.special.log_ndtr((-xx-mm*tt)/scale)
    log_b = -2*mm*xx/(ss*ss) + torch.special.log_ndtr((-xx+mm*tt)/scale)
    log_f = torch.logaddexp(log_a, log_b).clamp(max=0.0)
    return torch.exp(log_f).to(dtype)


def discounted_hit(x, t, mu, sigma, rho):
    dtype = x.dtype
    xx, tt, mm = _as_double(x, t, mu)
    ss = torch.as_tensor(sigma, dtype=torch.float64, device=x.device)
    rr = torch.as_tensor(rho, dtype=torch.float64, device=x.device)
    nu = torch.sqrt(mm*mm+2*rr*ss*ss)
    scale = ss*torch.sqrt(tt)
    log_a = (-mm+nu)*xx/(ss*ss)+torch.special.log_ndtr((-xx-nu*tt)/scale)
    log_b = (-mm-nu)*xx/(ss*ss)+torch.special.log_ndtr((-xx+nu*tt)/scale)
    return torch.exp(torch.logaddexp(log_a, log_b).clamp(max=0.0)).to(dtype)


def numerical_hit_integral(x, t, mu, sigma, rho=0.0, nodes=48):
    """Gauss-Legendre density integration, not reuse of the analytic CDF.

    Substitution s=x/(sigma*sqrt(tau)) removes the narrow tau=0 peak:
      H_rho = integral_{s0}^infty sqrt(2/pi)
                exp[-(s+beta/s)^2/2-rho*x^2/(sigma^2*s^2)] ds.
    The finite upper tail and finite quadrature are numerical approximations.
    Suitable as a SAME-WEIGHTS numerical-kernel control, not an accuracy oracle.
    """
    dtype = x.dtype
    xx, tt, mm = _as_double(x, t, mu)
    ss = torch.as_tensor(sigma, dtype=torch.float64, device=x.device)
    s0 = xx/(ss*torch.sqrt(tt))
    beta = mm*xx/(ss*ss)
    high = torch.maximum(s0+12.0, torch.sqrt(beta.abs()+1e-12)+12.0)
    n, w = _legendre(nodes, x.device)
    # A separate near-lower-limit interval resolves the boundary layer when
    # x is tiny. A single global quadrature materially under-resolves that case.
    split=s0+torch.minimum(torch.ones_like(s0),0.1+torch.sqrt(beta.abs()+1e-12))
    out=torch.zeros_like(s0)
    for low,upper in ((s0,split),(split,high)):
        s = low.unsqueeze(-1)+(upper-low).unsqueeze(-1)*(n+1)/2
        power = -.5*(s+beta.unsqueeze(-1)/s)**2
        power = power-float(rho)*xx.unsqueeze(-1)**2/(ss*ss*s*s)
        integrand = math.sqrt(2/math.pi)*torch.exp(power)
        out = out+(upper-low)/2*torch.sum(w*integrand, dim=-1)
    return out.clamp(min=0.0,max=1.0).to(dtype)


_LEGENDRE_CACHE = {}


def _legendre(n, device):
    key = (n,str(device))
    if key not in _LEGENDRE_CACHE:
        x,w = np.polynomial.legendre.leggauss(n)
        _LEGENDRE_CACHE[key] = (
            torch.tensor(x,dtype=torch.float64,device=device),
            torch.tensor(w,dtype=torch.float64,device=device))
    return _LEGENDRE_CACHE[key]


def surviving_distance_mean(x, t, mu, sigma, min_survival=1e-12):
    """Exact conditional mean in the unclipped interior, then safe tail clamp.

    E[X_t | tau>t] = x+mu*t+2*x*B/S, where B is the reflection CDF term.
    Moment closure is a MODEL APPROXIMATION even when this scalar mean is exact.
    Extremely tiny survival is clamped to avoid ill-conditioned floating-point
    ratios. Callers must not describe this tail clamp as an exact distribution.
    """
    dtype = x.dtype
    xx, tt, mm = _as_double(x,t,mu)
    ss = torch.as_tensor(sigma,dtype=torch.float64,device=x.device)
    scale=ss*torch.sqrt(tt)
    log_a=torch.special.log_ndtr((-xx-mm*tt)/scale)
    log_b=-2*mm*xx/(ss*ss)+torch.special.log_ndtr((-xx+mm*tt)/scale)
    log_f=torch.logaddexp(log_a,log_b).clamp(max=-min_survival)
    survival=(-torch.expm1(log_f)).clamp(min=min_survival)
    conditional=xx+mm*tt+2*xx*torch.exp(log_b)/survival
    return conditional.clamp(min=1e-5,max=50.0).to(dtype)


class _LambertW0(torch.autograd.Function):
    @staticmethod
    def forward(ctx,z):
        # This model stays strictly inside (-1/e, 0), away from the branch point.
        zd=z.to(torch.float64)
        w=zd.clone()
        for _ in range(16):
            ew=torch.exp(w)
            f=w*ew-zd
            denominator=ew*(w+1)-(w+2)*f/(2*w+2)
            w=w-f/denominator
        ctx.save_for_backward(w,zd)
        return w.to(z.dtype)

    @staticmethod
    def backward(ctx,grad):
        w,z=ctx.saved_tensors
        derivative=w/(z*(1+w))
        return (grad.to(torch.float64)*derivative).to(grad.dtype)


def lambert_w0(z):
    return _LambertW0.apply(z)


def optimal_reset_threshold(a, sigma, rho, cost, reset=0.0, refractory=0.10):
    """Frozen-parameter scalar impulse-control threshold, NOT full dynamic QVI."""
    root=torch.sqrt(a*a+2*float(rho)*float(sigma)**2)
    gamma=(root-a)/(float(sigma)**2)
    gamma=gamma.clamp(min=1e-5)
    c=cost.clamp(min=float(reset)+0.025)
    z=-torch.exp(-float(rho)*float(refractory)-1-gamma*(c-float(reset)))
    return c+(1+lambert_w0(z))/gamma


class _HardThreshold(torch.autograd.Function):
    @staticmethod
    def forward(ctx,x):
        ctx.save_for_backward(x)
        return (x>=0).to(x.dtype)

    @staticmethod
    def backward(ctx,grad):
        (x,)=ctx.saved_tensors
        return grad*5.0/(1+5.0*x.abs())**2


class SurrogateSequenceModel(nn.Module):
    """Matched-parameter sequence encoder; a common external head chooses actions.

    Default feature contract (F=22): resource index 4 is real external budget/6;
    maturity indices 7:11 contain item remaining times / 4 (NOT histogram mass);
    alive indices 11:15 identify actual obligations. The input projection sees
    ALL features for every comparator. Fixed mechanism shortcuts are reported.

    mode='hard': true binary forward events with biased surrogate backward.
    mode='expected': continuous event probabilities; NOT a hard-spiking network.
    The common trainer must report which mode it used.
    """
    def __init__(self,variant,input_size,hidden_size=16,resource_index=4,
                 maturity_indices=(7,8,9,10),alive_indices=(11,12,13,14),
                 horizons=None,ablations:Iterable[str]=(),mode='hard',
                 maturity_shuffle_seed=271828,
                 constants:MechanismConstants|None=None):
        super().__init__()
        self.variant=ALIASES.get(variant,variant)
        if self.variant not in CANONICAL_VARIANTS:
            raise ValueError(f'Unknown variant: {variant}')
        if mode not in ('hard','expected'):
            raise ValueError("mode must be 'hard' or 'expected'")
        self.input_size=int(input_size)
        self.hidden_size=int(hidden_size)
        self.resource_index=int(resource_index)
        self.maturity_indices=tuple(maturity_indices)
        self.alive_indices=tuple(alive_indices)
        self.ablations=frozenset(ablations)
        self.mode=mode
        self.maturity_shuffle_seed=int(maturity_shuffle_seed)
        self.constants=constants or MechanismConstants()
        self.input_layer=nn.Linear(input_size,hidden_size,bias=True)
        self.recurrent_layer=nn.Linear(hidden_size,hidden_size,bias=False)
        nn.init.xavier_uniform_(self.input_layer.weight,gain=0.7)
        nn.init.zeros_(self.input_layer.bias)
        nn.init.orthogonal_(self.recurrent_layer.weight,gain=0.25)
        # horizons retained only as caller metadata; the supplied schema uses
        # per-item remaining times, not fixed histogram bins.
        self.horizons=None if horizons is None else tuple(horizons)

    def state_accounting(self,batch_size=1,dtype_bytes=4):
        h=self.hidden_size
        names={'evidence':h,'event_trace':h,'previous_event':h,'refractory':h}
        if self.variant=='ctrnn':
            names={'continuous_hidden':h}
        elif self.variant=='alif':
            names['adaptation']=h
        elif self.variant=='resource_lif':
            names['energy_proxy']=h
        elif self.variant.startswith('fp_') or self.variant=='rr_full':
            names['energy_proxy']=h
            if self.variant in ('fp_multi_fixed','rr_full'):
                names['retained_memory']=h
        if 'frozen_resource' in self.ablations and ('energy_proxy' in names):
            names['frozen_resource_reference']=1
        return {
            'trainable_parameters':sum(p.numel() for p in self.parameters()),
            'state_scalars_per_sequence':sum(names.values()),
            'active_state_bytes_per_sequence':sum(names.values())*dtype_bytes,
            'active_state_bytes_batch':sum(names.values())*dtype_bytes*batch_size,
            'state_components':names,
            'excludes':'input sequence, external deadline queue, output head, autograd tape, temporary quadrature tensors',
        }

    def metadata(self):
        return {
            'variant':self.variant,'mode':self.mode,'ablations':sorted(self.ablations),
            'constants':asdict(self.constants),'accounting':self.state_accounting(),
            'all_features_visible_to_every_model':True,
            'maturity_shuffle':('causal resampling from already observed historical profiles; original projection unchanged'
                                if 'shuffle_maturity' in self.ablations else None),
            'maturity_shuffle_seed':self.maturity_shuffle_seed,
            'mathematical_equivalences':[
                'fp_multi_fixed equals rr_full + fixed_boundary at the same weights and random numbers.',
                'Consistently permuting item remaining/alive pairs leaves symmetric maturity aggregation unchanged.',
            ],
            'is_complete_lsnn_recipe':False,'is_cfc':False,
            'exact_event_runtime':False,
            'limitations':[
                'Observation-grid proxy with at most one internal event per interval.',
                'Hard mode uses biased surrogate gradients.',
                'First-passage survival propagation uses a conditional-mean closure.',
                'Dynamic RR threshold is a frozen-parameter control approximation.',
                'Resource proxy is dimensionless; real legal actions and accounting are external.',
                'All methods have equal trainable parameters but differing actual state usage.',
            ],
        }

    def _dt(self,dt,x):
        b,t,_=x.shape
        value=torch.as_tensor(dt,dtype=x.dtype,device=x.device)
        if value.ndim==0:
            return value.expand(b,t)
        if value.ndim==1:
            if value.numel()!=t:
                raise ValueError('1D dt must have T elements')
            return value.unsqueeze(0).expand(b,t)
        if value.shape!=(b,t):
            raise ValueError('dt must be scalar, [T], or [B,T]')
        return value

    def _maturity(self,xt):
        c=self.constants
        remaining=xt[:,self.maturity_indices].clamp(min=0)*c.horizon_scale
        alive=xt[:,self.alive_indices].clamp(min=0,max=1)
        count=alive.sum(dim=-1,keepdim=True)
        if 'collapse_maturity' in self.ablations:
            mean=(remaining*alive).sum(dim=-1,keepdim=True)/count.clamp(min=1)
            remaining=mean.expand_as(remaining)
        pressure=(alive/(remaining+c.minimum_remaining)).sum(dim=-1,keepdim=True)/max(1,len(self.maturity_indices))
        return remaining,alive,pressure

    def _kernel(self,x,t,mu,discount=0.0):
        c=self.constants
        if 'numerical_kernel' in self.ablations:
            return numerical_hit_integral(x,t,mu,c.sigma,rho=discount,nodes=c.numerical_nodes)
        if discount:
            return discounted_hit(x,t,mu,c.sigma,discount)
        return first_hit_cdf(x,t,mu,c.sigma)

    def forward(self,x,dt=1.0,generator=None):
        if x.ndim!=3 or x.shape[-1]!=self.input_size:
            raise ValueError('x must have shape [B,T,input_size]')
        dts=self._dt(dt,x)
        if bool(torch.any(dts<0)):
            raise ValueError('negative dt is invalid')
        c=self.constants
        b,t,_=x.shape
        h=self.hidden_size
        zero=x.new_zeros((b,h))
        evidence=zero.clone()
        trace=zero.clone()
        previous=zero.clone()
        refractory=zero.clone()
        adaptation=zero.clone()
        initial_energy=x[:,0,self.resource_index:self.resource_index+1].clamp(0,1).clone()
        energy=initial_energy.expand(b,h).clone()
        retained=zero.clone()
        projected=self.input_layer(x)
        history_rng=np.random.default_rng(self.maturity_shuffle_seed)
        latents=[];events=[];probs=[];energies=[];thresholds=[]

        for step in range(t):
            interval=dts[:,step:step+1]
            # A zero-duration cue is still an observation update, represented by
            # an explicitly documented 0.05 model-time encoding interval.
            effective_dt=torch.where(interval>0,interval,torch.full_like(interval,0.05))
            pre=projected[:,step]+self.recurrent_layer(previous)
            target=x[:,step,self.resource_index:self.resource_index+1].clamp(0,1).expand(b,h)
            if self.variant=='ctrnn':
                decay=torch.exp(-effective_dt/c.lif_tau)
                evidence=decay*evidence+(1-decay)*torch.tanh(pre)
                previous=evidence
                latent=evidence
                spike=zero
                probability=zero
                threshold=torch.ones_like(zero)
                energy=target
            else:
                active_dt=(effective_dt-refractory).clamp(min=0)
                active=(active_dt>0).to(x.dtype)
                refractory=(refractory-effective_dt).clamp(min=0)
                safe_dt=active_dt.clamp(min=1e-4)
                energy=target+(energy-target)*torch.exp(-effective_dt/c.energy_tau)
                energy=(energy-c.proxy_hold_cost*effective_dt).clamp(min=0,max=1)
                observed_energy=initial_energy.expand(b,h) if 'frozen_resource' in self.ablations else energy
                if self.variant in ('lif','alif','resource_lif'):
                    current=1.25*torch.sigmoid(pre)
                    decay=torch.exp(-active_dt/c.lif_tau)
                    before=evidence*decay+current*(1-decay)
                    threshold=torch.full_like(before,c.lif_threshold)
                    if self.variant=='alif':
                        adaptation=adaptation*torch.exp(-effective_dt/c.adaptation_tau)
                        threshold=threshold+c.adaptation_strength*adaptation
                    elif self.variant=='resource_lif':
                        threshold=threshold*(1+c.resource_price*(1-observed_energy))
                        permitted=(energy>=c.proxy_spike_cost).to(x.dtype)
                        active=active*permitted
                        before=torch.where(permitted.bool(),before,evidence)
                    probability=torch.sigmoid(5*(before-threshold))*active
                    if self.mode=='expected':
                        spike=probability
                    else:
                        spike=_HardThreshold.apply(before-threshold)*active
                    if self.variant=='resource_lif':
                        spike=spike*(energy>=c.proxy_spike_cost).to(x.dtype)
                    reset_weight=spike if self.mode=='expected' else spike.detach()
                    evidence=(1-reset_weight)*before
                    if self.variant=='alif':
                        adaptation=adaptation+spike
                else:
                    # If the resource proxy forbids the cell from running,
                    # freeze its evidence; do not condition on "no hit" when a
                    # real hit could merely have been hidden by a firing gate.
                    permitted=(energy>=c.proxy_spike_cost).to(x.dtype)
                    active=active*permitted
                    drive=0.45+0.8*torch.tanh(pre)
                    multi=self.variant in ('fp_multi_fixed','rr_full')
                    if multi:
                        drive=drive+0.25*retained
                    drive=drive.clamp(min=-0.6,max=1.5)
                    cost=c.emission_cost+c.resource_price*(1-observed_energy)
                    provisional=optimal_reset_threshold(drive,c.sigma,c.discount,cost,refractory=c.refractory)
                    pressure=zero[:,0:1]
                    retain_gate=torch.ones_like(zero)
                    if multi:
                        maturity_step=step
                        if 'shuffle_maturity' in self.ablations:
                            maturity_step=int(history_rng.integers(0,step+1))
                        remaining,alive,pressure=self._maturity(x[:,maturity_step])
                        horizons=remaining.clamp(min=0.05)[:,None,:]
                        distance=(provisional-evidence).clamp(min=1e-4)[:,:,None]
                        mu=-drive[:,:,None]
                        future_hit=self._kernel(distance,horizons,mu)
                        future_discounted=self._kernel(distance,horizons,mu,discount=c.discount)
                        value=torch.exp(-c.discount*horizons)*(1-future_hit)+0.2*future_discounted
                        weights=alive[:,None,:]
                        q=(value*weights).sum(dim=-1)/weights.sum(dim=-1).clamp(min=1)
                        # Surplus is an explicit heuristic using the analytic
                        # lifetime readout. It is not a solved dynamic QVI.
                        shadow=1+c.resource_price*(1-observed_energy)
                        retain_gate=torch.sigmoid(6*(q-shadow*c.renewal_unit_cost))
                        if self.variant=='rr_full' and 'no_rollover' not in self.ablations:
                            cost=cost+c.rollover_price*pressure*(1-q)
                        if 'no_rollover' in self.ablations:
                            retain_gate=torch.ones_like(retain_gate)
                    if self.variant=='fp_multi_fixed' or 'fixed_boundary' in self.ablations:
                        threshold=torch.full_like(evidence,c.fixed_fp_threshold)
                    else:
                        threshold=optimal_reset_threshold(drive,c.sigma,c.discount,cost,refractory=c.refractory)
                    distance=(threshold-evidence).clamp(min=1e-4)
                    probability=self._kernel(distance,safe_dt,-drive)*active
                    # Previously-over-threshold states are immediate events.
                    probability=torch.where(evidence>=threshold,active,probability)
                    if self.mode=='expected':
                        spike=probability
                    else:
                        uniform=torch.rand(probability.shape,dtype=x.dtype,device=x.device,generator=generator)
                        hard=(uniform<probability).to(x.dtype)
                        spike=hard+(probability-probability.detach())
                    permitted=(energy>=c.proxy_spike_cost).to(x.dtype)
                    spike=spike*permitted
                    conditional=surviving_distance_mean(distance,safe_dt,-drive,c.sigma)
                    survived_evidence=threshold-conditional
                    survived_evidence=torch.where(active.bool(),survived_evidence,evidence)
                    reset_weight=spike if self.mode=='expected' else spike.detach()
                    evidence=(1-reset_weight)*survived_evidence
                    if multi:
                        decay=torch.exp(-effective_dt/c.memory_tau)
                        retained=decay*retained+(1-decay)*torch.tanh(evidence)*retain_gate
                if self.variant=='resource_lif' or self.variant.startswith('fp_') or self.variant=='rr_full':
                    energy=(energy-c.proxy_spike_cost*spike.detach()).clamp(min=0,max=1)
                fired=(spike.detach()>.5).to(x.dtype)
                refractory=torch.where(fired.bool(),torch.full_like(refractory,c.refractory),refractory)
                trace=trace*torch.exp(-effective_dt/c.trace_tau)+spike
                latent=trace+0.25*torch.tanh(evidence)
                if self.variant in ('fp_multi_fixed','rr_full'):
                    latent=latent+0.25*retained
                previous=spike
            latents.append(latent);events.append(spike);probs.append(probability)
            energies.append(energy);thresholds.append(threshold)
        return {'latent':torch.stack(latents,dim=1),'final_latent':latents[-1],
                'spikes':torch.stack(events,dim=1),
                'probabilities':torch.stack(probs,dim=1),
                'energy':torch.stack(energies,dim=1),
                'thresholds':torch.stack(thresholds,dim=1)}


def make_model(variant,input_size=22,hidden_size=16,**kwargs):
    return SurrogateSequenceModel(variant,input_size,hidden_size,**kwargs)

