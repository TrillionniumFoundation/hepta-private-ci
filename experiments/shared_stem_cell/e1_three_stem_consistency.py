#!/usr/bin/env python3
"""E1 three-Encoder *observational* parity. No model download or selection.

Consumes per-model E1 sources already checked by the separate confirmatory
reviewer. Reports descriptive matched-case metrics, not verified pretrained
execution, independent Reader capacity or real future NDU.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from e1e5_confirmatory_review import _cases, Invalid, E1_PROFILES, FUTURES, SPLITS, load

SCHEMA = 'hepta.stem-e1-three-candidate-panel.v1'
OUT_SCHEMA = 'hepta.stem-e1-three-candidate-parity.v1'
CANDIDATES = ('granite_97m_r2', 'mmbert_small', 'embeddinggemma_2_text')
# The original public Gemma research panel remains unchanged. The core triad
# requested for Hepta's Stem selection is a separate, incompatible schema.
CORE_SCHEMA = 'hepta.stem-e1-core-granite-mmbert-modernbert.v1'
CORE_OUT_SCHEMA = 'hepta.stem-e1-core-triad-parity.v1'
CORE_CANDIDATES = ('granite_97m_r2', 'mmbert_small', 'modernbert_base')
CORE_REVISIONS = {
    'granite_97m_r2': '835ad14087e140460703cf0fae09f97d469d65c2',
    'mmbert_small': '0eb3d056ec1d6333cf4e19b0966dfde342a41a3a',
    'modernbert_base': 'fa3113d09d6dacfe5528708803dd92a62240237a',
}

MAX_CASES = 50000
FAMILIES = ('zh', 'en', 'code')


def d256(v):
    if (type(v) is not str or len(v) != 64 or v == '0'*64 or
            any(c not in '0123456789abcdef' for c in v)):
        raise Invalid('noncanonical evidence digest')
    return v


def stable(v):
    if (type(v) is not str or not 1 <= len(v) <= 128 or
            any(not (c.isascii() and (c.isalnum() or c in '._:-')) for c in v)):
        raise Invalid('invalid identifier')
    return v


def finite(v):
    if type(v) not in (float,int) or not math.isfinite(v) or v < 0:
        raise Invalid('missing numeric value')
    return float(v)


def _case_fingerprint(row):
    return tuple(row[k] for k in ('case_id', 'source_group', 'input_sha256',
              'split', 'scope', 'observed_at', 'modality', 'reader_condition',
              'reader_correct', 'answer_label', 'language', 'task_family'))


def review(panel):
    if (type(panel) is not dict or panel.get('schema') not in (SCHEMA, CORE_SCHEMA) or
            panel.get('authority') != 'DENY_ALL' or
            panel.get('production_promotion_permitted') is not False):
        raise Invalid('invalid/nonresearch E1 panel')
    for key in ('plan_sha256', 'dataset_sha256', 'no_change_producer_sha256'):
        d256(panel.get(key))
    cohort = CORE_CANDIDATES if panel['schema'] == CORE_SCHEMA else CANDIDATES
    scope=stable(panel.get('scope'))
    items=panel.get('candidates')
    if type(items) is not list or len(items) != 3:
        raise Invalid('exact three candidate entries required')
    seen=set();canonical_cases=None;no_change=None;baseline_identity=None
    shared_training=None;model_ids=set();runs=set();evidence={};predictions={}
    for item in items:
        if type(item) is not dict or set(item) != {'model', 'run_sha256', 'study', 'training', 'tokens'}:
            raise Invalid('malformed candidate record')
        model=item['model']
        if model not in cohort or model in seen:
            raise Invalid('duplicate or unregistered Encoder')
        seen.add(model)
        run=d256(item['run_sha256'])
        if run in runs:raise Invalid('recycled physical execution receipt')
        runs.add(run)
        study=item['study']
        if type(study) is not dict or study.get('stage') != 'E1' or study.get('encoder_candidate') != model:
            raise Invalid('wrong candidate study')
        if study.get('dataset_sha256') != panel['dataset_sha256'] or study.get('plan_sha256') != panel['plan_sha256'] or study.get('scope') != scope:
            raise Invalid('dataset/plan/Scope mismatch')
        cases,arms=_cases(study)
        if panel['schema'] == CORE_SCHEMA and study['upstream_revision'] != CORE_REVISIONS[model]:
            raise Invalid('unapproved core Stem model revision')
        if not 3 <= len(cases) <= MAX_CASES or set(c['split'] for c in cases.values()) != set(SPLITS):
            raise Invalid('full cross-sectional + future/OOD cohort required')
        if any(c.get('modality') not in ('text','code') or c.get('language') not in FAMILIES or
               c.get('task_family') not in ('chinese_semantics','english_semantics','code_diagnostics') or
               (c['language'],c['task_family']) not in (('zh','chinese_semantics'),('en','english_semantics'),('code','code_diagnostics'))
               for c in cases.values()):
            raise Invalid('missing or incoherent Chinese/English/code task family')
        for split in SPLITS:
            if {c['language'] for c in cases.values() if c['split']==split} != set(FAMILIES):
                raise Invalid('every split needs independent Chinese, English and code cases')
        records={id:_case_fingerprint(c) for id,c in cases.items()}
        if canonical_cases is None:canonical_cases=records
        elif canonical_cases != records:raise Invalid('cross-model sample/label/time/source drift')
        t=item['training']
        if type(t) is not dict or set(t) != {'seed','steps','batch_size','learning_rate','head_kind','head_ceiling','trainable_head_parameters','optimizer','train_case_sha256','minibatch_sha256'}:
            raise Invalid('incomplete training budget')
        if (any(type(t[k]) is not int or t[k] < 1 for k in ('steps','batch_size','head_ceiling','trainable_head_parameters')) or
                type(t['seed']) is not int or t['head_ceiling'] not in (2048,8192,16384) or
                t['trainable_head_parameters'] > t['head_ceiling'] or
                t['head_kind'] not in ('linear','film','rank8','rank16','mlp','swiglu') or
                t['optimizer'] not in ('adamw','sgd')):
            raise Invalid('Head training mismatch/ceiling exceeded')
        if finite(t['learning_rate']) <= 0:
            raise Invalid('invalid learning rate')
        for k in ('train_case_sha256','minibatch_sha256'):d256(t[k])
        comparable=tuple((k,t[k]) for k in ('seed','steps','batch_size','learning_rate','head_kind','head_ceiling','optimizer','train_case_sha256','minibatch_sha256'))
        if shared_training is None:shared_training=comparable
        elif comparable!=shared_training:raise Invalid('unmatched training schedule')
        tokens=item['tokens']
        if type(tokens) is not dict or set(tokens) != set(cases):raise Invalid('incomplete model-specific token counts')
        if any(type(x) is not int or not 1<=x<=512 for x in tokens.values()):
            raise Invalid('tokenization exceeded preregistered cap or truncated')
        learned=arms['learned_head'];frozen=arms['frozen_head'];unchanged=arms['no_change']
        if learned[0]['model_sha256'] != frozen[0]['model_sha256']:
            raise Invalid('same Encoder not shared by learned/frozen controls')
        if learned[0]['model_sha256'] in model_ids:raise Invalid('different candidate names share model identity')
        model_ids.add(learned[0]['model_sha256'])
        this_base=(unchanged[0]['model_sha256'],unchanged[0]['head_sha256'])
        if baseline_identity is None:baseline_identity=this_base
        elif baseline_identity!=this_base:raise Invalid('no-change model/Head identity drift')
        if no_change is None:no_change=unchanged[1]
        else:
            if any(abs(no_change[k]-unchanged[1][k])>1e-12 for k in cases):
                raise Invalid('no-change predictions differ across candidates')
        predictions[model]={name:arms[name][1] for name in ('learned_head','frozen_head','no_change')}
        evidence[model]={'upstream_revision':study['upstream_revision'],
                         'feature_width':E1_PROFILES[model][0],
                         'pooling_profile':E1_PROFILES[model][1],
                         'trained_head_parameters_claimed':t['trainable_head_parameters'],
                         'reported_model_sha256':learned[0]['model_sha256'],
                         'token_count_min':min(tokens.values()),
                         'token_count_max':max(tokens.values()),
                         'reported_lifecycle_ms':sum(learned[0]['resources'][k] for k in ('load_ms','encode_ms','bridge_fit_ms','head_train_ms','cache_ms','migration_ms','recompute_ms','serving_ms','evaluation_ms','checkpoint_ms')),
                         'reported_peak_rss_bytes':learned[0]['resources']['peak_rss_bytes']}
    if seen != set(cohort):raise Invalid('three Stem candidates incomplete')
    rows_by_split=defaultdict(list)
    for case_id,fingerprint in canonical_cases.items():
        rows_by_split[fingerprint[3]].append((case_id,fingerprint[-3],fingerprint[1],fingerprint[-2]))
    descriptive={}
    for split in ('test',*FUTURES,'ood'):
        rows=rows_by_split[split];descriptive[split]={}
        for model in cohort:
            desc={}
            for label,pred in predictions[model].items():
                correct=sum(int((pred[k]>=.5)==bool(y)) for k,y,_,_ in rows)
                brier=sum((pred[k]-y)**2 for k,y,_,_ in rows)/len(rows)
                desc[label]={'n':len(rows),'source_groups':len({g for _,_,g,_ in rows}),
                             'accuracy':correct/len(rows),'brier':brier}
            desc['learned_minus_frozen_accuracy']=desc['learned_head']['accuracy']-desc['frozen_head']['accuracy']
            desc['learned_minus_no_change_accuracy']=desc['learned_head']['accuracy']-desc['no_change']['accuracy']
            desc['family_case_counts']={f:sum(row[3]==f for row in rows) for f in FAMILIES}
            descriptive[split][model]=desc
    return {'schema': CORE_OUT_SCHEMA if panel['schema'] == CORE_SCHEMA else OUT_SCHEMA,
            'models':evidence,'matched_source_cases':len(canonical_cases),
            'core_triad_exact_revisions_declared':panel['schema'] == CORE_SCHEMA,
            'production_no_change_source_independently_authenticated':False,
            'independent_reader_and_future_outcome_authority':False,
            'matched_training_ceiling_and_schedule':True,
            'unchanged_production_baseline_predictions_reused':True,
            'descriptive_split_metrics':descriptive,
            'reader_sufficient_accuracy_independently_verified':False,
            'model_weight_origin_and_physical_execution_verified':False,
            'future_predictions_prelabel_seal_independently_verified':False,
            'external_ndu_outcomes_verified':False,
            'lifecycle_cpu_gpu_energy_costs_independently_verified':False,
            'stem_winner_selected':False,'all_acceptance_gates_passed':False,
            'production_promotion_permitted':False,'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--panel',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    payload,source_sha=load(a.panel)
    result=review(payload);result['panel_file_sha256']=source_sha
    with a.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')

if __name__=='__main__':main()
