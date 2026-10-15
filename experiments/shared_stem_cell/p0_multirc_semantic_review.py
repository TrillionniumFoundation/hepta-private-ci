#!/usr/bin/env python3
"""Source-replayed held-label MultiRC score. No model execution/authorization.

Only ORIGINAL human-annotated passage/candidate pairs have ground truth.
Unlabeled no-evidence probes remain diagnostics, never fabricated negatives.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from p0_multirc_semantic_material import (build, canonical, sha, read, save,
    normalized, tokens, Invalid, SCHEMA, COUNTS, original_rows)

REQUIRED = ('granite_97m_r2','mmbert_small','embeddinggemma_2_text','laya421_nochange')
REVISIONS = {'granite_97m_r2':'835ad14087e140460703cf0fae09f97d469d65c2',
 'mmbert_small':'0eb3d056ec1d6333cf4e19b0966dfde342a41a3a',
 'embeddinggemma_2_text':'914f7f89142e33e77833254d9c9b90c3cef7303b',
 'laya421_nochange':'c5d78730f3493e4fe16d61507ef4b78eef7318cf'}


def numeric(v, *, positive=False):
    if type(v) not in (int,float) or not math.isfinite(v) or (v<=0 if positive else v<0):
        raise Invalid('invalid/missing observed physical cost')
    return float(v)


def probability(v):
    p=numeric(v)
    if p>1:
        raise Invalid('probability outside valid range')
    return p


def metrics(rows):
    if not rows:
        return None
    return {'rows':len(rows), 'accuracy':sum((p>=.5)==bool(label) for p,label in rows)/len(rows),
            'brier':sum((p-label)**2 for p,label in rows)/len(rows),
            'positive_support':sum(y for _,y in rows),
            'negative_support':sum(1-y for _,y in rows)}


def original_label_audit(fit,blind,owner,source_train,source_validation):
    meta=fit['metadata'];source_fit,source_blind,source_owner=build(source_train,source_validation,
         train_sha=meta['train_sha256'],validation_sha=meta['validation_sha256'])
    if canonical(source_fit)!=canonical(fit) or canonical(source_blind)!=canonical(blind):
        raise Invalid('SOURCE MISMATCH: original row/candidate/hidden-eval task changed')
    if canonical(source_owner)!=canonical(owner):
        raise Invalid('SOURCE MISMATCH: target labels, identities or source receipt changed')
    if (owner.get('schema')!='hepta.p0.multirc-original-human-labels.v1' or
            owner.get('generated_intervention_labels_invented') is not False or
            owner.get('authority')!='DENY_ALL'):
        raise Invalid('untrusted human-label receipt')
    return owner['original_human_candidate_labels']


def review(fit,blind,owner,source_train,source_validation,reports):
    if type(reports) is not dict or set(reports)!=set(REQUIRED):
        raise Invalid('missing four independent real-model arms')
    labels=original_label_audit(fit,blind,owner,source_train,source_validation)
    all_rows=blind['cases'];source_by_case={r['case_id']:r for r in all_rows}
    eval_original={r['case_id']:r for r in all_rows if r['condition']=='original'}
    if len(eval_original)!=len(labels) or set(labels)!=set(eval_original):
        raise Invalid('wrong original annotated candidate denominator')
    if len({x['source_group'] for x in eval_original.values()})!=COUNTS['test']:
        raise Invalid('wrong independent source group count')
    by_question=defaultdict(list)
    presence={}
    overlap={}
    for cid,r in eval_original.items():
        y=labels[cid]
        if type(y) is not int or y not in (0,1):
            raise Invalid('bad original human label')
        evidence=r['joint_input']['state']
        answer=r['candidate_text']
        present=normalized(answer) in normalized(evidence)
        w=set(tokens(answer));doc=set(tokens(evidence))
        shared=(len(w&doc)/len(w)) if w else 0
        presence[cid]=present
        overlap[cid]=shared
        by_question[(r['source_group'],r['question_id'])].append((cid,y,present,shared))
    original_results=[]
    for cid,y in labels.items():
        original_results.append((float(presence[cid]),y))
    lexical=metrics(original_results)
    # Fixed BEFORE inspecting model results. Only original MultiRC labels count.
    hard_exact={cid for rows in by_question.values()
                if {y for _,y,p,_ in rows if p}=={0,1}
                for cid,y,p,_ in rows if p}
    hard_overlap={cid for rows in by_question.values()
                  if {y for _,y,_,o in rows if o>=.75}=={0,1}
                  for cid,y,_,o in rows if o>=.75}
    same_answer=defaultdict(set)
    for cid,r in eval_original.items():
        same_answer[normalized(r['candidate_text'])].add(labels[cid])
    matched_answers=sum(v=={0,1} for v in same_answer.values())
    byid=defaultdict(dict)
    for r in all_rows:
        key=(r['source_group'],r['question_id'],r['answer_id'])
        byid[key][r['condition']]=r
    if any(set(d)!={'original','no_evidence'} for d in byid.values()):
        raise Invalid('incomplete original/no-evidence diagnostic pair')
    outputs={}
    fit_train = [r['case_id'] for r in fit['cases']
                 if r['condition']=='original' and r['split']=='train']
    fit_calibration = [r['case_id'] for r in fit['cases']
                       if r['condition']=='original' and r['split']=='calibration']
    train_digest=sha(canonical(fit_train))
    calibration_digest=sha(canonical(fit_calibration))
    for model in REQUIRED:
        report=reports[model]
        if (type(report) is not dict or
                report.get('schema')!='hepta.p0.multirc-original-semantic-physical.v1' or
                report.get('dataset_schema')!=SCHEMA or
                report.get('model')!=model or report.get('model_revision')!=REVISIONS[model] or
                report.get('panel_id')!=fit['metadata']['panel_id'] or
                report.get('fit_material_sha256')!=sha(canonical(fit)) or
                report.get('blind_material_sha256')!=sha(canonical(blind)) or
                report.get('eval_blind_rows')!=len(all_rows) or
                report.get('actual_pretrained_local_weights_claimed') is not True or
                report.get('physical_model_origin_independently_signed') is not False or
                report.get('model_selection_permitted') is not False or
                report.get('production_promotion_permitted') is not False or
                report.get('authority')!='DENY_ALL'):
            raise Invalid('modified source/run identity or false physical authority')
        cost={k:numeric(report.get(k),positive=True) for k in
             ('local_process_wall_ms','local_process_cpu_ms','local_peak_rss_bytes')}
        if report.get('training') is None:
            if model!='laya421_nochange' or report.get('head_mode')!='pretrained_checkpoint_native_noul_nochange_not_equal_head':
                raise Invalid('missing authentic training or wrong Laya mode')
        else:
            if model=='laya421_nochange':
                raise Invalid('pretend Laya had equal-sized Head')
            profile=report.get('complete_source_profiles')
            expected=2*(384 if model in ('granite_97m_r2','mmbert_small') else 256)+2
            training=report['training']
            if (type(training) is not dict or training.get('parameter_count')!=expected or
                    training.get('steps')!=40 or training.get('seed')!=20261015 or
                    training.get('learning_rate')!=0.1 or
                    training.get('optimizer')!='torch.optim.SGD' or
                    training.get('fit_train_case_ids_sha256')!=train_digest or
                    training.get('calibration_case_ids_sha256')!=calibration_digest or
                    training.get('train_labels_only_in_gradient') is not True or
                    type(profile) is not dict or
                    profile.get('physical_encoder_api_requests')!=len(fit['cases'])+len(all_rows)):
                raise Invalid('training parameter, schedule or physical call mismatch')
            numeric(training.get('head_training_ms'),positive=True)
            numeric(profile.get('model_load_ms'),positive=True)
            if profile['model_load_ms']+training['head_training_ms']>cost['local_process_wall_ms']+5:
                raise Invalid('impossible physically reported complete lifecycle')
            if model=='mmbert_small' and profile.get('complete_mmbert_weight_bytes_checked') is not True:
                raise Invalid('mmBERT missing whole pretrained table integrity')
        controls=report.get('control')
        expected_controls=({'laya_native_nochange'} if model=='laya421_nochange'
                           else {'frozen_head','trained_head'})
        if type(controls) is not dict or set(controls)!=expected_controls:
            raise Invalid('frozen or learned baseline missing')
        if model!='laya421_nochange':
            # These lineage links are checked against the actual immutable
            # training/calibration case census, not self-reported arbitrary SHAs.
            initial=training.get('initial_frozen_head_sha256')
            if (not isinstance(initial,str) or len(initial)!=64 or
                    any(c not in '0123456789abcdef' for c in initial) or
                    controls['frozen_head'].get('head_sha256')!=initial or
                    controls['trained_head'].get('head_sha256')==initial or
                    training.get('controls')!=controls):
                raise Invalid('frozen/learned Head tensor lineage or controls diverged')
        else:
            if numeric(report.get('model_load_ms'),positive=True)>cost['local_process_wall_ms']+5:
                raise Invalid('Laya model load exceeds whole local process time')
        arms={}
        complete_measured_requests=0.0
        for arm,material in controls.items():
            if type(material) is not dict or type(material.get('predictions')) is not list:
                raise Invalid('missing original sealed predictions')
            preds={}
            for p in material['predictions']:
                if (type(p) is not dict or type(p.get('case_id')) is not str or
                        p['case_id'] in preds or p['case_id'] not in source_by_case or
                        p.get('view_sha256')!=source_by_case[p['case_id']]['view_sha256']):
                    raise Invalid('swapped, duplicate or unregistered model task')
                preds[p['case_id']]=probability(p.get('positive_probability'))
                tick=('full_request_ms' if model=='laya421_nochange' else 'head_request_ms')
                complete_measured_requests+=numeric(p.get(tick),positive=True)
            if len(preds)!=len(all_rows):
                raise Invalid('one physical model missing full blind census')
            full=[(preds[cid],y) for cid,y in labels.items()]
            signed=[preds[d['original']['case_id']]-preds[d['no_evidence']['case_id']]
                    for d in byid.values()]
            hard=[(preds[cid], labels[cid]) for cid in hard_exact]
            relaxed=[(preds[cid], labels[cid]) for cid in hard_overlap]
            # Counterfactual has no label; report only sensitivity, never accuracy.
            # The true target is the HUMAN LABEL OF THE ORIGINAL INPUT.
            # A no-evidence model score is a prior-only predictor of that same
            # target, NOT a newly human-labeled empty-passage entailment claim.
            evidence_brier_by_source=defaultdict(list)
            prior_for_original=[]
            for d in byid.values():
                r=d['original']
                y=labels[r['case_id']]
                true_p=preds[r['case_id']]
                prior_p=preds[d['no_evidence']['case_id']]
                evidence_brier_by_source[r['source_group']].append(
                    (prior_p-y)**2-(true_p-y)**2)
                prior_for_original.append((prior_p,y))
            if set(evidence_brier_by_source)!={r['source_group'] for r in eval_original.values()}:
                raise Invalid('incomplete paired evidence source groups')
            group_deltas=[sum(v)/len(v) for _,v in sorted(evidence_brier_by_source.items())]
            evidence_diagnostic={
                'target':'original_human_label_only_not_no_evidence_entailment',
                'no_evidence_prior_predictor_against_original_labels':metrics(prior_for_original),
                'mean_paired_brier_gain_positive_is_better':sum(group_deltas)/len(group_deltas),
                'per_source_brier_gain_count':len(group_deltas),
                'source_groups_improved':sum(x>0 for x in group_deltas),
                'source_groups_harmed':sum(x<0 for x in group_deltas),
                'source_groups_tied':sum(x==0 for x in group_deltas),
                'minimum_group_gain':min(group_deltas),
                'maximum_group_gain':max(group_deltas),
                'matched_head_budget_not_a_separately_trained_prior':True,
                'causal_semantic_superiority_proven':False}
            group_concordance=[]
            for rows in by_question.values():
                if {y for _,y,p,_ in rows if p}=={0,1}:
                    ps=[preds[cid] for cid,y,p,_ in rows if p and y==1]
                    ns=[preds[cid] for cid,y,p,_ in rows if p and y==0]
                    group_concordance.append(float(min(ps)>max(ns)))
            arms[arm]={'original_human_label':metrics(full),'original_human_hard_exact':metrics(hard),
                       'original_human_hard_overlap75':metrics(relaxed),
                       'original_minus_no_evidence_mean_probability_shift':sum(signed)/len(signed),
                       'same_question_hard_exact_positive_beats_negative':(
                           sum(group_concordance)/len(group_concordance) if group_concordance else None),
                       'hard_question_count':len(group_concordance),
                       'evidence_vs_priors_original_target_only':evidence_diagnostic}
        if complete_measured_requests>cost['local_process_wall_ms']+5:
            raise Invalid('summed paid requests exceed observed process lifetime')
        outputs[model]={'arms':arms,'physical_costs_unattested':cost,
                        'measured_head_or_laya_request_time_ms':complete_measured_requests,
                        'comparison_with_equal_parameter_head_permitted':model!='laya421_nochange'}
    return {'schema':'hepta.p0.multirc-original-semantic-independent-review.v2',
            'original_human_answer_rows':len(labels),
            'independent_source_passages':COUNTS['test'],
            'cheap_exact_literal_presence_baseline':lexical,
            'original_human_exact_lexical_hard_rows':len(hard_exact),
            'original_human_overlap75_hard_rows':len(hard_overlap),
            'same_answer_text_with_opposite_original_labels':matched_answers,
            'models':outputs,
            'hard_question_independence_sufficient_for_95pct_claims':False,
            'artificially_transformed_evidence_has_human_label':False,
            'new_future_task_benefit_verified':False,
            'pretraining_contamination_or_source_origin_independently_certified':False,
            'no_evidence_has_new_human_ground_truth':False,
            'no_evidence_only_a_predictor_for_original_target':True,
            'model_winner_selected':False,'production_promotion_permitted':False,
            'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser()
    for k in ('fit','blind','labels','train_parquet','validation_parquet','output'):
        p.add_argument('--'+k.replace('_','-'),type=Path,required=True)
    for m in REQUIRED:
        p.add_argument('--'+m.replace('_','-'),type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():
        raise FileExistsError('independent evaluation is write-once')
    fit=read(a.fit);blind=read(a.blind);labels=read(a.labels)
    meta=fit['metadata']
    source_train=original_rows(a.train_parquet,meta['train_sha256'])
    source_validation=original_rows(a.validation_parquet,meta['validation_sha256'])
    outputs=review(fit,blind,labels,source_train,source_validation,
                   {m:read(getattr(a,m)) for m in REQUIRED})
    save(a.output,outputs)
    print(json.dumps({'human_original_rows':outputs['original_human_answer_rows'],
                      'hard_subset':outputs['original_human_exact_lexical_hard_rows'],
                      'production_accepted':False,'authority':'DENY_ALL'}))

if __name__=='__main__':main()
