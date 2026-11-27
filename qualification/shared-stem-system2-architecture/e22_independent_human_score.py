"""E22 separate ORIGINAL human MultiRC scorer of source-sealed E15/E16 folds.

Replays E15 whole-question scoring and original E16 independent 48-step
training on genuine other-passage labels, then checks BOTH E16 hosted scores.
No method wins production admission on four old passage groups.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import itertools
import math

from e21_whole_question import (once, _json_bytes, _zip, evaluate as e21_evaluate,
                                score_from_labels as e21_score, ALL as E15_METHODS,
                                SCHEMA as E21_SCHEMA, E15_SCORES, signflip_p)
from e14_multirc_score import original_labels, read_validation, VAL_SHA
from e16_independent_score import evaluate as independent_e16, SCHEMA as E16_SCHEMA
from e22_e16_question_gate import (SCHEMA, ALL, E16_FOLDS, E16_METHODS, E16_HEAD,
                                    blind_e22)

SCORE_SCHEMA='hepta.e22.original-human-eight-arm-whole-question-negative-gate.v1'
E16_SCORES=(
    (11953241456,'8f8ac3c4ed99b4859b9d0258d19c2afdaca1ac194a806130196b3d9980aa91a4',E16_HEAD),
    (11952742279,'8dc6e34ff5d70eca8d4986a87e574c1cf2a0926b6c2dcf7b972c84e1954d8b60','14cf1a7de3b1d7269a1952afa75a188fe65e4705'),
)


def question_metrics(blind, labels):
    """Independently score all real original question/candidate/passage units."""
    if (type(blind) is not dict or set(blind) != {
            'schema','authority','production_accepted','model_selected','system2_fbsde_permitted',
            'source_archive_sha256','e16_head','human_labels_opened','new_pretrained_forwards',
            'source_passages','questions','candidates',
            'original_training_and_inference_costs_not_complete','e16_observed_student_CPU_ns','rows'}
        or blind['schema'] != SCHEMA or blind['authority'] != 'DENY_ALL'
        or blind['production_accepted'] is not False or blind['model_selected'] is not False
        or blind['system2_fbsde_permitted'] is not False
        or blind['human_labels_opened'] is not False
        or type(blind['new_pretrained_forwards']) is not int or blind['new_pretrained_forwards'] != 0
        or blind['e16_head'] != E16_HEAD
        or blind['original_training_and_inference_costs_not_complete'] is not True
        or (blind['source_passages'],blind['questions'],blind['candidates']) != (4,8,33)):
        raise ValueError('not a qualifying E22 original pretrained blind score')
    rows=blind['rows']
    if type(rows) is not list or len(rows)!=33 or type(labels) is not dict or set(labels)!={r['task_id'] for r in rows}:
        raise ValueError('incomplete original human label/candidate panel')
    by_method={name:{'correct':0,'brier_sum':0.,'question':defaultdict(list),
                     'passage':defaultdict(list)} for name in ALL}
    true_by_question=defaultdict(set)
    for row in rows:
        if (type(row) is not dict or set(row) != {
             'task_id','source_group','question_slot','candidate_id','original_v1_candidate','probs'}
            or type(row['original_v1_candidate']) is not bool
            or type(row['probs']) is not dict or set(row['probs'])!=set(ALL)):
            raise ValueError('malformed original candidate action')
        source=row['source_group'];q=(source,row['question_slot']);truth=labels[row['task_id']]
        if type(truth) is not int or truth not in (0,1):raise ValueError('not original true binary label')
        true_by_question[q].add(truth)
        for name,p in row['probs'].items():
            if type(p) is not float or not math.isfinite(p) or not 0<p<1:
                raise ValueError('invalid original probability')
            hit=int(((p >= .5) if name not in E15_METHODS[:4] else (p > .5))==bool(truth))
            v=by_method[name];v['correct']+=hit;v['brier_sum']+=2*(p-truth)**2
            v['question'][q].append(hit);v['passage'][source].append(hit)
    if (len(true_by_question)!=8 or any(ys!={0,1} for ys in true_by_question.values())
            or len({g for g,_ in true_by_question})!=4):
        raise ValueError('historical questions do not have mixed human labels')
    metrics={}
    for name,v in by_method.items():
        metrics[name]={
            'correct':v['correct'],'total':33,'brier':v['brier_sum']/33,
            'complete_original_questions':sum(all(h) for h in v['question'].values()),
            'complete_original_passages':sum(all(h) for h in v['passage'].values()),
            'passage_correct':{k:sum(x) for k,x in sorted(v['passage'].items())},
            'passage_total':{k:len(x) for k,x in sorted(v['passage'].items())},
            'question_success':{f'{g}:{q}':int(all(x)) for (g,q),x in sorted(v['question'].items())},
        }
    return metrics


def audit(source, e15_folds, e16_folds, blind_path, validation,
          e15_scores, e16_scores):
    if (len(e15_scores)!=2 or len(e16_scores)!=2):
        raise ValueError('two full independent hosted score profiles required')
    sealed=Path(blind_path).read_bytes()
    if not 0<len(sealed)<2_000_000:
        raise ValueError('empty or excessive create-only sealed blind research source')
    original=_json_bytes(sealed)
    expected=blind_e22(source,e15_folds,e16_folds)
    if expected != original:
        raise ValueError('E22 blind predictions changed even when source receipt was re-signed')
    from e21_whole_question import VAL_SHA as E21_VAL_SHA
    if E21_VAL_SHA!=VAL_SHA or sha256(Path(validation).read_bytes()).hexdigest()!=VAL_SHA:
        raise ValueError('exact original validation owner source changed')
    originals=[{k:v[k] for k in ('task_id','source_group','question_slot','candidate_id','original_v1_candidate')}
               for v in original['rows']]
    truths=original_labels(read_validation(validation),originals)
    methods=question_metrics(original,truths)
    # E21 evaluator independently recreates baseline and the E15 trained heads.
    e21_blind={
        'schema':E21_SCHEMA,'authority':'DENY_ALL','production_accepted':False,
        'source_archive_sha256':original['source_archive_sha256'],
        'e15_head':'d4d71baa8c00821fe385c1a47ed7b68b4255ad6e',
        'real_pretrained_forwards_new':0,'held_human_labels_opened':False,
        'source_group_count':4,'question_count':8,'candidate_count':33,
        'rows':[{**{k:r[k] for k in ('task_id','source_group','question_slot','candidate_id',
                                      'original_v1_candidate')},
                  'probs':{m:r['probs'][m] for m in E15_METHODS}} for r in original['rows']],
    }
    e15=e21_evaluate(e21_blind,truths,*e15_scores)
    for name in E15_METHODS:
        own=methods[name];older=e15['method_results'][name]
        if (own['correct'] != older['correct'] or abs(own['brier']-older['brier'])>2e-12 or
            own['complete_original_questions']!=older['complete_question_count'] or
            own['complete_original_passages']!=older['complete_passage_count'] or
            own['passage_correct']!=older['passage_correct']):
            raise ValueError('independent E21 and E22 human-level scorers disagree')
    # Do not trust E16 claimed fitted weights: re-fit all four folds using a
    # separate numerical optimizer on the authentic three-passage train labels.
    with TemporaryDirectory() as td:
        paths=[];hashes=[]
        for fold,(_,outer,inner) in enumerate(E16_FOLDS):
            parts=_zip(e16_folds[fold],outer,('held-prediction.json',))
            f=Path(td)/f'fold-{fold}.json';f.write_bytes(parts['held-prediction.json'])
            paths.append(str(f));hashes.append(inner)
        real_replay=independent_e16(source,validation,paths,hashes)
    if (real_replay['schema']!=E16_SCHEMA or real_replay['authority']!='DENY_ALL'
            or real_replay['production_accepted'] is not False):
        raise ValueError('E16 independent original human replay not qualified')
    for method in ALL:
        original_score=real_replay['results'][method];cur=methods[method]
        if (original_score['correct']!=cur['correct'] or
            abs(original_score['brier']-cur['brier'])>2e-12 or
            original_score['source_passage_correct']!=cur['passage_correct'] or
            original_score['source_passage_total']!=cur['passage_total']):
            raise ValueError('E16 independently re-trained human score disagrees')
    observed=[]
    for path,(_,expected,expected_head) in zip(e16_scores,E16_SCORES,strict=True):
        parts=_zip(path,expected,('original-human-e16-centered-result.json','score.sha256','source-head.txt'))
        obj=_json_bytes(parts['original-human-e16-centered-result.json'])
        if (parts['source-head.txt'].decode().strip()!=expected_head or
             sha256(parts['original-human-e16-centered-result.json']).hexdigest()!=
                    parts['score.sha256'].decode().split()[0]
                or obj.get('schema')!=E16_SCHEMA or obj.get('authority')!='DENY_ALL'
                or obj.get('production_accepted') is not False
                or obj.get('original_passage_count')!=4 or obj.get('original_human_candidate_count')!=33):
            raise ValueError('historical E16 real label owner receipt changed')
        for method in ALL:
            x=obj['results'][method];y=methods[method]
            if (x['correct']!=y['correct'] or abs(x['brier']-y['brier'])>2e-12 or
                x['source_passage_correct']!=y['passage_correct']):
                raise ValueError('both original E16 CI scores do not match independent human replay')
        observed.append(sha256(parts['original-human-e16-centered-result.json']).hexdigest())
    baseline=methods['mean_pool_query_fused'];learned=methods['centered_scaled_5']
    groups=sorted(baseline['passage_correct'])
    passage_deltas=[learned['passage_correct'][g]-baseline['passage_correct'][g] for g in groups]
    question_deltas=[learned['question_success'][q]-baseline['question_success'][q]
                    for q in sorted(baseline['question_success'])]
    return {
        'schema':SCORE_SCHEMA,'authority':'DENY_ALL','production_accepted':False,
        'model_selected':False,'fbsde_system2_reactivation_permitted':False,
        'original_human_source_sha256':VAL_SHA,
        'source_blind_sha256':sha256(sealed).hexdigest(),
        'original_human_label_source_families':1,
        'independent_original_passage_groups':4,'original_questions':8,'original_candidates':33,
        'independently_retrained_every_E16_fold_from_true_three_passage_training_labels':True,
        'both_original_E15_and_E16_source_merge_human_scores_reconciled':True,
        'e16_human_original_receipt_sha256s':observed,
        'method_results':methods,
        'primary_exploratory_contrast':{
            'candidate':'centered_scaled_5','baseline':'mean_pool_query_fused',
            'candidate_correct_delta':learned['correct']-baseline['correct'],
            'brier_delta':learned['brier']-baseline['brier'],
            'passage_correct_deltas':passage_deltas,
            'question_complete_deltas':question_deltas,
            'complete_question_delta':(learned['complete_original_questions']-
                                       baseline['complete_original_questions']),
            'four_group_exact_signflip_p_descriptive_only':signflip_p(passage_deltas),
            'posthoc_multiple_E15_E16_head_comparisons_no_confirmatory_p_value':True,
        },
        'original_new_pretrained_forwards':0,
        'training_and_held_head_CPU_observed_only_not_full_service_cost':True,
        'e16_original_self_reported_head_cpu_ns':sum(v['train_cpu_ns']+v['held_cpu_ns']
                                                     for v in original['e16_observed_student_CPU_ns']),
        'independent_fresh_future_model_generalization_established':False,
        'cost_adjusted_inference_gain_established':False,
        'independent_original_human_signer_authenticated':False,
        'system2_inference_executed':False,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',required=True)
    for i in range(4):
        p.add_argument(f'--e15-{i}',required=True)
        p.add_argument(f'--e16-{i}',required=True)
    p.add_argument('--blind',required=True);p.add_argument('--validation',required=True)
    p.add_argument('--e15-source',required=True);p.add_argument('--e15-merge',required=True)
    p.add_argument('--e16-source',required=True);p.add_argument('--e16-merge',required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args()
    result=audit(a.original,
       [getattr(a,f'e15_{i}') for i in range(4)],
       [getattr(a,f'e16_{i}') for i in range(4)],
       a.blind,a.validation,[a.e15_source,a.e15_merge],[a.e16_source,a.e16_merge])
    print(once(a.out,result))

if __name__=='__main__':main()
