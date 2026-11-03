"""P0 emulated scalar precision-loss audits and sigma->0 checks.

Importantly, converting high-precision F/G outputs into low precision is NOT
an executed FP32/BF16 implementation of the original He-Xiong formula. It
proves the representational gap may disappear and must fail closed.
"""
from __future__ import annotations
import math
from mpmath import mp
import torch
from fpt_reference import FPT, formula
from fpt_positive_gap import truncated_hit_first_moment


def casts(p:FPT,dps=95):
    ref=formula(p,dps=dps)
    true_gap=mp.mpf(ref['F_minus_G'])
    output={}
    for name,dtype in [('binary64',torch.float64),('float32',torch.float32),('bfloat16',torch.bfloat16)]:
        f=torch.tensor(float(ref['F']),dtype=dtype).item()
        g=torch.tensor(float(ref['G']),dtype=dtype).item()
        gap=f-g
        status=('DENY_REVERSED_ORDER' if g>f else
                'DENY_LOST_POSITIVE_GAP' if true_gap>0 and not gap>0 else
                'REPRESENTABLE_NOT_CERTIFIED')
        output[name]={'F':f,'G':g,'difference':gap,'classification':status}
    return {'input':vars(p),'reference_gap':ref['F_minus_G'],
            'casts':output,
            'actual_native_dtype_kernel_executed':False,
            'production_evidence_accepted':False}


def deterministic_limit(p:FPT):
    """Exact sigma=0 hitting limit away from the discontinuous tau=T case."""
    p.validate()
    if p.x==0:return {'F':1.,'G':1.,'tau':0.,'limit':'barrier_at_start'}
    if p.horizon==0:return {'F':0.,'G':0.,'tau':None,'limit':'zero_horizon'}
    tau=p.x/(-p.drift) if p.drift<0 else math.inf
    if math.isfinite(tau) and abs(tau-p.horizon)<1e-10*max(1,p.horizon):
        raise ValueError('sigma->0 hitting at T discontinuity; do not certify')
    hit=math.isfinite(tau) and tau<p.horizon
    return {'F':1. if hit else 0.,'G':math.exp(-p.discount*tau) if hit else 0.,
            'tau':tau if math.isfinite(tau) else None,'limit':'deterministic_fixed_barrier'}


def zero_discount_sensitivity(p:FPT,q_small=1e-6,dps=95):
    p.validate()
    if p.x==0 or p.horizon==0:
        return {'limit_first_moment':'0','finite_q_ratio':'0'}
    test=FPT(p.x,p.drift,p.sigma,p.horizon,q_small)
    r=formula(test,dps=dps)
    moment=truncated_hit_first_moment(p,dps=dps)
    with mp.workdps(dps):
        quotient=mp.mpf(r['F_minus_G'])/mp.mpf(str(q_small))
        ratio=quotient/mp.mpf(moment)
        return {'q':q_small,'first_moment':moment,
                'finite_q_gap_over_q':mp.nstr(quotient,30),
                'ratio_to_zero_q_limit':mp.nstr(ratio,30),
                'derivative_certified':False}


def run():
    tricky=FPT(math.log(1.000000000000002),
               .007595780582070804-3.5072936797757205e-7-1.8581469732429565**2/2,
               1.8581469732429565,2.2216211523554883e-8,.007595780582070804)
    cases=[FPT(.8,-.3,.7,.9,.05),tricky,
           FPT(.7,-.5,1e-4,2,.2),
           FPT(.7,-.5,1e-4,1,.2),
           FPT(.7,+.5,1e-4,2,.2)]
    result={'cast_analyses':[casts(p) for p in cases[:2]],
            'deterministic_regimes':[],'sensitivity':zero_discount_sensitivity(cases[0])}
    for p in cases[2:]:
        r=formula(p,120)
        limit=deterministic_limit(p)
        result['deterministic_regimes'].append({'reference':r,'expected_limit':limit})
    return result

if __name__=='__main__':
    import json
    from pathlib import Path
    result=run()
    out=Path('reports/p0_precision_limits.json')
    out.write_text(json.dumps(result,indent=2))
    print('saved',out)
    for r in result['cast_analyses']:
        print('gap:',r['reference_gap'],
              {k:v['classification'] for k,v in r['casts'].items()})
