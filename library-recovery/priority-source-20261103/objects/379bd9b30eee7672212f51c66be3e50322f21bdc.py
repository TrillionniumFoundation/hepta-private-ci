"""P1 factorial-contrast estimator with strict exploratory reporting.

No model is certified here; sign-flip p-values assume symmetric/exchangeable
seed-level effects. The familywise Holm adjustment is applied to all seven
pre-registered nonempty mechanism contrasts; no optional selection after data.
"""
from __future__ import annotations
import itertools
import math
from fair_ablation import ARMS,check_matched

FACTORS=('call','risk','margin')
CONTRASTS=tuple('+'.join(c) for k in (1,2,3) for c in itertools.combinations(FACTORS,k))


def _bits(arm):
    return set() if arm=='control' else set(arm.split('+'))


def exact_two_sided_signflip(values):
    if not values or len(values)>15 or any(not math.isfinite(x) for x in values):
        raise ValueError('requires 1..15 finite paired effects')
    n=len(values)
    observed=abs(sum(values))
    extreme=0
    # No Monte Carlo or asymptotic approximations for small seed cohorts.
    for signs in itertools.product((-1,1),repeat=n):
        total=abs(sum(v*s for v,s in zip(values,signs)))
        if total>=observed-1e-13:
            extreme+=1
    return extreme/(2**n)


def estimate_mechanisms(rows,seeds,*,exploratory_unmeasured_physical=False):
    check=check_matched(rows,seeds,
          exploratory_unmeasured_physical=exploratory_unmeasured_physical)
    if not check['metadata_comparable']:
        return {'valid_exploratory_design':False,'problems':check['issues'],
                'production_evidence_accepted':False,
                'physical_costs_unmeasured':exploratory_unmeasured_physical}
    grouped={(row['seed'],row['arm']):row['quality'] for row in rows}
    contrasts={}
    for name in CONTRASTS:
        target=set(name.split('+'))
        effects=[]
        for seed in sorted(set(seeds)):
            contrast=sum((1 if len(_bits(arm)&target)%2==len(target)%2 else -1)*
                         grouped[(seed,arm)] for arm in ARMS)/4
            # For target size >= 2 parity of the *intersection* alone cannot
            # express product signs unless comparing to target cardinality parity.
            effects.append(contrast)
        contrasts[name]={'seed_effects':effects,
                         'mean_effect':sum(effects)/len(effects),
                         'unadjusted_signflip_p':exact_two_sided_signflip(effects)}
    ordered=sorted(contrasts,key=lambda n:contrasts[n]['unadjusted_signflip_p'])
    prev=0
    for index,key in enumerate(ordered):
        p=contrasts[key]['unadjusted_signflip_p']
        adjusted=min(1.,max(prev,(len(ordered)-index)*p))
        contrasts[key]['holm_adjusted_p']=adjusted
        prev=adjusted
    return {'valid_exploratory_design':True,'contrasts':contrasts,
            'physical_cost_fields_present':not exploratory_unmeasured_physical,
            'n_seeds':len(set(seeds)),
            'signflip_assumption':'symmetric seed-level effects under null',
            'family':'seven preregistered main/pairwise/triple factorial contrasts',
            'production_evidence_accepted':False,
                'physical_costs_unmeasured':exploratory_unmeasured_physical}
