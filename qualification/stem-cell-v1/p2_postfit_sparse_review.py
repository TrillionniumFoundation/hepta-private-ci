"""Independent NumPy-only audit of P2 postfit Top-1 physical execution report.

Does not import Torch, the sparse producer or P2 trainer. Validates original
source and original trained weights with original P2 NumPy reviewer, then
independently checks exact routing, all predicted logits and fixed linear-MAC
accounting. Wall/CPU times remain *self-reported*; not a speedup certificate.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import math
from pathlib import Path

import numpy as np
import p1_real_granite_review as p1source
import p2_real_cell_split_review as base

SCHEMA='hepta.p2.postfit-physical-sparse-top1.v1'
ARMS=base.ARMS
EXPERT_MAC=384*8 + 64*8 + 8*384 + 384*2
WIDE_MAC=384*16 +64*16+16*384+384*2+384*2
ERROR_CAP=4e-5


def need(ok,msg):
    if not ok:
        raise ValueError(msg)


def stable_hash(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'),
                  ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def rank(items, fraction):
    ordered=sorted(items)
    return ordered[max(0,math.ceil(fraction*len(items))-1)]


def audit(original_panel,train,blind,owner,original,reported):
    # Original source/labels and weights are audited independently first;
    # this stage does not change the previous quality result or select a winner.
    prior=base.review(original_panel,train,blind,owner,original)
    need(prior.get('eligible_model_selection') is False, 'original research selected a model')
    if (not isinstance(reported,dict) or reported.get('schema')!=SCHEMA or
        reported.get('report_sha256')!=stable_hash({k:v for k,v in reported.items() if k!='report_sha256'})
        or reported.get('authority')!='DENY_ALL'
        or reported.get('production_promotion_permitted') is not False):
        raise ValueError('incomplete immutable DENY_ALL sparse execution report')
    fields={'schema','original_p2_report_sha256','original_frozen_model_sha256',
        'original_source_panel_sha256','original_model_revision','repetitions','warmups',
        'source_heldout_count','request_unit','time_measurements_self_reported',
        'original_training_compute_and_model_load_not_remeasured',
        'strict_equal_online_mac_across_arms',
        'independent_future_task_utility_established','native_worker_request_p99_qualified',
        'production_promotion_permitted','authority','arms','report_sha256'}
    need(set(reported)==fields,'unregistered extra sparse result or missing field')
    need(reported['original_p2_report_sha256']==original['report_sha256']
         and reported['original_frozen_model_sha256']==original['frozen_model_weights_sha256']
         and reported['original_source_panel_sha256']==original['public_panel_sha256']
         and reported['original_model_revision']==original['model_revision']
         and reported['source_heldout_count']==96
         and reported['request_unit']=='96-row-full-batch'
         and type(reported['repetitions']) is int and 20<=reported['repetitions']<=200
         and type(reported['warmups']) is int and 0<=reported['warmups']<=20
         and reported['time_measurements_self_reported'] is True
         and reported['original_training_compute_and_model_load_not_remeasured'] is True
         and reported['strict_equal_online_mac_across_arms'] is False
         and reported['independent_future_task_utility_established'] is False
         and reported['native_worker_request_p99_qualified'] is False,
         'original model/cost/quality scope drift or forbidden resource authority')
    results=reported.get('arms')
    need(type(results) is dict and set(results)==set(ARMS),'all five original P2 arms required')
    source=original['source_heldout_cases']
    expected_source=[dict(case_id=t['case_id'],group_id=t['group_id'],split=t['split'],
                    joint_input_digest=t['joint_input_digest']) for t in source]
    source_sha=stable_hash(expected_source)
    q24=original['source_features_q24']
    x=np.asarray([[z/(1<<24) for z in q24[t['case_id']]] for t in source],dtype=np.float32)
    cutoff=original['cutoff_feature0_train_median']
    results_by_arm={};quantities={}
    required_result={'arm','split_proposed','final_weights_sha256',
        'total_resident_parameter_count','source_heldout_count',
        'source_heldout_identity_sha256','physical_selected_head_indices',
        'registered_dense_head_rows','physical_active_head_rows',
        'physical_active_batch_calls','declared_linear_mac_dense',
        'declared_linear_mac_active','dense_vs_original_p2_logits_max_abs',
        'sparse_vs_dense_logits_max_abs','sparse_heldout_logits',
        'dense_batch_wall_ns','active_batch_wall_ns',
        'dense_batch_process_cpu_ns','active_batch_process_cpu_ns'}
    for name in ARMS:
        a=results[name];old=original['compared_arms'][name]
        need(type(a) is dict and set(a)==required_result
             and a.get('arm')==name and a.get('split_proposed') is old['split_proposed']
             and a.get('final_weights_sha256')==old['final_weights_sha256']
             and a.get('total_resident_parameter_count')==14868
             and a.get('source_heldout_count')==96
             and a.get('source_heldout_identity_sha256')==source_sha,
             'original trained parameter, source or arm identity mismatch')
        routed=name in ('fixed_two_cell','adaptive_train_only')
        wide=name=='wide_single_equal_parameter'
        expected_route=((x[:,0]>=cutoff).astype(int).tolist()
              if old['split_proposed'] else [0]*96) if routed else []
        expected_dense=96 if wide else 192
        expected_active=96 if routed or wide else 192
        expected_dense_mac=96*WIDE_MAC if wide else expected_dense*EXPERT_MAC
        expected_active_mac=96*WIDE_MAC if wide else expected_active*EXPERT_MAC
        batches=len(set(expected_route)) if routed else (1 if wide else 2)
        need(a['physical_selected_head_indices']==expected_route
             and type(a['registered_dense_head_rows']) is int and a['registered_dense_head_rows']==expected_dense
             and type(a['physical_active_head_rows']) is int and a['physical_active_head_rows']==expected_active
             and type(a['physical_active_batch_calls']) is int and a['physical_active_batch_calls']==batches
             and type(a['declared_linear_mac_dense']) is int and a['declared_linear_mac_dense']==expected_dense_mac
             and type(a['declared_linear_mac_active']) is int and a['declared_linear_mac_active']==expected_active_mac,
             'sparse Top-1 router or actual expert-row count differs from original decision')
        original_logits=np.asarray(old['logits'],dtype=np.float64)
        np_ref=base.np_logits(x,old['weights'],name,old['split_proposed'],cutoff)
        saved=a.get('sparse_heldout_logits')
        need(isinstance(saved,list) and len(saved)==96 and all(isinstance(v,list) and len(v)==2
             and all(type(z) is float and math.isfinite(z) for z in v) for v in saved),
             'complete original-source sparse logits required')
        physically=np.asarray(saved,dtype=np.float64)
        rerun_error=float(np.max(np.abs(np_ref-physically)))
        original_error=float(np.max(np.abs(np_ref-original_logits)))
        sparse_reference_error=float(np.max(np.abs(original_logits-physically)))
        need(rerun_error<=ERROR_CAP and original_error<=ERROR_CAP and sparse_reference_error<=ERROR_CAP
             and type(a['dense_vs_original_p2_logits_max_abs']) is float
             and type(a['sparse_vs_dense_logits_max_abs']) is float
             and abs(a['dense_vs_original_p2_logits_max_abs']-original_error)<=ERROR_CAP
             and abs(a['sparse_vs_dense_logits_max_abs']-sparse_reference_error)<=ERROR_CAP,
             'independent NumPy cannot reproduce original sparse logits')
        elapsed={}
        for label in ('dense_batch_wall_ns','active_batch_wall_ns',
                      'dense_batch_process_cpu_ns','active_batch_process_cpu_ns'):
            durations=a.get(label)
            need(type(durations) is list and len(durations)==reported['repetitions']
                 and all(type(v) is int and 0<v<10**12 for v in durations),
                 'missing actual full-batch timing observations')
            elapsed[label]=dict(p50_ns=rank(durations,.50),p95_ns=rank(durations,.95),
                                p99_ns=rank(durations,.99),samples=len(durations))
        results_by_arm[name]=dict(active_head_rows=expected_active,dense_head_rows=expected_dense,
            active_linear_mac=expected_active_mac,dense_linear_mac=expected_dense_mac,
            descriptive_linear_mac_saved=expected_dense_mac-expected_active_mac,
            preserved_original_logits_max_abs=rerun_error,
            full_batch_latency=elapsed)
    # Critically: some arms intentionally save ZERO expert work. Do not reject
    # negative/mixed latency or infer real savings from theoretical linear MACs.
    return dict(schema='hepta.p2.postfit-sparse-independent-review.v1',authority='DENY_ALL',
         original_p2_report_sha256=original['report_sha256'],
         source_panel_sha256=original['public_panel_sha256'],
         independently_replayed_original_p2=True,
         physically_claimed_sparse_rows_independently_checked_as_formulas=True,
         physical_runner_or_device_attested=False,
         self_reported_elapsed_not_signed=True,
         declared_linear_mac_not_full_flops=True,
         cost_adjusted_full_lifecycle_win_established=False,
         true_future_ood_utility_established=False,
         exact_equal_compute_across_arms=False,
         model_winner_selected=False,production_promotion_permitted=False,
         original_quality_descriptive=prior['results'],arms=results_by_arm)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('original-panel','train-material','blind-material','owner-labels',
                'p2-report','sparse-report','output'):
        ap.add_argument('--'+key,required=True)
    args=ap.parse_args()
    panel=p1source.read_strict(args.original_panel)
    train=p1source.read_strict(args.train_material)
    blind=p1source.read_strict(args.blind_material)
    owner=p1source.read_strict(args.owner_labels)
    original=p1source.read_strict(args.p2_report,limit=8*1024*1024)
    sparse=p1source.read_strict(args.sparse_report,limit=8*1024*1024)
    result=audit(panel,train,blind,owner,original,sparse)
    with Path(args.output).open('x',encoding='utf8') as f:
        json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')

if __name__=='__main__':main()
