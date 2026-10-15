#!/usr/bin/env python3
"""Independent source-replayed matched evidence versus trained question-only review.

Only the original MultiRC passage/question/answer owns a human truth label.
Prior-only features estimate that original target, NOT an artificial no-evidence
entailment. Real physical-model receipt claims need independent host witnesses.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random

from p0_multirc_semantic_material import (Invalid, canonical, sha, read, save,
                                          original_rows, normalized, COUNTS)
from p0_multirc_semantic_review import (REQUIRED, REVISIONS, review as review_original,
                                        original_label_audit, probability, numeric, metrics)
from p0_question_only_head import SCHEMA, matched_pairs

MODEL_HEADS = ('granite_97m_r2', 'mmbert_small', 'embeddinggemma_2_text')
OUT_SCHEMA = 'hepta.p0.multirc-matched-question-only-independent-review.v1'


def _sha(v):
    if type(v) is not str or len(v) != 64 or any(c not in '0123456789abcdef' for c in v):
        raise Invalid('invalid content or parameter SHA')
    return v


def _paired_metrics(evidence, prior, labels, original_rows_by_case):
    if set(evidence) != set(prior) or set(evidence) != set(labels):
        raise Invalid('paired scored cases incomplete')
    by_group = defaultdict(list)
    for cid in labels:
        y = labels[cid]
        e, q = evidence[cid], prior[cid]
        by_group[original_rows_by_case[cid]['source_group']].append(
            (q-y)**2 - (e-y)**2)
    if len(by_group) != COUNTS['test']:
        raise Invalid('insufficient independent passage census')
    diffs = [sum(xs)/len(xs) for _,xs in sorted(by_group.items())]
    rng = random.Random(20261015)
    # Deliberately descriptive for eight correlated passages, not a 95% claim.
    samples = [sum(rng.choice(diffs) for _ in diffs)/len(diffs) for _ in range(512)]
    samples.sort()
    return {'original_human_target': True,
            'human_truth_of_no_evidence_intervention': False,
            'evidence_metrics': metrics([(evidence[cid],labels[cid]) for cid in labels]),
            'trained_question_only_metrics': metrics([(prior[cid],labels[cid]) for cid in labels]),
            'group_equal_weight_brier_gain_positive_means_evidence_better': sum(diffs)/len(diffs),
            'source_passages': len(diffs),
            'groups_evidence_better': sum(x>0 for x in diffs),
            'groups_question_only_better': sum(x<0 for x in diffs),
            'groups_tied': sum(x==0 for x in diffs),
            'per_group_brier_gains': diffs,
            'descriptive_group_resample_5pct': samples[25],
            'descriptive_group_resample_95pct': samples[486],
            'independent_large_sample_causal_advantage': False}


def review(fit, blind, owner, source_train, source_validation, reports):
    """Fail closed before ever selecting a learned model on observed scores."""
    if type(reports) is not dict or set(reports) != set(REQUIRED):
        raise Invalid('incomplete four-model original-human experiment')
    # Re-run original independent source/label/4-model scorer in full. Never
    # interpret the matched prior without a valid physical primary study.
    original = review_original(fit, blind, owner, source_train, source_validation, reports)
    labels = original_label_audit(fit,blind,owner,source_train,source_validation)
    pairs = matched_pairs(fit,blind)
    train = pairs['train']; calibration=pairs['calibration']; test=pairs['test']
    original_rows_by_case={o['case_id']:o for o,p in test}
    if len(original_rows_by_case)!=len(labels) or set(labels)!=set(original_rows_by_case):
        raise Invalid('missing original-label evaluations')
    original_train_ids=[r['case_id'] for r in fit['cases']
                        if r['split']=='train' and r['condition']=='original']
    original_cal_ids=[r['case_id'] for r in fit['cases']
                      if r['split']=='calibration' and r['condition']=='original']
    # Preserve the FIT order when checking paired training exposure, never sort
    # by answer values or anything influenced by held labels.
    order={r['case_id']:i for i,r in enumerate(fit['cases'])}
    train=sorted(train,key=lambda z:order[z[0]['case_id']])
    calibration=sorted(calibration,key=lambda z:order[z[0]['case_id']])
    expected_train_prior=sha(canonical([q['case_id'] for o,q in train]))
    expected_cal_prior=sha(canonical([q['case_id'] for o,q in calibration]))
    train_identity=sha(canonical(original_train_ids))
    cal_identity=sha(canonical(original_cal_ids))
    scored={}
    for model in REQUIRED:
        report=reports[model]
        if model=='laya421_nochange':
            if report.get('matched_question_only_control') is not None:
                raise Invalid('Laya frozen native action is not a trained equal-Head comparator')
            scored[model]={'equal_head_comparison_available':False,
                           'native_nochange_original_study_preserved':True}
            continue
        parent=report.get('training');candidate=report.get('matched_question_only_control')
        profile=report.get('complete_source_profiles')
        if (type(parent) is not dict or type(candidate) is not dict or
                type(profile) is not dict or candidate.get('schema')!=SCHEMA or
                candidate.get('target')!='original_human_binary_label_predicted_without_passage_evidence' or
                candidate.get('no_evidence_material_has_new_human_ground_truth') is not False or
                candidate.get('source_training_only') is not True or
                candidate.get('authority')!='DENY_ALL' or
                candidate.get('production_promotion_permitted') is not False or
                candidate.get('reuse_same_original_shared_encoder_load') is not True or
                candidate.get('additional_model_loads')!=0 or
                candidate.get('additional_encoder_forwards')!=0):
            raise Invalid('missing authenticated same-Encoder question-only research lineage')
        width=384 if model!='embeddinggemma_2_text' else 256
        if (candidate.get('per_head_trainable_parameters')!=2*width+2 or
                candidate['per_head_trainable_parameters']!=parent['parameter_count'] or
                candidate.get('optimizer')!='torch.optim.SGD' or parent.get('optimizer')!='torch.optim.SGD' or
                candidate.get('steps')!=parent.get('steps') or parent['steps']!=40 or
                candidate.get('seed')!=parent.get('seed') or parent['seed']!=20261015 or
                candidate.get('learning_rate')!=parent.get('learning_rate') or parent['learning_rate']!=0.1 or
                candidate.get('train_source_case_ids_sha256')!=train_identity or
                candidate.get('calibration_source_case_ids_sha256')!=cal_identity or
                candidate.get('train_question_case_ids_sha256')!=expected_train_prior or
                candidate.get('calibration_question_case_ids_sha256')!=expected_cal_prior or
                candidate.get('matched_train_example_count')!=len(train) or
                candidate.get('matched_calibration_example_count')!=len(calibration)):
            raise Invalid('optimizer/Head/batch/source budget unequal')
        initial=_sha(candidate.get('original_and_prior_initial_tensor_sha256'))
        if initial!=parent.get('initial_frozen_head_sha256'):
            raise Invalid('different initial Head weights')
        c=candidate.get('complete_prior_controls')
        if type(c) is not dict or set(c)!={'question_frozen_head','question_trained_head'}:
            raise Invalid('incomplete matched prior frozen/learned controls')
        if (_sha(c['question_frozen_head'].get('head_sha256')) != initial or
                _sha(c['question_trained_head'].get('head_sha256')) == initial):
            raise Invalid('incorrect physical prior tensor update or frozen control')
        train_ms=numeric(candidate.get('question_only_head_training_ms'),positive=True)
        enc=profile.get('physical_encoder_ms_by_case')
        all_input={row['case_id'] for row in fit['cases']+blind['cases']}
        if type(enc) is not dict or set(enc)!=all_input:
            raise Invalid('missing real per-row shared Encoder work')
        enc_sum=sum(numeric(v,positive=True) for v in enc.values())
        load=numeric(profile.get('model_load_ms'),positive=True)
        head_train=numeric(parent.get('head_training_ms'),positive=True)
        total_wall=numeric(report.get('local_process_wall_ms'),positive=True)
        paid_old=sum(numeric(p.get('head_request_ms'),positive=True)
                     for arm in report['control'].values() for p in arm['predictions'])
        paid_new=0.0
        prior_pred={}
        expected={q['case_id']:(o['case_id'],q['view_sha256']) for o,q in test}
        for name,arm in c.items():
            numeric(arm.get('temperature'),positive=True)
            predictions=arm.get('predictions')
            if type(predictions) is not list or len(predictions)!=len(expected):
                raise Invalid('missing candidate-only matched heldout responses')
            seen={}
            for p in predictions:
                if type(p) is not dict or set(p)!={'original_case_id','no_evidence_case_id',
                                                  'no_evidence_view_sha256','positive_probability',
                                                  'head_request_ms'}:
                    raise Invalid('unexpected prior scorer fields')
                key=p['no_evidence_case_id']
                if (key not in expected or key in seen or
                        p['original_case_id']!=expected[key][0] or
                        p['no_evidence_view_sha256']!=expected[key][1]):
                    raise Invalid('swapped/replayed prior inference or changed original task')
                val=probability(p.get('positive_probability'))
                paid_new+=numeric(p.get('head_request_ms'),positive=True)
                seen[key]=val
            if len(seen)!=len(expected):
                raise Invalid('missing no-evidence test vector')
            prior_pred[name]={original:seen[q] for q,(original,_) in expected.items()}
        if load+enc_sum+head_train+train_ms+paid_old+paid_new>total_wall+5.0:
            raise Invalid('resource double count, missing wall or fabricated timings')
        evidence={}
        frozen={}
        for arm,output in (('trained_head',evidence),('frozen_head',frozen)):
            for p in report['control'][arm]['predictions']:
                if p['case_id'] in labels:
                    output[p['case_id']]=probability(p['positive_probability'])
        learned=_paired_metrics(evidence,prior_pred['question_trained_head'],labels,original_rows_by_case)
        frozen_result=_paired_metrics(frozen,prior_pred['question_frozen_head'],labels,original_rows_by_case)
        hard_exact=[];byquestion=defaultdict(list)
        for cid,row in original_rows_by_case.items():
            if normalized(row['candidate_text']) in normalized(row['joint_input']['state']):
                byquestion[(row['source_group'],row['question_id'])].append((cid,labels[cid]))
        for entries in byquestion.values():
            if {y for _,y in entries}=={0,1}:
                positives=[cid for cid,y in entries if y==1]
                negatives=[cid for cid,y in entries if y==0]
                hard_exact.append({
                    'evidence_true_above_false':int(min(evidence[x] for x in positives)>
                                                    max(evidence[x] for x in negatives)),
                    'question_only_true_above_false':int(min(prior_pred['question_trained_head'][x]
                                                        for x in positives)>
                                                     max(prior_pred['question_trained_head'][x]
                                                         for x in negatives))})
        scored[model]={
            'equal_head_comparison_available':True,
            'shared_pretrained_encoder_features_reused':True,
            'head_parameter_count_each':candidate['per_head_trainable_parameters'],
            'same_optimizer_steps_and_original_training_examples':True,
            'learned_evidence_versus_separately_trained_question_only':learned,
            'frozen_evidence_versus_frozen_question_only':frozen_result,
            'same_question_original_human_hard_exact_count':len(hard_exact),
            'hard_exact_evidence_rank_successes':sum(a['evidence_true_above_false'] for a in hard_exact),
            'hard_exact_question_only_rank_successes':sum(a['question_only_true_above_false'] for a in hard_exact),
            'metered_encoder_ms_all_views_once':enc_sum,
            'metered_evidence_train_ms':head_train,
            'metered_prior_train_ms':train_ms,
            'metered_head_inference_ms_evidence_and_prior':paid_old+paid_new,
            'metered_total_process_wall_ms':total_wall,
            'underpowered_semantic_hard_conclusion':True}
    return {'schema':OUT_SCHEMA, 'original_human_label_cases':len(labels),
            'original_human_scorer_v2':original,
            'matched_models':scored,
            'three_paired_equal_head_models':list(MODEL_HEADS),
            'laya_distinct_frozen_not_equal_head':True,
            'observational_small_english_cross_sectional_only':True,
            'equal_train_budget_is_not_equal_encoder_input_work':True,
            'no_evidence_view_human_entailment_label_invented':False,
            'real_target_host_energy_qualified':False,
            'independent_future_semantic_outcome_established':False,
            'stem_or_model_selection_permitted':False,
            'production_promotion_permitted':False, 'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser()
    for name in ('fit','blind','labels','train_parquet','validation_parquet','output'):
        p.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    for model in REQUIRED:
        p.add_argument('--'+model.replace('_','-'),type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError('create-only matched study review')
    fit=read(args.fit);blind=read(args.blind);labels=read(args.labels)
    meta=fit['metadata']
    a=original_rows(args.train_parquet,meta['train_sha256'])
    b=original_rows(args.validation_parquet,meta['validation_sha256'])
    result=review(fit,blind,labels,a,b,{m:read(getattr(args,m)) for m in REQUIRED})
    save(args.output,result)
    print(json.dumps({'schema':OUT_SCHEMA,'original_cases':result['original_human_label_cases'],
                      'selected_stem':None,'authority':'DENY_ALL'}))


if __name__=='__main__':
    main()
