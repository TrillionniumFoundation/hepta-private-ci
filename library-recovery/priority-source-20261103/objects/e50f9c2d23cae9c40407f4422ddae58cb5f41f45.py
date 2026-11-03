"""P5: matched experiment and full-lifecycle resource ledger parser.

No HCSN or Transformer/SSM is run here. Numeric report is SCREENING ONLY,
never a production conclusion until actual weights, training traces, and
holdout are independently verified.
"""
from __future__ import annotations
import math
from collections import defaultdict

MODELS=('hcsn','transformer','ssm')
COSTS=('training','hparam_search','preparation','validation','inference',
       'cutover','cleanup')
FIELDS=('task','seed','model','train_sha256','holdout_sha256',
        'max_training_tokens','max_training_flops','actual_training_flops',
        'hparam_trial_budget','quality','p99_ms','costs_joules')


def check_backbone(rows,tasks,seeds):
    issues=[]
    taskset=set(tasks);seedset=set(seeds)
    expected={(t,s,m) for t in taskset for s in seedset for m in MODELS}
    actual=set();indexed={};total_cost_by_key={}
    if not taskset or not seedset or not rows:
        issues.append('empty experiment')
    for i,r in enumerate(rows):
        if not isinstance(r,dict):issues.append(f'row {i}: invalid record');continue
        missing=[k for k in FIELDS if k not in r]
        if missing:issues.append(f'row {i}: missing fields {missing}');continue
        key=(r['task'],r['seed'],r['model'])
        if key in actual:issues.append(f'duplicate cell {key}')
        actual.add(key);indexed[key]=r
        if r['model'] not in MODELS:issues.append(f'{key}: unexpected model')
        for dig in ('train_sha256','holdout_sha256'):
            if (not isinstance(r[dig],str) or len(r[dig])!=64 or
                    any(c not in '0123456789abcdef' for c in r[dig])):
                issues.append(f'{key}: invalid data SHA {dig}')
        for f in ('max_training_tokens','max_training_flops','actual_training_flops',
                  'hparam_trial_budget','p99_ms'):
            val=r[f]
            if (isinstance(val,bool) or not isinstance(val,(int,float))
                    or not math.isfinite(val) or val<=0):
                issues.append(f'{key}: invalid {f}')
        if not isinstance(r['quality'],(float,int)) or not math.isfinite(r['quality']) or not 0<=r['quality']<=1:
            issues.append(f'{key}: invalid quality')
        costs=r['costs_joules']
        if not isinstance(costs,dict):issues.append(f'{key}: missing lifecycle cost breakdown')
        else:
            for cost in COSTS:
                val=costs.get(cost)
                if isinstance(val,bool) or not isinstance(val,(float,int)) or not math.isfinite(val) or val<0:
                    issues.append(f'{key}: unmeasured/negative cost {cost}')
            if all(k in costs and isinstance(costs[k],(float,int)) for k in COSTS):
                total=sum(costs[k] for k in COSTS)
                if total<=0 or not math.isfinite(total):
                    issues.append(f'{key}: nonpositive measured total joules')
                else:
                    total_cost_by_key[key]=total
    for key in sorted(expected-actual):issues.append(f'missing cell {key}')
    for key in sorted(actual-expected):issues.append(f'unregistered cell {key}')
    for t in taskset:
        for seed in seedset:
            baseline=indexed.get((t,seed,'hcsn'))
            if not baseline:continue
            for model in ('transformer','ssm'):
                row=indexed.get((t,seed,model))
                if not row:continue
                for field in ('train_sha256','holdout_sha256','max_training_tokens',
                              'max_training_flops','hparam_trial_budget'):
                    if row[field]!=baseline[field]:
                        issues.append(f'{t} seed {seed}: {model} mismatched {field}')
            for model in MODELS:
                row=indexed.get((t,seed,model))
                if row and isinstance(row.get('actual_training_flops'),(int,float)):
                    if row['actual_training_flops']>row['max_training_flops']:
                        issues.append(f'{t} seed {seed}: {model} exceeded FLOP budget')
    effects={}
    if not issues:
        for t in sorted(taskset):
            for m in ('transformer','ssm'):
                pairs=[(indexed[(t,s,'hcsn')],indexed[(t,s,m)]) for s in sorted(seedset)]
                effects[f'{t}:{m}']={
                    'per_seed_quality_margin':[a['quality']-b['quality'] for a,b in pairs],
                    'per_seed_cost_ratio':[total_cost_by_key[(t,s,'hcsn')]/total_cost_by_key[(t,s,m)]
                                           if total_cost_by_key[(t,s,m)]>0 else None
                                           for s in sorted(seedset)],
                    'all_seeds_better_quality':all(a['quality']>b['quality'] for a,b in pairs),
                    'all_seeds_lower_p99':all(a['p99_ms']<b['p99_ms'] for a,b in pairs),
                    'all_seeds_lower_total_joules':all(
                        total_cost_by_key[(t,s,'hcsn')]<total_cost_by_key[(t,s,m)]
                        for s in sorted(seedset)),
                }
    return {'metadata_matched':not issues,'issues':issues,
            'exploratory_paired_effects':effects,
            'independent_train_and_holdout_verification':False,
            'tuned_baseline_attestation':False,
            'production_evidence_accepted':False}
