"""Reproducible numerical audit receipt; not a training/quality benchmark."""

from dataclasses import asdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import platform
import random

import numpy
import scipy

from .hx import HX, boundary, equity_closed, equity_resolvent, bond_value
from .stopping import Stop, regenerative_boundary, regenerative_boundary_independent, qvi
from .test_oracles import independent_boundary


def run():
    root=Path(__file__).resolve().parent
    sources={x.name:sha256(x.read_bytes()).hexdigest()
             for x in sorted(root.glob('*.py'))}
    rng=random.Random(20261030)
    cases=[]
    for i in range(48):
        cases.append(HX(rate=rng.uniform(.015,.14),payout=rng.uniform(0,.09),
                        volatility=rng.uniform(.12,.6),maturity=rng.uniform(.5,7),
                        principal=rng.uniform(20,100),coupon=rng.uniform(1,13),
                        tax_shield=rng.uniform(.0,.6),recovery=rng.uniform(.1,.95),
                        shock_intensity=rng.uniform(0,5),
                        sale_fraction=rng.choice((0.0,1e-9,rng.uniform(.001,.1)))))
    accepted=0;rejected=0;closed_err=0.;root_err=0.
    for p in cases:
        try: b=boundary(p)
        except ValueError:
            rejected+=1
            continue
        accepted+=1
        x=1.6*b
        closed_err=max(closed_err,abs(equity_closed(p,x,b)-equity_resolvent(p,x,b)))
    samples=[HX(),HX(payout=0),HX(sale_fraction=0),
             HX(shock_intensity=0),HX(rate=.11,payout=.05,volatility=.35,maturity=1.2)]
    for p in samples:
        root_err=max(root_err,abs(boundary(p)-independent_boundary(p)))
    stops=[Stop(.1,.4,.1,1,0,.3),Stop(-.3,1,.01,.4,-1,1),
           Stop(.5,.05,1,1,0,0),Stop(0,.6,.5,1,0,2)]
    stop_err=max(abs(regenerative_boundary(p)-regenerative_boundary_independent(p)) for p in stops)
    qvi_err=max(abs(qvi(p,x)['complementarity']) for p in stops
                for x in [p.reset,regenerative_boundary(p)-.1,regenerative_boundary(p)+.1])
    bad=HX(sale_fraction=.2)
    bad_b=boundary(bad)
    witness=equity_closed(bad,bad_b*1.01,bad_b)
    assert witness<0, 'a known smooth-fit-only obstruction was lost'
    return {
        'schema':'hcsn-hx-unified-p0-local-audit-v1',
        'status':'REFERENCE_TESTED_NOT_ADMITTED',
        'source_sha256':sources,
        'environment':{'python':platform.python_version(),'platform':platform.platform(),
                       'numpy':numpy.__version__,'scipy':scipy.__version__},
        'fixed_seed':20261030,
        'stressed_parameter_cases':len(cases),
        'positive_algebraic_boundaries':accepted,
        'nonpositive_or_undefined_boundaries':rejected,
        'maximum_abs_closed_vs_resolvent_at_1_6_B':closed_err,
        'maximum_abs_boundary_vs_independent_root':root_err,
        'maximum_abs_renewal_boundary_vs_brentq':stop_err,
        'maximum_abs_sampled_scalar_qvi_residual':qvi_err,
        'known_negative_equity_witness':{
            'sale_fraction':bad.sale_fraction,'asset_to_boundary':1.01,
            'equity':witness,
            'interpretation':'smooth fit not globally sufficient under this parameter regime'},
        'proof_scope':'finite seeded grid, selected reference comparisons and sampled residuals only',
        'open_gates':[
            'certify global obstacle/equity nonnegativity for full legal parameter domain',
            'independent PDE-grid convergence/interval error bounds across stiff regimes',
            'actual fp32/fp16 kernels, gradients and degeneracy limits',
            'matched Call/Risk/Margin mechanism attribution and training',
            'continuous-time event/refractory/memory workloads',
            'GPU throughput and real owner scale']
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=run()
    payload=json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload,encoding='utf-8')
    else:
        print(payload)


if __name__=='__main__':
    main()
