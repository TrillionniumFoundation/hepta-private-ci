#!/usr/bin/env python3
"""Torch-free, independent 40-step SGD replay for source-group budgets.

No producer import, test labels or model promotion. All budgets/seed/Heads
are checked, including explicitly infeasible unlabeled-class budgets.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from safetensors.numpy import load_file
from e1_matched_gated_review import SHAPES, sha_state, retrain, forward

BUDGETS=(4,8,12)
SEEDS=(41,47,53)
KINDS=('additive','gated')
TOL=3e-5
SCHEMA='hepta.e3.source-group-learning-curve.v1'


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def expected_plan(fit_rows,blind_rows,panel):
    groups={r['source_group'] for r in fit_rows if r['split']=='train' and r['condition']=='original'}
    cal={r['source_group'] for r in fit_rows if r['split']=='calibration' and r['condition']=='original'}
    test={r['source_group'] for r in blind_rows if r['condition']=='original'}
    if len(groups)!=12 or len(cal)!=4 or len(test)!=8 or (groups&cal or groups&test or cal&test):
        raise ValueError('not original disjoint 12/4/8 MultiRC sources')
    # Independent of panel digest, which includes labeled TRAIN/FIT content.
    order=sorted(groups,key=lambda g:(hashlib.sha256(
        b'hepta.e3.original-source-group-nolabel.v2\0' + g.encode('utf8')
    ).hexdigest(),g))
    train=[(i,r) for i,r in enumerate(fit_rows) if r['split']=='train' and r['condition']=='original']
    calib=[(i,r) for i,r in enumerate(fit_rows) if r['split']=='calibration' and r['condition']=='original']
    held=list(range(len(fit_rows),len(fit_rows)+len(blind_rows)))
    if (len(train)<24 or len(calib)<8 or not held or
        any(type(r['label']) is not int or r['label'] not in (0,1) for _,r in train+calib) or
        {r['label'] for _,r in train}!={0,1} or {r['label'] for _,r in calib}!={0,1}):
        raise ValueError('invalid original train/CAL label support')
    subsets={}
    for n in BUDGETS:
        sub=[(i,r) for i,r in train if r['source_group'] in set(order[:n])]
        subsets[str(n)]={'train_indices':[i for i,_ in sub],
                         'train_groups':order[:n],
                         'status':'qualifiable' if {r['label'] for _,r in sub}=={0,1}
                                  else 'missing_both_labels'}
    return ({'source_group_order':order,'selection':'sha256(fixed-domain:source_group)-ascending-label-independent-v2',
             'calibration_indices':[i for i,_ in calib], 'blind_indices':held,
             'budgets':subsets},
            {str(n):np.asarray([r['label'] for i,r in train if i in subsets[str(n)]['train_indices']],
                                dtype=np.float32) for n in BUDGETS},
            np.asarray([r['label'] for i,r in calib],dtype=np.float32))


def review(features, parent, fit_rows, blind_rows, panel_id, report, saved):
    if (not isinstance(features,np.ndarray) or features.dtype!=np.float32 or
        features.ndim!=2 or len(features)!=len(fit_rows)+len(blind_rows) or
        not np.isfinite(features).all()):
        raise ValueError('invalid original FP32 feature bank')
    plan,labels,cal_labels=expected_plan(fit_rows,blind_rows,panel_id)
    if (type(report) is not dict or report.get('schema')!=SCHEMA or
        report.get('panel_id')!=panel_id or report.get('authority')!='DENY_ALL' or
        report.get('production_promotion_permitted') is not False or
        report.get('statistical_winner_selected') is not False or
        report.get('equal_full_lifecycle_cost_certified') is not False or
        report.get('original_human_held_labels_read') is not False or
        report.get('additional_encoder_loads')!=0 or report.get('additional_encoder_forwards')!=0 or
        report.get('projection_extra_physical_forwards')!=1 or
        report.get('projection_extra_mac')!=len(features)*features.shape[1]*128 or
        report.get('projection_extra_fp32_bytes')!=len(features)*128*4 or
        report.get('original_input_features_sha256')!=hashlib.sha256(features.tobytes(order='C')).hexdigest() or
        report.get('plan')!=plan):
        raise ValueError('original budget/source/cost/authority seal mismatch')
    projection=parent['shared_projection']
    if (projection.dtype!=np.float32 or projection.shape!=(features.shape[1],128) or
        not np.isfinite(projection).all() or
        report.get('original_shared_projection_sha256')!=hashlib.sha256(projection.tobytes(order='C')).hexdigest()):
        raise ValueError('shared E1 projection source mismatch')
    z=features@projection
    records=report.get('records')
    expected_order=[(n,s,k) for n in BUDGETS for s in SEEDS for k in KINDS]
    if (type(records) is not list or
        [(r.get('budget_source_groups'),r.get('seed'),r.get('architecture')) for r in records]!=expected_order):
        raise ValueError('missing, duplicated or shuffled original Head budget/seed grid')
    full_set=set(); max_weight=0.0; max_prob=0.0; statuses={}
    for r in records:
        n,seed,kind=r['budget_source_groups'],r['seed'],r['architecture']
        sub=plan['budgets'][str(n)]
        tr_idx=sub['train_indices']
        if r.get('training_rows')!=len(tr_idx):
            raise ValueError('TRAIN row budget was changed')
        key=f'b{n}.seed{seed}.{kind}'
        if sub['status']!='qualifiable':
            if (r.get('status')!='missing_both_labels' or r.get('optimizer_updates')!=0 or
                r.get('blind_predictions') is not None or set(r)!={'budget_source_groups','seed','architecture','status',
                                                                  'training_rows','optimizer_updates','blind_predictions'}):
                raise ValueError('infeasible group budget disguised as zero quality')
            statuses[str(n)]='infeasible_missing_both_labels'
            continue
        if (r.get('status')!='trained' or r.get('head_parameter_count')!=4145 or
            r.get('optimizer_updates')!=40 or r.get('train_row_exposures')!=40*len(tr_idx)):
            raise ValueError('false actual gradient/update/cost accounting')
        for key_name in ('train_wall_ms','train_cpu_ms'):
            t=r.get(key_name)
            if type(t) not in (float,int) or not math.isfinite(t) or t<0:
                raise ValueError('missing actual CPU timing observation')
        initial={k:parent[f'seed{seed}.frozen_{kind}.{k}'] for k in SHAPES}
        actual={k:saved[f'{key}.{k}'] for k in SHAPES if f'{key}.{k}' in saved}
        if (set(actual)!=set(SHAPES) or
            any(v.dtype!=np.float32 or v.shape!=SHAPES[k] or not np.isfinite(v).all()
                for k,v in actual.items())):
            raise ValueError('missing or invalid original physical Head weights')
        full_set.update(f'{key}.{k}' for k in SHAPES)
        if sha_state(initial)!=r.get('initial_sha256') or sha_state(actual)!=r.get('final_sha256'):
            raise ValueError('changed initial/final physical tensor lineage')
        replay=retrain(z[tr_idx],labels[str(n)],initial,kind)
        delta=max(float(np.abs(replay[k]-actual[k]).max()) for k in SHAPES)
        if delta>TOL:
            raise ValueError('independent budget TRAIN-label SGD replay disagrees')
        max_weight=max(max_weight,delta)
        if n==12:
            reference={k:parent[f'seed{seed}.trained_{kind}.{k}'] for k in SHAPES}
            if max(float(np.abs(reference[k]-actual[k]).max()) for k in SHAPES)>1e-6:
                raise ValueError('complete source budget not identical to original E1 trained baseline')
        cal_logit,_=forward(z[plan['calibration_indices']],actual,kind)
        temps=(0.5,0.75,1.,1.5,2.,3.)
        temperature=r.get('temperature')
        if type(temperature) not in (int,float) or temperature not in temps:
            raise ValueError('nonoriginal CAL temperature')
        losses=[float(np.mean(np.logaddexp(0,cal_logit/t)-cal_labels*cal_logit/t)) for t in temps]
        if losses[temps.index(temperature)]>min(losses)+TOL:
            raise ValueError('temperature was selected using non-CAL data')
        logits,_=forward(z[plan['blind_indices']],actual,kind)
        pred=np.exp(-np.logaddexp(0,-logits/temperature))
        observed=np.asarray(r.get('blind_predictions'))
        if (observed.shape!=pred.shape or not np.isfinite(observed).all() or
            np.any(observed<0) or np.any(observed>1)):
            raise ValueError('missing original held probabilities')
        p_delta=float(np.abs(pred-observed).max())
        if p_delta>TOL:
            raise ValueError('blind predicted probability not from recorded trained Head')
        max_prob=max(max_prob,p_delta)
        statuses[str(n)]='qualifiable'
    if set(saved)!=full_set:
        raise ValueError('extra/unknown trained weights outside original budget grid')
    for k in ('projection_wall_ms','projection_cpu_ms'):
        v=report.get(k)
        if type(v) not in (float,int) or not math.isfinite(v) or v<0:
            raise ValueError('missing actual paid additional projection cost')
    return {'schema':'hepta.e3.independent-source-group-train-replay.v1',
            'original_group_budgets':list(BUDGETS), 'validated_records':len(records),
            'budget_status':statuses, 'maximum_weight_disagreement':max_weight,
            'maximum_probability_disagreement':max_prob,'tolerance':TOL,
            'independent_cpu_performance_attested':False,
            'pretrained_stem_quality_scored':False,'future_task_utility_established':False,
            'source_group_budgets_nested':True,'original_full_budget_e1_parity':True,
            'production_promotion_permitted':False, 'authority':'DENY_ALL'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for f in ('fit','blind','original-report','replay-dir','e1-probe-dir','e1-numeric-review',
              'e3-probe-dir','output'):
        ap.add_argument('--'+f,type=Path,required=True)
    ap.add_argument('--model',required=True,choices=('granite_97m_r2','mmbert_small','embeddinggemma_2_text'))
    a=ap.parse_args()
    from p0_multirc_semantic_material import read,validate
    from p0_physical_replay_v5 import independent_numeric_replay
    fit,blind,p0=read(a.fit),read(a.blind),read(a.original_report)
    rows,held=validate(fit,blind)
    parent_e1=read(a.e1_probe_dir/'COMMITTED.json')
    numeric=read(a.e1_numeric_review)
    original=independent_numeric_replay(a.replay_dir,fit,blind,p0,model=a.model)
    if original!=parent_e1.get('original_numeric_replay'):
        raise ValueError('original E1 model P0 numeric lineage changed')
    # Independent reviewed E1 numerical result must bind to exact real E1 report.
    if (numeric.get('reviewed_probe_report_sha256')!=digest(parent_e1) or
        numeric.get('reviewed_original_p0_report_sha256')!=digest(p0) or
        numeric.get('reviewed_blind_material_sha256')!=digest(blind) or
        numeric.get('reviewed_model')!=a.model):
        raise ValueError('unverified original E1 producer from source review')
    report=read(a.e3_probe_dir/'COMMITTED.json')
    if (report.get('original_e1_probe_sha256')!=digest(parent_e1) or
        report.get('original_e1_numeric_sha256')!=digest(numeric) or
        report.get('original_fit_sha256')!=digest(fit) or
        report.get('original_blind_sha256')!=digest(blind) or
        report.get('p0_original_report_sha256')!=digest(p0) or
        report.get('model')!=a.model):
        raise ValueError('source/parent/source-group experiment identity mismatch')
    features=load_file(str(a.replay_dir/'features.safetensors'))['features_q24_fp32']
    parent=load_file(str(a.e1_probe_dir/'probe.safetensors'))
    weights_file=a.e3_probe_dir/'trained-heads.safetensors'
    if hashlib.sha256(weights_file.read_bytes()).hexdigest()!=report.get('e3_trained_weights_sha256'):
        raise ValueError('recorded E3 weight archive SHA does not match bytes')
    result=review(features,parent,rows,held,fit['metadata']['panel_id'],report,load_file(str(weights_file)))
    result.update({'reviewed_e3_report_sha256':digest(report),
                   'reviewed_e3_weights_sha256':report['e3_trained_weights_sha256'],
                   'reviewed_original_fit_sha256':digest(fit),
                   'reviewed_original_blind_sha256':digest(blind),
                   'reviewed_e1_report_sha256':digest(parent_e1),
                   'reviewed_model':a.model})
    with a.output.open('xb') as fd:fd.write(canonical(result)+b'\n')


if __name__=='__main__':main()
