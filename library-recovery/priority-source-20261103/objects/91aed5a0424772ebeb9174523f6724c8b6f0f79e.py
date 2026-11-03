"""P0 time-slab gap bracketing for a constant-drift *fixed-barrier* FPT.

For t in [t_i,t_{i+1}], 1-e^{-q*t_i} <= 1-e^{-q*t} <=
1-e^{-q*t_{i+1}}. Multiply by nonnegative first-passage mass dF(t)
and sum. This is an analytic real-valued inequality, but the endpoints
computed with mpmath are *approximations*, NOT verified outward intervals.

Do NOT use these numerical bounds as production certificates for He-Xiong.
"""
from __future__ import annotations
from dataclasses import dataclass
from mpmath import mp
from fpt_reference import FPT, _Phi, _num, formula


def _cdf(t,x,drift,sigma):
    if t == 0:
        return mp.zero
    u=sigma*mp.sqrt(t)
    a=(-x-drift*t)/u
    b=(-x+drift*t)/u
    return _Phi(a)+mp.exp(-2*drift*x/sigma**2)*_Phi(b)


def bracket(p:FPT,slabs=64,dps=90):
    p.validate()
    if not isinstance(slabs,int) or not 2<=slabs<=4096:
        raise ValueError('slabs must be integer 2..4096')
    if not 50<=dps<=230:
        raise ValueError('dps must be 50..230')
    if p.horizon==0 or p.x==0 or p.discount==0:
        return {'lower':'0.0','upper':'0.0','width':'0.0','slabs':slabs,
                'exact_degenerate':True,'verified_outward_rounding':False}
    with mp.workdps(dps):
        x,mu,sig,T,q=map(_num,(p.x,p.drift,p.sigma,p.horizon,p.discount))
        last_t=mp.zero
        last_f=mp.zero
        low=mp.zero;high=mp.zero
        for i in range(1,slabs+1):
            t=T*i/slabs
            mass=_cdf(t,x,mu,sig)-last_f
            # Exact F is monotone. Numerical negativity even at high precision
            # means the reference is unresolved; never clip it to 0.
            if mass<0:
                raise ArithmeticError('reference CDF not monotone: increase precision')
            wlo=-mp.expm1(-q*last_t)
            whi=-mp.expm1(-q*t)
            low+=mass*wlo
            high+=mass*whi
            last_t=t
            last_f+=mass
        if not 0<=low<=high<=1:
            raise ArithmeticError('invalid numerical ordering')
        return {'lower':mp.nstr(low,dps-12),
                'upper':mp.nstr(high,dps-12),
                'width':mp.nstr(high-low,dps-12),
                'cdf_horizon':mp.nstr(last_f,dps-12),
                'slabs':slabs,'dps':dps,'exact_degenerate':False,
                'inequality':'real-valued monotone time-slab discount inequality',
                'verified_outward_rounding':False,
                'scope':'fixed absorbing boundary, constant drift and sigma only'}


def refinement(p:FPT,counts=(32,64,128),dps=80):
    a=[bracket(p,n,dps=dps) for n in counts]
    # We do not claim certified brackets; this is a cross-check against
    # high-precision F-G subtraction to detect an implementation error.
    reference=formula(p,dps=dps)
    with mp.workdps(dps):
        v=mp.mpf(reference['F_minus_G'])
        for interval in a:
            if not mp.mpf(interval['lower']) <= v <= mp.mpf(interval['upper']):
                # Finite-precision printed endpoints may cause extreme edge
                # false negatives; fail closed rather than widen silently.
                raise ArithmeticError('reference gap falls outside approximate slab endpoints')
        if not all(mp.mpf(a[i+1]['width']) < mp.mpf(a[i]['width']) for i in range(len(a)-1)):
            raise ArithmeticError('time-slab bounds did not narrow')
    return {'reference_gap':reference['F_minus_G'],'slabs':a,
            'certified_real_interval':False}
