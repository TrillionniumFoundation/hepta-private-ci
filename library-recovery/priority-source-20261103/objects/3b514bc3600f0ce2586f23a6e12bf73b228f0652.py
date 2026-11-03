"""P0 stress and boundary sensitivities for published HX vs independent FD.

Finite random domains and *finite-difference gradients* are diagnostic only;
not all-parameter certification, interval errors, or analytic AD proof.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import replace
import random
import math
from full_hx_numeric import HXCoupled,solve_free_boundary
from hx_published_boundary import published_boundary


def boundary_gradient_crosscheck(p=HXCoupled(),fields=('volatility','payout','shock_intensity','maturity'),h=0.001,N=1600):
    p.validate()
    rows=[]
    for field in fields:
        value=getattr(p,field)
        if not value>h:raise ValueError(f'{field}: requires symmetric legal perturbation')
        plus=replace(p,**{field:value+h})
        minus=replace(p,**{field:value-h})
        fine_analytic=(float(published_boundary(plus)['boundary'])-
                       float(published_boundary(minus)['boundary']))/(2*h)
        fine_fd=(solve_free_boundary(plus,N=N)['boundary']-
                 solve_free_boundary(minus,N=N)['boundary'])/(2*h)
        # Additionally check analytic central-gradient stability with h/2.
        half_plus=replace(p,**{field:value+h/2})
        half_minus=replace(p,**{field:value-h/2})
        half_analytic=(float(published_boundary(half_plus)['boundary'])-
                       float(published_boundary(half_minus)['boundary']))/h
        rows.append({'field':field,'analytic_central_gradient':fine_analytic,
                     'independent_FD_central_gradient':fine_fd,
                     'disagreement':abs(fine_analytic-fine_fd),
                     'analytic_step_halving_change':abs(fine_analytic-half_analytic),
                     'perturbation':h,'mesh_N':N,
                     'not_certified_derivative':True})
    return rows


def domain_sweep(n=64,seed=20261031,N=600):
    if not isinstance(n,int) or not 0<n<=300:raise ValueError('invalid stress n')
    rng=random.Random(seed)
    summary={'attempted':n,'seed':seed,'admissible_numeric_compared':0,
             'regime_refused':0,'numeric_refused':0,
             'max_abs_boundary_error':0.,'max_relative_error':0.,
             'worst_cases':[],'rejection_reasons':{}}
    reasons=Counter()
    for i in range(n):
        p=HXCoupled(rate=rng.uniform(.02,.15),
                    payout=rng.uniform(.005,.09),
                    volatility=rng.uniform(.08,.9),
                    maturity=rng.uniform(.3,5),
                    shock_intensity=rng.uniform(0.,.5),
                    sale_fraction=rng.uniform(0.,.4),
                    recovery_fraction=rng.uniform(.35,.8),
                    tax_shield=rng.uniform(.1,.35),
                    total_coupon=rng.uniform(.02,.14),
                    total_principal=rng.uniform(.8,1.5))
        try:
            exact=float(published_boundary(p)['boundary'])
        except (ValueError,ArithmeticError,OverflowError) as exc:
            summary['regime_refused']+=1
            reasons['analytic:'+type(exc).__name__+':'+str(exc)]+=1
            continue
        try:
            numeric=solve_free_boundary(p,N=N)['boundary']
        except (ValueError,ArithmeticError,OverflowError,ZeroDivisionError) as exc:
            summary['numeric_refused']+=1
            reasons['numeric:'+type(exc).__name__+':'+str(exc)]+=1
            continue
        absolute=abs(numeric-exact)
        relative=absolute/max(abs(exact),1e-15)
        if not(math.isfinite(absolute) and math.isfinite(relative)):
            raise ArithmeticError('unexpected nonfinite boundary comparison')
        summary['admissible_numeric_compared']+=1
        if relative>summary['max_relative_error']:
            summary['worst_cases']=[{'index':i,'params':vars(p),'analytic':exact,
                                     'FD_N':numeric,'absolute':absolute,'relative':relative}]
        summary['max_relative_error']=max(summary['max_relative_error'],relative)
        summary['max_abs_boundary_error']=max(summary['max_abs_boundary_error'],absolute)
    summary['rejection_reasons']=dict(sorted(reasons.items()))
    summary['scope']='sampled finite-grid screening, not exhaustive legal domain or proof'
    return summary
