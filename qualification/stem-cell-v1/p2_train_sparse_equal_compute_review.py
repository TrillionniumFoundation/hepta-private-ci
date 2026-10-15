"""Torch-free independent reviewer: replays P2 parent and newly TRAINED physical Top-1.

Scoring uses the original exact published AG News labels, opened only after
separate create-only unscored P2 + sparse-training records exist. This numeric
audit cannot independently observe the training graph/backward FLOPs or sign a
model's publisher weight origin. No production decision is returned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import p1_real_granite_review as source
import p2_real_cell_split_review as original_audit

SCHEMA='hepta.p2.physically-trained-one-active-equal-resident.v1'
SCORE='hepta.p2.trained-one-active-independent-review.v1'
ARMS=('frozen_single','single_active','fixed_top1','adaptive_top1')
LEARNED=ARMS[1:]
EXPERT_MAC=384*8+64*8+8*384+384*2
STEPS=40
TRAIN_ROWS=20*64+20*128
TOLERANCE=4e-5


def need(test,msg):
    if not test:raise ValueError(msg)


def sha(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode('utf8')).hexdigest()


def original_weights_sha(weights):
    result=hashlib.sha256()
    for name,value in sorted(weights.items()):
        result.update(name.encode()+b'\0')
        result.update(value.astype('<f4',copy=False).tobytes())
    return result.hexdigest()


def single_expert_sha(weights,index):
    result=hashlib.sha256()
    for name,value in sorted(weights.items()):
        result.update(name.encode()+b'\0')
        result.update(value[index].astype('<f4',copy=False).tobytes())
    return result.hexdigest()


def np_selected(x,weights,indices):
    """One selected expert per row, independently evaluated from FP32 bytes.

    The helper in original P2 reviewer computes *both* experts; our scorer
    instead replays one exact expert at a time without importing its producer.
    This does not attest the producer's actual Torch kernel accounting.
    """
    w=original_audit.decode_weights(weights)
    z=np.asarray(x,dtype=np.float32).astype(np.float64)
    need(z.ndim==2 and z.shape[1]==384,'384D Q24 heldout features required')
    need(type(indices) is list and len(indices)==len(z)
         and all(type(i) is int and i in (0,1) for i in indices),
         'complete Top-1 selected expert per heldout item required')
    logits=np.empty((len(z),2),dtype=np.float64)
    for i,which in enumerate(indices):
        down=z[i]@w['down'][which].astype(np.float64)
        gated=z[i,:64]@w['gate'][which].astype(np.float64)+w['g_bias'][which].astype(np.float64)
        silu=down/(1+np.exp(-np.clip(down,-50,50)))
        sigm=1/(1+np.exp(-np.clip(gated,-50,50)))
        delta=(silu*sigm)@w['up'][which].astype(np.float64)
        logits[i]=(z[i]+delta)@w['out'][which].astype(np.float64)+w['out_bias'][which].astype(np.float64)
    return logits,w


def review(panel,training,blind,owner,parent,report):
    labels=source.validate_original(panel,training,blind,owner)
    prior=original_audit.review(panel,training,blind,owner,parent)
    need(prior['eligible_model_selection'] is False,'original P2 declared unauthorized winner')
    need(type(report) is dict and report.get('schema')==SCHEMA
         and report.get('authority')=='DENY_ALL'
         and report.get('production_promotion_permitted') is False
         and report.get('report_sha256')==sha({k:v for k,v in report.items() if k!='report_sha256'}),
         'sealed nonauthorizing new physically trained report required')
    expected_top={'schema','authority','production_promotion_permitted',
         'original_p2_report_sha256','source_panel_sha256','model_revision',
         'original_model_weights_sha256','model_parameter_count',
         'pretrained_weight_execution_claimed','independent_model_origin_authenticated',
         'independently_sourced_future_tasks_verified','source_cohorts_are_chronological',
         'exact_backward_flops_matched','actual_equal_forward_expert_rows_on_train',
         'population_4096_training_executed','ndu_system2_superiority_established',
         'signed_final_use_verified','production_model_selected','one_model_load_in_this_execution',
         'original_pretrained_encoder_forward_calls','additional_model_load_vs_original_p2_job',
         'encoding_cpu_ns','encoding_wall_ns','train_count','heldout_calibration_count',
         'heldout_test_count','seed','original_frozen_two_head_initial_sha256',
         'train_cutoff_feature0_median','private_head_resident_count',
         'common_train_updates','common_train_example_exposures','source_heldout_cases',
         'source_features_q24','compared_arms','observed_process_peak_rss_bytes','report_sha256'}
    need(set(report)==expected_top,'new trained Head missing/added critical evidence field')
    need(report['original_p2_report_sha256']==parent['report_sha256']
         and report['source_panel_sha256']==parent['public_panel_sha256']==source.PANEL_SHA
         and report['model_revision']==parent['model_revision']==source.REVISION
         and report['original_model_weights_sha256']==parent['frozen_model_weights_sha256']
         and report['model_parameter_count']==parent['model_parameter_count']
         and type(report['pretrained_weight_execution_claimed']) is bool
         and report['pretrained_weight_execution_claimed']==parent['frozen_pretrained_source_execution_claimed']
         and type(report['seed']) is int and 0<report['seed']<2**31
         and report['original_frozen_two_head_initial_sha256']==parent['compared_arms']['frozen_no_change']['initial_weights_sha256']
         and report['train_cutoff_feature0_median']==parent['cutoff_feature0_train_median'],
         'different original model, source, frozen initial Head or router threshold')
    for flag in ('independent_model_origin_authenticated','independently_sourced_future_tasks_verified',
                 'source_cohorts_are_chronological','exact_backward_flops_matched',
                 'population_4096_training_executed','ndu_system2_superiority_established',
                 'signed_final_use_verified','production_model_selected'):
        need(report.get(flag) is False,'unsupported scientific or production authority')
    need(report.get('actual_equal_forward_expert_rows_on_train') is True
         and report.get('one_model_load_in_this_execution') is True
         and report.get('additional_model_load_vs_original_p2_job') is report.get('pretrained_weight_execution_claimed')
         and report.get('original_pretrained_encoder_forward_calls')==224
         and report.get('train_count')==128
         and report.get('heldout_calibration_count')==32
         and report.get('heldout_test_count')==64
         and report.get('private_head_resident_count')==14868
         and report.get('common_train_updates')==40
         and report.get('common_train_example_exposures')==3840
         and type(report.get('encoding_cpu_ns')) is int and report['encoding_cpu_ns']>0
         and type(report.get('encoding_wall_ns')) is int and report['encoding_wall_ns']>0
         and type(report.get('observed_process_peak_rss_bytes')) is int
         and report['observed_process_peak_rss_bytes']>0,
         'unaccounted original full feature/materialization and total resident work')
    expected=[dict(case_id=c['case_id'],group_id=c['group_id'],split=c['split'],
                   joint_input_digest=c['joint_input_digest']) for c in blind['rows']]
    need(report.get('source_heldout_cases')==expected
         and report.get('source_features_q24')==parent['source_features_q24']
         and type(report['source_features_q24']) is dict
         and set(report['source_features_q24'])=={x['case_id'] for x in expected},
         'not exact frozen source-bound heldout features from independent original P2 execution')
    x=np.array([[v/(1<<24) for v in report['source_features_q24'][r['case_id']]]
                 for r in expected],dtype=np.float32)
    need(x.shape==(96,384) and bool(np.isfinite(x).all()),'finite original Q24 inputs')
    compared=report.get('compared_arms')
    need(type(compared) is dict and set(compared)==set(ARMS),'all four trained Top-1 controls required')
    results={};raw={};initials=set()
    required_arm={'arm','parameter_count','active_head_parameters','initial_weights_sha256',
        'final_weights_sha256','expert_one_before_sha256','expert_one_after_sha256',
        'weights','split_proposed','train_only_split_excess_brier','split_threshold',
        'parent_clone_logits_max_abs','migration_copied_fp32_bytes',
        'split_parity_actual_head_forward_rows','split_parity_actual_head_batch_calls',
        'split_parity_forward_linear_mac','train_updates',
        'train_examples_exposed','train_physical_selected_expert_rows',
        'training_head_batch_calls','train_diagnostic_selected_expert_rows',
        'diagnostic_head_batch_calls','heldout_selected_expert_rows',
        'heldout_head_batch_calls','original_training_labels_only',
        'heldout_labels_opened_before_seal','train_forward_linear_mac',
        'diagnostic_forward_linear_mac','heldout_forward_linear_mac',
        'train_cpu_ns','train_wall_ns','heldout_cpu_ns','heldout_wall_ns','train_loss_history',
        'heldout_selected_expert_ids','heldout_logits'}
    for name in ARMS:
        arm=compared[name]
        need(type(arm) is dict and set(arm)==required_arm
             and arm.get('arm')==name and arm.get('parameter_count')==14868
             and arm.get('active_head_parameters')==7434
             and arm.get('initial_weights_sha256')==report['original_frozen_two_head_initial_sha256']
             and type(arm.get('split_proposed')) is bool
             and type(arm.get('train_only_split_excess_brier')) is float
             and math.isfinite(arm['train_only_split_excess_brier'])
             and arm.get('split_threshold')==0.03
             and arm.get('parent_clone_logits_max_abs')==0.0
             and arm.get('original_training_labels_only') is True
             and arm.get('heldout_labels_opened_before_seal') is False,
             'unmatched registered 7434p one-active Head, unsupported train/holdout use')
        initial=arm['initial_weights_sha256'];initials.add(initial)
        w=original_audit.decode_weights(arm['weights'])
        need(original_weights_sha(w)==arm['final_weights_sha256'],
             'complete original FP32 final tensor bytes do not hash to declared weights')
        need(type(arm.get('expert_one_before_sha256')) is str
             and len(arm['expert_one_before_sha256'])==64
             and single_expert_sha(w,1)==arm['expert_one_after_sha256'],
             'expert one weight content does not equal declared final bytes')
        split=arm['split_proposed']
        if name in ('frozen_single','single_active') or (name=='adaptive_top1' and not split):
            need(arm['expert_one_before_sha256']==arm['expert_one_after_sha256'],
                'unselected/dormant Head was silently optimized')
        if name=='frozen_single':
            need(arm['train_updates']==0 and arm['train_examples_exposed']==0
                 and arm['final_weights_sha256']==initial and split is False,
                'frozen no-change Head actually learned or split')
        else:
            need(arm['train_updates']==STEPS and arm['train_examples_exposed']==TRAIN_ROWS
                 and arm['final_weights_sha256']!=initial,
                'matched stage steps/source exposures are not real')
        if name=='fixed_top1':need(split is True,'fixed Top-1 route disabled')
        if name=='single_active':need(split is False,'single Head illegally specialized')
        if name=='adaptive_top1':
            need(split==(arm['train_only_split_excess_brier']>.03),
                 'adaptive route decision used forbidden postlabel criterion')
        expected_migration=7434*4 if name=='adaptive_top1' and split else 0
        need(type(arm['migration_copied_fp32_bytes']) is int
             and arm['migration_copied_fp32_bytes']==expected_migration
             and arm['split_parity_actual_head_forward_rows']==(8 if expected_migration else 0)
             and arm['split_parity_actual_head_batch_calls']==(2 if expected_migration else 0)
             and arm['split_parity_forward_linear_mac']==(8 if expected_migration else 0)*EXPERT_MAC,
             'unaccounted trained Cell clone or fake migration')
        def counts(key,expected_rows):
            z=arm.get(key)
            need(type(z) is list and len(z)==2
                 and all(type(v) is int and v>=0 for v in z)
                 and sum(z)==expected_rows,'actual Head-row phase count incomplete')
            return z
        train=counts('train_physical_selected_expert_rows',0 if name=='frozen_single' else TRAIN_ROWS)
        diagnostic=counts('train_diagnostic_selected_expert_rows',128)
        eval_count=counts('heldout_selected_expert_rows',96)
        for k,min_v,max_v in (('training_head_batch_calls',0,80),
                              ('diagnostic_head_batch_calls',2,4),
                              ('heldout_head_batch_calls',1,2)):
            v=arm[k]
            need(type(v) is int and min_v<=v<=max_v,'selected expert batch-call census invalid')
        if name=='frozen_single':need(arm['training_head_batch_calls']==0,'frozen Head claimed updates')
        else:need(40<=arm['training_head_batch_calls']<=80,'missing 40 sparse SGD batch calls')
        if name in ('single_active','frozen_single') or (name=='adaptive_top1' and not split):
            need(train[1]==0 and diagnostic[1]==0 and eval_count[1]==0,
                 'one-active or unsplit model computed a dormant expert')
        need(arm['train_forward_linear_mac']==EXPERT_MAC*sum(train)
             and arm['diagnostic_forward_linear_mac']==EXPERT_MAC*sum(diagnostic)
             and arm['heldout_forward_linear_mac']==EXPERT_MAC*sum(eval_count),
             'unaccounted equal forward compute or resource claim')
        ix=arm['heldout_selected_expert_ids']
        expected_ix=([int(z>=report['train_cutoff_feature0_median']) for z in x[:,0]]
                     if name=='fixed_top1' or (name=='adaptive_top1' and split)
                     else [0]*96)
        need(ix==expected_ix and eval_count==[96-sum(expected_ix),sum(expected_ix)]
             and arm['heldout_head_batch_calls']==len(set(expected_ix)),
             'selected actual Head must agree with frozen train-only feature Router')
        saved=arm.get('heldout_logits')
        need(type(saved) is list and len(saved)==96 and
             all(type(v) is list and len(v)==2 and all(type(y) is float and math.isfinite(y) for y in v)
                 for v in saved),'complete saved label-blind Top-1 logits required')
        reconstructed,_=np_selected(x,arm['weights'],expected_ix)
        discrepancy=float(np.max(np.abs(reconstructed-np.asarray(saved,dtype=np.float64))))
        need(discrepancy<=TOLERANCE,'independent NumPy cannot reproduce trained physical single-expert logits')
        ls=arm.get('train_loss_history')
        need(type(ls) is list and len(ls)==arm['train_updates']
             and all(type(q) is float and q>=0 and math.isfinite(q) for q in ls),
             'optimizer source-step loss history incomplete')
        for time_key in ('train_cpu_ns','train_wall_ns','heldout_cpu_ns','heldout_wall_ns'):
            need(type(arm.get(time_key)) is int and 0<arm[time_key]<10**15,
                 'untrusted or omitted physical training time')
        z=reconstructed-np.max(reconstructed,axis=1,keepdims=True)
        exp=np.exp(z);probs=exp[:,1]/exp.sum(axis=1)
        gold=np.array([v['label'] for v in labels],dtype=np.int64)
        correct=(probs>=.5)==(gold==1)
        per={}
        for s in ('calibration','test'):
            ids=np.array([i for i,v in enumerate(expected) if v['split']==s],dtype=int)
            per[s]=dict(n=len(ids),correct=int(np.sum(correct[ids])),
                accuracy=float(np.mean(correct[ids])),brier=float(np.mean((probs[ids]-gold[ids])**2)))
        raw[name]=correct
        results[name]=dict(**per,split=split,active_head_rows_train=sum(train),
            actual_train_forward_linear_mac=arm['train_forward_linear_mac'],
            diagnostic_rows=sum(diagnostic),test_rows=sum(eval_count),
            train_cpu_ns=arm['train_cpu_ns'],migration_copied_bytes=expected_migration,
            independent_numpy_replay_max_abs=discrepancy,
            signed_hardware_compute_attested=False)
    need(len(initials)==1,'multiple Head initializations falsely matched')
    paired={}
    for other in LEARNED[1:]:
        for s in ('calibration','test'):
            ids=[i for i,c in enumerate(expected) if c['split']==s]
            a=raw[other][ids];b=raw['single_active'][ids]
            recovered=int(np.sum(a&~b));lost=int(np.sum(b&~a))
            paired[f'{other}__vs__single_active__{s}']=dict(recovered=recovered,lost=lost,
                difference_accuracy=(recovered-lost)/len(ids))
    return dict(schema=SCORE,authority='DENY_ALL',
         reference_p2_report_sha256=parent['report_sha256'],
         trained_sparse_source_report_sha256=report['report_sha256'],
         original_public_panel_sha256=source.PANEL_SHA,
         source_group_effective_independent_n=0,
         old_new_split_is_temporal=False,only_real_public_cross_sectional_labels=True,
         primary_train_arms_equal_actual_forward_expert_rows=True,
         backward_flops_and_kernel_cost_matched=False,
         inherited_dense_and_wide_references_unequal_active_forward_mac=True,
         independent_model_and_worker_origin_authenticated=False,
         model_selection_authorized=False,ndu_utility_verified=False,
         production_promotion_permitted=False,
         original_p2_descriptive=prior['results'],new_arms=results,
         paired_against_single_active=paired)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('original-panel','train-material','blind-material','owner-labels',
                  'original-p2-report','trained-top1-report','output'):
        ap.add_argument('--'+field,required=True)
    args=ap.parse_args()
    orig=source.read_strict(args.original_panel)
    train=source.read_strict(args.train_material)
    blind=source.read_strict(args.blind_material)
    labels=source.read_strict(args.owner_labels)
    p2=source.read_strict(args.original_p2_report,limit=8*1024*1024)
    report=source.read_strict(args.trained_top1_report,limit=8*1024*1024)
    result=review(orig,train,blind,labels,p2,report)
    with Path(args.output).open('x',encoding='utf8') as fd:
        json.dump(result,fd,sort_keys=True,indent=2,allow_nan=False);fd.write('\n')

if __name__=='__main__':main()
