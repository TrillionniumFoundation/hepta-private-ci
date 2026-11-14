"""P5 conservative, unforgeability-agnostic comparison gate.

The gate checks internal logical consistency of claimed raw metrics but cannot
cryptographically authenticate source, train run or hardware. An auditor must
replay from frozen sources; even a numerical PASS is labeled REVIEW_REQUIRED.
"""
from __future__ import annotations
import hashlib
import math
from collections import defaultdict
import numpy as np

MODELS=('hybrid_hcsn','tuned_transformer','tuned_ssm')
# Fail-closed at the research phase: no tiny pilot with just 2-3 seeds can
# declare superiority in a high-dimensional real task domain.
MIN_SEEDS=8
MIN_TASKS=3
NUMBERS=('train_tokens','train_flops','train_wall_seconds',
         'eval_flops','training_joules','inference_joules',
         'peak_rss_bytes','preparation_joules','validation_joules',
         'switch_joules','cleanup_joules','quality')
STRINGS=('source_sha','data_sha256','holdout_sha256','environment_sha256',
         'raw_train_log_sha256','raw_eval_log_sha256')


def _valid_hex(v,n):
    return isinstance(v,str) and len(v)==n and all(c in '0123456789abcdef' for c in v)


def compare(rows,*,task_ids,seed_ids,
            quality_delta_margin=0.01,compute_tolerance=0.01,
            negative_transfer_tolerance=0.005):
    issues=[]
    if len(set(seed_ids))<MIN_SEEDS:issues.append('insufficient independent seed replications')
    if len(set(task_ids))<MIN_TASKS:issues.append('insufficient diverse tasks')
    if not 0<=quality_delta_margin<1 or not 0<=negative_transfer_tolerance<1:
        raise ValueError('invalid margin')
    grouped={}
    expected={(task,seed,model) for task in task_ids for seed in seed_ids for model in MODELS}
    for i,r in enumerate(rows):
        if not isinstance(r,dict):
            issues.append(f'row {i}: invalid type');continue
        key=(r.get('task'),r.get('seed'),r.get('model'))
        if key in grouped:issues.append(f'duplicate {key}')
        grouped[key]=r
        for f in STRINGS:
            if not _valid_hex(r.get(f),40 if f=='source_sha' else 64):
                issues.append(f'{key}: invalid/missing {f}')
        for f in NUMBERS:
            v=r.get(f)
            if not isinstance(v,(int,float)) or not math.isfinite(v) or (v<=0 if f!='quality' else not (0<v<=1)):
                issues.append(f'{key}: invalid/unmeasured {f}')
        for f in ('preparation_joules','validation_joules','switch_joules','cleanup_joules'):
            if f in r and isinstance(r[f],(int,float)) and r[f]==0:
                issues.append(f'{key}: total costs contain unmeasured zero {f}')
    for key in expected-set(grouped):issues.append(f'missing {key}')
    for key in set(grouped)-expected:issues.append(f'unregistered {key}')
    paired_task_effects=defaultdict(dict)
    for task in task_ids:
        for seed in seed_ids:
            rs=[grouped.get((task,seed,model)) for model in MODELS]
            if any(r is None for r in rs):continue
            hybrid=rs[0]
            for base in rs[1:]:
                for f in ('data_sha256','holdout_sha256'):
                    if hybrid.get(f)!=base.get(f):issues.append(f'{task}/{seed}: unmatched {f}')
                for f in ('train_tokens','train_flops'):
                    a,b=hybrid.get(f),base.get(f)
                    if all(isinstance(v,(float,int)) and math.isfinite(v) and v>0 for v in (a,b)):
                        if abs(a-b)/b>compute_tolerance:
                            issues.append(f'{task}/{seed}: unmatched {f} vs {base.get("model")}')
                if all(isinstance(v,(float,int)) and math.isfinite(v) for v in
                       (hybrid.get('quality'),base.get('quality'))):
                    paired_task_effects[task].setdefault(base['model'],[]).append(
                        hybrid['quality']-base['quality'])
    # All task-level seed contrasts must be positive beyond predeclared margin
    # with a conservative nonparametric bootstrap lower interval. This is a
    # heuristic decision rule; not a proof of scientific superiority.
    contrasts=[]
    if not issues:
        rng=np.random.default_rng(20261031)
        for task in task_ids:
            for model in MODELS[1:]:
                effects=np.asarray(paired_task_effects[task][model])
                n=len(effects)
                boots=effects[rng.integers(0,n,(5000,n))].mean(axis=1)
                lb,ub=np.quantile(boots,[.025,.975])
                contrasts.append({'task':task,'baseline':model,
                                  'mean_delta':float(effects.mean()),
                                  'ci95_lower':float(lb),'ci95_upper':float(ub),
                                  'all_seed_noninferior':bool(np.min(effects)>=-negative_transfer_tolerance),
                                  'pre_registered_margin_met':bool(lb>quality_delta_margin)})
    # Self-reported metadata alone never opens product gate; audit provenance.
    potential=bool(contrasts) and all(c['pre_registered_margin_met'] and c['all_seed_noninferior'] for c in contrasts)
    return {'metadata_comparable':not issues,'issues':issues,
            'paired_contrasts':contrasts,
            'potential_research_advantage':potential,
            'decision':'REVIEW_REQUIRED' if potential else 'DENY',
            'production_qualified':False,'verified_source_and_hardware':False,
            'note':'Source integrity, full cost data and scientific replication must be independently authenticated.'}
