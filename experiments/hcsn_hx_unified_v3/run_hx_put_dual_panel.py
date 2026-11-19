"""Deterministic independent 122-case fixed-barrier put dual panel (NO_GO)."""
import argparse
import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from .hx_put_lower_witness import certify_fixed_barrier_put_dual
from .test_hx_put_lower_witness import HX


def make_panel():
    rows=[]
    def record(p,b,L,kind):
        c=certify_fixed_barrier_put_dual(p,candidate_barrier=b,log_upper=L)
        rows.append(dict(kind=kind,rate=p.rate,payout=p.payout,
            volatility=p.volatility,sale_fraction=p.sale_fraction,
            barrier=b,log_upper=L,put_lower=c.put_lower,put_upper=c.put_upper,
            witness=c.witness_level,gap=str(Decimal(c.put_upper)-Decimal(c.put_lower)),
            production_activation=False))
    for sf,b in ((.015,64.62517667527493),(.2,101.32402860907811)):
        record(HX(sale_fraction=sf),b,3.6,'published_fixed_barrier')
    for r in (.03,.05,.09):
        for delta in (.015,.06):
            for sigma in (.15,.35):
                for b in (30.,55.,80.,105.,130.):
                    for L in (.7,3.6):
                        record(HX(rate=r,payout=delta,volatility=sigma,
                                  sale_fraction=.2),b,L,'parameter_stress')
    return dict(schema='hcsn-fixed-barrier-constant-bond-put-dual-v1',
        parent_pr=4518,parent_sha='ee06b987eb408821cd8b7aba4c7969aa18e5e77f',
        main_observed_sha='732e934ba496d90fbe042b8d41d479ef901643e5',
        status='RESEARCH_ONLY_DENY_ALL_NO_GO',
        source_is_independent_rational_reference=True,
        full_HX_coupled_obstacle_proved=False,
        production_activation=False,
        total_cases=len(rows),zero_premium=sum(x['put_upper']=='0.000000000000' for x in rows),
        rows=rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path)
    a=ap.parse_args()
    raw=(json.dumps(make_panel(),sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    if a.output:
        with a.output.open('xb') as f:
            f.write(raw)
    print('raw_sha256',hashlib.sha256(raw).hexdigest())
    print('bytes',len(raw))
    print('cases',122)

if __name__=='__main__':
    main()
