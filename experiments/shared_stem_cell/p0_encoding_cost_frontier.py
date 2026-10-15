#!/usr/bin/env python3
"""P0: source-replayed, encoding-inclusive cost accounting for matched Human MultiRC.

Three pretrained Encoder banks are consumed as *untrusted physical observations*,
not authoritatively witnessed timing/energy. Head FLOPs are budget matched, whereas
evidence/no-evidence input token counts and Encoder work are not. This module
compares physically distinct input costs without selecting a model or issuing
capabilities, and refuses unavailable arms or partial original-label evidence.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from p0_multirc_semantic_material import Invalid, canonical, sha, read, save, original_rows
from p0_multirc_semantic_review import REQUIRED, numeric, probability
from p0_question_only_head import matched_pairs
from p0_question_only_review import review as paired_review, MODEL_HEADS

SCHEMA = 'hepta.p0.multirc-encoding-inclusive-cost-frontier.v1'


def _exact_positive_number(value, *, upper=None):
    number = numeric(value, positive=True)
    if upper is not None and number > upper:
        raise Invalid('unbounded physical measurement')
    return number


def _raw_prediction_times(arm, *, case_ids, kind):
    """Never add spent evaluation/control calls to one hypothetical deployed Head."""
    predictions = arm.get('predictions') if isinstance(arm, dict) else None
    if type(predictions) is not list:
        raise Invalid('missing original physical prediction receipt')
    observed = set()
    elapsed = 0.0
    for p in predictions:
        if type(p) is not dict:
            raise Invalid('missing original paid request')
        cid = p.get(kind)
        if type(cid) is not str or cid in observed:
            raise Invalid('duplicate paid request in trained arm')
        observed.add(cid)
        if cid in case_ids:
            key = 'head_request_ms'
            elapsed += _exact_positive_number(p.get(key))
    if observed != case_ids and kind == 'no_evidence_case_id':
        # The prior evaluates ONLY test questions. A missing original prediction
        # is not compensated by repeating a nearby case or using its baseline.
        raise Invalid('missing full matched prior inference census')
    return elapsed


def _split_cost_profile(fit, blind, reports, matched):
    """Compute standalone lower bounds; retain unknown physical overhead explicitly."""
    pairs = matched_pairs(fit, blind)
    rows = fit['cases'] + blind['cases']
    id_to_row = {r['case_id']:r for r in rows}
    if len(rows)!=len(id_to_row):
        raise Invalid('case census duplicate')
    all_ids = set(id_to_row)
    orig_ids = {r['case_id'] for r in rows if r['condition']=='original'}
    q_ids = all_ids - orig_ids
    if not orig_ids or len(orig_ids)!=len(q_ids):
        raise Invalid('unpaired original/no-evidence material')
    test_e = {o['case_id'] for o,_ in pairs['test']}
    test_q = {q['case_id'] for _,q in pairs['test']}
    out = {}
    for model in REQUIRED:
        report=reports[model]
        if model not in MODEL_HEADS:
            if report.get('matched_question_only_control') is not None:
                raise Invalid('Laya falsely represented as matched trained control')
            out[model]={'matched_encoder_head_frontier_applicable':False,
                        'reason':'separate frozen native no-change, not same trainable model class',
                        'no_additional_claim_of_equal_budget':True}
            continue
        profile = report.get('complete_source_profiles')
        if not isinstance(profile,dict):
            raise Invalid('no target-host Encoder measurements')
        tokens=profile.get('physical_token_counts_by_case')
        timings=profile.get('physical_encoder_ms_by_case')
        if type(tokens) is not dict or set(tokens)!=all_ids or type(timings) is not dict or set(timings)!=all_ids:
            raise Invalid('missing physical token/time per-case full inventory')
        if sha(canonical(tokens)) != profile.get('source_token_counts_sha256'):
            raise Invalid('altered physical token count source receipt')
        if profile.get('encoder_ms_by_case') != timings:
            raise Invalid('different contradictory Encoder duration inventories')
        if profile.get('physical_encoder_api_requests')!=len(rows):
            raise Invalid('wrong actual model API request count')
        original_tokens=[];prior_tokens=[];ms_orig=ms_prior=ms_all=0.0
        for cid,row in id_to_row.items():
            v=tokens[cid]
            if type(v) is not int or not 1<=v<=512:
                raise Invalid('missing/out-of-range physical tokenizer input')
            elapsed=_exact_positive_number(timings[cid])
            ms_all+=elapsed
            if row['condition']=='original':
                ms_orig+=elapsed;original_tokens.append(v)
            else:
                ms_prior+=elapsed;prior_tokens.append(v)
        training=report.get('training');candidate=report.get('matched_question_only_control')
        if type(training) is not dict or type(candidate) is not dict:
            raise Invalid('paired trainable research arms missing')
        old_controls=report.get('control');prior_controls=candidate.get('complete_prior_controls')
        if type(old_controls) is not dict or type(prior_controls) is not dict:
            raise Invalid('missing trained evidence/prior observation controls')
        if (set(old_controls)!={'frozen_head','trained_head'} or
                set(prior_controls)!={'question_frozen_head','question_trained_head'}):
            raise Invalid('missing both same-initialization controls')
        original_train=_exact_positive_number(training.get('head_training_ms'))
        prior_train=_exact_positive_number(candidate.get('question_only_head_training_ms'))
        load=_exact_positive_number(profile.get('model_load_ms'))
        wall=_exact_positive_number(report.get('local_process_wall_ms'))
        old_metered=sum(_exact_positive_number(p.get('head_request_ms'))
                         for arm in old_controls.values() for p in arm['predictions'])
        new_metered=sum(_exact_positive_number(p.get('head_request_ms'))
                         for arm in prior_controls.values() for p in arm['predictions'])
        # Actual paired campaign includes both frozen controls, all Encoder views,
        # and all physical Head calls. Count model load once; no fictitious
        # zero-cost/zero-FLOP extra forward or dummy padding.
        counted=load+ms_all+original_train+prior_train+old_metered+new_metered
        if counted>wall+5.0:
            raise Invalid('campaign cost exceeds actual process wall')
        # Recompute the trained policy's *original heldout* paid requests only.
        old_trained = old_controls['trained_head']['predictions']
        seen=set();original_serving_ms=0.0
        for p in old_trained:
            if type(p) is not dict or type(p.get('case_id')) is not str or p['case_id'] in seen:
                raise Invalid('duplicate original trained Head prediction')
            seen.add(p['case_id'])
            probability(p.get('positive_probability'))
            cost=_exact_positive_number(p.get('head_request_ms'))
            if p['case_id'] in test_e:
                original_serving_ms+=cost
        if seen!={r['case_id'] for r in blind['cases']}:
            raise Invalid('original Head omitted a scored evaluation request')
        question_serving_ms=_raw_prediction_times(prior_controls['question_trained_head'],
                                                    case_ids=test_q,kind='no_evidence_case_id')
        # Separate full-pretrained workflows *both* load a model; one packed
        # paired research process loads a model only ONCE. Standalone *lower*
        # bounds omit unmetered calibration, serialization, disk/WAL and host
        # scheduler work. Never subtract joint wall to invent service latency.
        evidence_standalone=load+ms_orig+original_train+original_serving_ms
        question_standalone=load+ms_prior+prior_train+question_serving_ms
        out[model]={
            'matched_encoder_head_frontier_applicable':True,
            'same_model_load_counted_once_in_joint_process':True,
            'separate_strategy_model_load_charged_once_each':True,
            'physical_input_counts':{'original':len(orig_ids),'question_only':len(q_ids)},
            'observed_token_counts':{
                'evidence_sum':sum(original_tokens),'question_only_sum':sum(prior_tokens),
                'evidence_min':min(original_tokens),'evidence_max':max(original_tokens),
                'question_only_min':min(prior_tokens),'question_only_max':max(prior_tokens)},
            'reported_encoding_ms':{'evidence':ms_orig,'question_only':ms_prior,
                                    'all_views_once':ms_all},
            'reported_head_training_ms':{'evidence':original_train,'question_only':prior_train},
            'reported_trained_head_serving_ms_for_original_human_test':{
                'evidence':original_serving_ms,'question_only':question_serving_ms},
            'standalone_cold_cost_lower_bound_ms':{
                'evidence':evidence_standalone,'question_only':question_standalone,
                'evidence_minus_question_only':evidence_standalone-question_standalone},
            'joint_paid_work_lower_bound_ms':counted,
            'joint_observed_process_wall_ms':wall,
            'joint_unattributed_wall_ms':max(0.0,wall-counted),
            'joint_cost_overshoot_tolerance_ms':max(0.0,counted-wall),
            'shared_read_only_weights_saving_measured':False,
            'target_host_gpu_energy_and_p99_verified':False,
            'full_lifecycle_cost_known':False,
            'physical_measurements_independently_attested':False}
    return out


def review(fit,blind,labels,original_train,original_validation,reports,*,matched_record=None):
    if type(reports) is not dict or set(reports)!=set(REQUIRED):
        raise Invalid('missing one or more original pretrained model controls')
    # Must rerun *the complete* prior original-source material/Head/label review.
    matched=paired_review(fit,blind,labels,original_train,original_validation,reports)
    if matched_record is not None and canonical(matched_record)!=canonical(matched):
        raise Invalid('old matched semantic score altered after label opening')
    profiles=_split_cost_profile(fit,blind,reports,matched)
    gains={model:{'group_equal_weight_brier_gain':matched['matched_models'][model]
             ['learned_evidence_versus_separately_trained_question_only']
             ['group_equal_weight_brier_gain_positive_means_evidence_better'],
             'source_groups':matched['matched_models'][model]
             ['learned_evidence_versus_separately_trained_question_only']['source_passages'],
             'independent_confirmatory_future_windows':0}
           for model in MODEL_HEADS}
    return {'schema':SCHEMA,'profile':profiles,'observational_human_label_results':gains,
            'prior_matched_score_sha256':sha(canonical(matched)),
            'reported_encoder_compute_parity':False,
            'equal_head_training_updates_do_not_imply_equal_total_compute':True,
            'result_quality_after_cost_superiority_proven':False,
            'prospective_future_windows_verified':False,
            'winner_selected':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser()
    for name in ('fit','blind','labels','train_parquet','validation_parquet','matched_score','output'):
        p.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    for model in REQUIRED:
        p.add_argument('--'+model.replace('_','-'),type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError('write-once encoding-inclusive research review')
    fit=read(args.fit);blind=read(args.blind);labels=read(args.labels)
    meta=fit['metadata']
    train=original_rows(args.train_parquet,meta['train_sha256'])
    validation=original_rows(args.validation_parquet,meta['validation_sha256'])
    outputs=review(fit,blind,labels,train,validation,
                   {m:read(getattr(args,m)) for m in REQUIRED},
                   matched_record=read(args.matched_score))
    save(args.output,outputs)
    print(json.dumps({'schema':SCHEMA,'new_model_winner':False,
                      'source_groups':8,'production_authority':'DENY_ALL'}))


if __name__=='__main__':
    main()
