"""P1/P5 pre-registered, matched-budget attribution evidence checker.

Checking equality of metadata is NOT itself an assurance of a valid experiment;
raw training/evaluation traces, data permissions, provenance and independent
replication are still required. Synthetic fixtures must never be submitted as
performance evidence.
"""
from __future__ import annotations
import math
import re
from collections import defaultdict

ARMS=('control','call','risk','margin','call+risk','call+margin',
      'risk+margin','call+risk+margin')
HEXDIGEST=re.compile(r'^[0-9a-f]{64}$')
REQUIRED=('seed','arm','train_set_sha256','holdout_set_sha256',
          'information_sha256','encoder_sha256','parameter_count',
          'local_slope_norm','train_tokens','train_flops',
          'hyperparameter_search_trials','quality','inference_flops',
          'training_joules','peak_rss_bytes')


def check_matched(rows, seeds, arms=ARMS, parameter_tolerance=0.01,
                  slope_tolerance=0.02, flop_tolerance=0.01,
                  exploratory_unmeasured_physical=False):
    """Validate a complete factorial design, returning all violations.

    All score comparisons are exploratory pending independently checked raw
    logs and pre-registered confidence intervals. No claim of model advantage.
    """
    issues=[]
    seed_set=set(seeds)
    expected={(seed,arm) for seed in seed_set for arm in arms}
    actual=set()
    grouped=defaultdict(dict)
    for index,row in enumerate(rows):
        missing=[k for k in REQUIRED if k not in row]
        if missing:
            issues.append(f'row {index}: missing {missing}')
            continue
        key=(row['seed'],row['arm'])
        if key in actual:
            issues.append(f'duplicate cell {key}')
        actual.add(key)
        grouped[row['seed']][row['arm']]=row
        for name in ('train_set_sha256','holdout_set_sha256','information_sha256',
                     'encoder_sha256'):
            if not isinstance(row[name],str) or not HEXDIGEST.fullmatch(row[name]):
                issues.append(f'{key}: invalid {name}')
        if row['train_set_sha256']==row['holdout_set_sha256']:
            issues.append(f'{key}: same train and holdout hashes')
        for name in ('parameter_count','local_slope_norm','train_tokens','train_flops',
                     'hyperparameter_search_trials','inference_flops',
                     'training_joules','peak_rss_bytes'):
            val=row[name]
            unmeasured = (exploratory_unmeasured_physical and
                          name in ('training_joules', 'peak_rss_bytes') and (val is None or val == 0))
            if not unmeasured and (isinstance(val,bool) or not isinstance(val,(int,float)) or
                                   not math.isfinite(val) or val<=0):
                issues.append(f'{key}: invalid positive {name}')
        if (isinstance(row['quality'],bool) or not isinstance(row['quality'],(float,int)) or
                not math.isfinite(row['quality']) or not 0<=row['quality']<=1):
            issues.append(f'{key}: invalid score')
    for key in sorted(expected-actual):
        issues.append(f'missing factorial cell {key}')
    for key in sorted(actual-expected):
        issues.append(f'unregistered factorial cell {key}')
    for seed,arms_in_seed in grouped.items():
        base=arms_in_seed.get('control')
        if not base:
            continue
        for arm,row in arms_in_seed.items():
            key=(seed,arm)
            for name in ('train_set_sha256','holdout_set_sha256',
                         'information_sha256','encoder_sha256'):
                if row[name]!=base[name]:
                    issues.append(f'{key}: mismatched {name}')
            for name in ('train_tokens','hyperparameter_search_trials'):
                if row[name]!=base[name]:
                    issues.append(f'{key}: mismatched {name}')
            for name,allowance in (('parameter_count',parameter_tolerance),
                                   ('local_slope_norm',slope_tolerance),
                                   ('train_flops',flop_tolerance)):
                reference=base[name]
                if isinstance(reference,(int,float)) and reference>0 and isinstance(row[name],(int,float)):
                    if abs(row[name]-reference)/reference>allowance+1e-12:
                        issues.append(f'{key}: nonmatched {name}')
    # Even a syntactically complete table cannot be accepted as provenance.
    deltas={}
    if not issues:
        for arm in arms:
            if arm=='control':
                continue
            differences=[grouped[seed][arm]['quality']-grouped[seed]['control']['quality']
                         for seed in sorted(seed_set)]
            deltas[arm]={'paired_mean_quality_delta':sum(differences)/len(differences),
                         'per_seed_delta':differences}
    return {'metadata_comparable':not issues,'issues':issues,
            'exploratory_paired_deltas':deltas,
            'production_evidence_accepted':False,
            'physical_costs_unmeasured':exploratory_unmeasured_physical}
