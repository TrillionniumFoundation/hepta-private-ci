"""Deterministic P0 broad diagnostic sweep; not exhaustive, not a proof.

Raises on unexpected impossible ordering; counts resolution failures separately.
"""
import math
import random
from fpt_reference import FPT,formula,float_diagnostic


def run_stress(n=240,seed=20261030):
    rng=random.Random(seed)
    summary={'total':n,'reference_ordered':0,'high_precision_unresolved':0,
             'binary64_resolution_denied':0,'binary64_reference_check_only':0,
             'fatal_unexpected':0,'seed':seed,'cases':[]}
    for i in range(n):
        p=FPT(x=10**rng.uniform(-8,.5),
              drift=rng.uniform(-1.8,1.8),
              sigma=10**rng.uniform(-1.5,.4),
              horizon=10**rng.uniform(-6,1),
              discount=10**rng.uniform(-12,1))
        try:
            diagnostic=float_diagnostic(p,110)
            summary['reference_ordered']+=1
            if diagnostic['classification'].startswith('DENY'):
                summary['binary64_resolution_denied']+=1
                if len(summary['cases'])<5:
                    summary['cases'].append({'case_index':i,'param':p.__dict__,
                                             'gap_ulp':diagnostic['gap_ulp'],
                                             'reason':diagnostic['classification']})
            else:
                summary['binary64_reference_check_only']+=1
        except ArithmeticError as err:
            if 'unresolved' in str(err):
                summary['high_precision_unresolved']+=1
            else:
                summary['fatal_unexpected']+=1
                summary['cases'].append({'case_index':i,'param':p.__dict__,'error':str(err)})
    return summary

if __name__=='__main__':
    import json
    print(json.dumps(run_stress(),indent=2))
