"""Deterministic empirical panel for the structural (not efficacy) P1 NO_GO."""
from __future__ import annotations
import hashlib
import json
import random

import torch

try:
    from .dual_channel_structural_gate import (channels, first_hit_probability,
        independent_first_hit_density_integral)
except ImportError:
    from dual_channel_structural_gate import (channels, first_hit_probability,
        independent_first_hit_density_integral)


def panel():
    torch.set_num_threads(1)
    rng = random.Random(314159)
    rows=[]
    for i in range(180):
        r=rng.uniform(.012,.17)
        delta=rng.uniform(.01,.14)
        sigma=rng.uniform(.075,.55)
        horizon=rng.uniform(.1,6)
        b=rng.uniform(.4,1.3)
        v=b*__import__('math').exp(rng.uniform(.01,.65))
        p=first_hit_probability(v,b,horizon,r=r,delta=delta,sigma=sigma)
        integration,quad_est=independent_first_hit_density_integral(v,b,horizon,r=r,delta=delta,sigma=sigma)
        rows.append(dict(id=i,r=r,delta=delta,sigma=sigma,horizon=horizon,
                         barrier=b,state=v,reflection=p,density_quadrature=integration,
                         quad_error_estimate=quad_est,absolute_difference=abs(p-integration)))
    records={'schema':'hcsn-p1-structural-panel-v1','seed':314159,
             'research_only':True,'production_activation':False,
             'all_scientific_blockers_closed':False,
             'rows':rows,'max_abs_difference':max(x['absolute_difference'] for x in rows)}
    return records


def main():
    p=panel()
    encoded=json.dumps(p,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    sha=hashlib.sha256(encoded).hexdigest()
    print(json.dumps({'rows':len(p['rows']),'max_abs_difference':p['max_abs_difference'],
                      'canonical_sha256':sha},indent=2))
    with open(__import__('os').path.join(__import__('os').path.dirname(__file__),'structural_panel.json'),'wb') as f:
        f.write(encoded+b'\n')


if __name__=='__main__':main()
