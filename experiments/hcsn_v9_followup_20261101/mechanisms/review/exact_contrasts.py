"""Exact reward arithmetic before world-block bootstrap; verify fixed risk raw replay."""
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import argparse

import numpy as np


def lines(path):
    with gzip.open(path,'rt') as stream:
        return [json.loads(v) for v in stream]


def reward(row):
    return Fraction(sum(v['correct'] for v in row['predictions']),4)-Fraction(row['summary']['reads'],25)


def avg(values):
    return sum(values,Fraction())/len(values)


def quantile(sorted_integer, numerator, denominator, value_denominator):
    index=Fraction((len(sorted_integer)-1)*numerator,denominator)
    low=index.numerator//index.denominator
    fraction=index-low
    high=min(low+1,len(sorted_integer)-1)
    return (Fraction(int(sorted_integer[low]))*(1-fraction)+int(sorted_integer[high])*fraction)/value_denominator


def main(dest,out):
    rows=lines(dest/'runs.jsonl.gz')
    freeze=json.loads((dest/'EVALUATION_FREEZE.json').read_text())
    results={}
    for condition in ('matched','hidden_refractory_mismatch'):
        deltas=[]
        for wi in range(12):
            group=[v for v in rows if v['condition']==condition and v['index']==wi and v['risk'] and not v['fixed'] and v['controller']=='task_value']
            d=avg([reward(v) for v in group if v['family']=='analytic' and v['mode']=='original'])
            b=avg([reward(v) for v in group if v['family'] in ('gru','ssm') and freeze['ordinary_selections'][v['fit_seed']]==v['family']])
            deltas.append(d-b)
        unit=math.lcm(*(v.denominator for v in deltas))
        integers=np.array([int(v*unit) for v in deltas],dtype=np.int64)
        indices=np.random.default_rng(916003).integers(12,size=(10000,12))
        draws=np.sort(integers[indices].sum(1))
        lo=quantile(draws,25,1000,unit*12)
        hi=quantile(draws,975,1000,unit*12)
        mean=avg(deltas)
        results[condition]={'mean_fraction':str(mean),'mean':float(mean),'per_world_fractions':list(map(str,deltas)),
            'percentile95_fraction':[str(lo),str(hi)],'percentile95':[float(lo),float(hi)],
            'strict_positive_lower_bound':lo>0,'method':'exact per-world paired reward and mean; integer bootstrap sums; exact interpolated quantiles',
            'reward_formula':'correct_count/4 - READ_count/25','worlds':12,'replicates':10000,'seed':916003}
    originals={(v['condition'],v['index'],v['fit_seed']):v for v in rows if v['family']=='analytic' and
               v['mode']=='original' and v['controller']=='task_value' and v['risk'] and not v['fixed']}
    fixed=lines(dest/'fixed_risk_replay.jsonl.gz')
    done=json.loads((dest/'FIXED_RISK_COMPLETE.json').read_text())
    digest=hashlib.sha256((dest/'fixed_risk_replay.jsonl.gz').read_bytes()).hexdigest()
    assert done['replayed_runs']==len(fixed)==len(originals)==72 and done['raw_sha256']==digest
    checks=2
    keys=set()
    for v in fixed:
        key=(v['condition'],v['index'],v['fit_seed'])
        assert key not in keys
        keys.add(key)
        old=originals[key]
        assert old['predictions']==v['predictions']
        assert old['access']==v['access']
        assert [(r['tick'],r['action']) for r in old['trace']]==[(r['tick'],r['action']) for r in v['trace']]
        assert reward(old)==reward(v)
        checks+=5
    result={'status':'passed','risk_aware_D_minus_B':results,'fixed_risk_raw_checks':checks,'fixed_risk_records':72,
            'limits':['historical ordinary fits and newly calibrated analytic families have unequal training budgets/priors',
                      'fixed risk replay confirms controller-only intervention semantics, not risk utility superiority']}
    with out.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status':'passed','fixed_risk_raw_checks':checks,'contrasts':results}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    a=parser.parse_args()
    main(a.run,a.out)
