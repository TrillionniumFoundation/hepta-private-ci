"""Reproduce a *numerical smoke panel* for the conservative P0 bound.

The proof in hx_equity_upper_envelope.py is independent from HX's closed form.
These numerical samples are checks, not proof of the global financial VI.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
from .hx import HX, boundary, equity_closed
from .hx_equity_upper_envelope import fixed_barrier_equity_upper_envelope


def run_panel():
    cases={'nominal':HX(), 'high_liquidity':HX(sale_fraction=.2),
           'zero_shock':HX(shock_intensity=0.),
           'low_payout_high_vol':HX(volatility=.5,payout=.005),
           'lower_coupon':HX(coupon=2.,tax_shield=.4)}
    rows=[]
    for label,p in cases.items():
        b=boundary(p)
        q=p.rate+p.shock_intensity*p.sale_fraction
        C=(1-p.tax_shield)*p.coupon+p.principal/p.maturity
        base=p.coupon/(p.maturity*q)
        B_no_default=base+math.exp(-q*p.maturity)*(p.principal/p.maturity-base)
        A=b*math.exp(3.6)
        guess=A+(B_no_default-C)/p.rate
        c=fixed_barrier_equity_upper_envelope(p,candidate_barrier=b,
            log_upper=3.6,nominal_upper_equity=guess)
        ref=equity_closed(p,A,b)
        rows.append(dict(case=label,barrier=b,nominal_equity=guess,
            sampled_fixed_barrier_equity=ref,
            observed_abs_diff=abs(ref-guess),
            rigorous_fixed_barrier_optimal_equity_envelope={
                'lower':c.equity_lower,'upper':c.equity_upper},
            upper_equity_abs_budget=c.upper_equity_abs_budget,
            model_assumptions=c.boundary_model,
            scientific_gate_closed=False,
            production_activation=False))
    return dict(schema='HCSN-equity-boundary-envelope-smoke-v1',
                numeric_reference='local HX reconstructed subset; NOT complete upstream CI',
                notes='Sampled fixed-boundary resolvent need not equal global optimal-stopping equity',
                experiment='fixed financial barrier, positive payout; 3.6 log upper; exact-rational Taylor interval',
                base_pr=4512,base_sha='99fa3ad1f75eb021fc95fd2b6cd5dbda37898e2c',
                rows=rows,scientific_gate_closed=False,production_activation=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    payload=json.dumps(run_panel(),sort_keys=True,indent=2,allow_nan=False)+'\n'
    path=Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(payload)
    print(json.dumps({'path':str(path),'sha256':hashlib.sha256(payload.encode()).hexdigest(),
                      'records':len(json.loads(payload)['rows'])},sort_keys=True))

if __name__=='__main__':main()
