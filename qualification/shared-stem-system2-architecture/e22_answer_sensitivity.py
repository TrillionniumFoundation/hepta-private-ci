"""E22: original E21 Reader answer-information obstruction, research/DENY_ALL.

No new pretrained forward or full evidentiary perturbation. Original human
labels may enter only the separate post-seal scoring operation.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from e21_whole_question import SCHEMA, SOURCE_SHA, E15_HEAD, ALL, LEARNED, score_from_labels

SCHEMA_E22 = 'hepta.e22.e21-prelabel-answer-contrast.v1'
REVIEW_E22 = 'hepta.e22.original-human-answer-information.v1'


def deny(ok, why):
    if not ok:
        raise ValueError(why)


def encoded(obj):
    return (json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def read(path):
    p = Path(path)
    deny(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size < 2_000_000,
         'missing/unsafe bounded original research artifact')
    def pairs(xs):
        d = {}
        for key, value in xs:
            deny(key not in d, 'duplicate JSON member')
            d[key] = value
        return d
    return json.loads(p.read_bytes(), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def analyze(blind):
    deny(type(blind) is dict and set(blind) == {
        'schema','authority','production_accepted','source_archive_sha256',
        'e15_head','real_pretrained_forwards_new','held_human_labels_opened',
        'source_group_count','question_count','candidate_count','rows'}, 'E21 field drift')
    deny(blind['schema'] == SCHEMA and blind['authority'] == 'DENY_ALL' and
         blind['production_accepted'] is False and blind['held_human_labels_opened'] is False and
         blind['source_archive_sha256'] == SOURCE_SHA and blind['e15_head'] == E15_HEAD and
         type(blind['real_pretrained_forwards_new']) is int and
         blind['real_pretrained_forwards_new'] == 0 and
         (blind['source_group_count'],blind['question_count'],blind['candidate_count']) == (4,8,33),
         'unqualified E21 original prelabel source')
    rows = blind['rows']; deny(type(rows) is list and len(rows) == 33,'missing original answers')
    groups = defaultdict(list); seen = set()
    for r in rows:
        deny(type(r) is dict and set(r) == {
            'task_id','source_group','question_slot','candidate_id','original_v1_candidate','probs'},
            'answer source identity/label injection')
        deny(type(r['task_id']) is str and len(r['task_id']) == 32 and
             type(r['source_group']) is str and len(r['source_group']) == 32 and
             type(r['question_slot']) is int and r['question_slot'] in (0,1) and
             type(r['candidate_id']) is int and r['candidate_id'] >= 0 and
             type(r['original_v1_candidate']) is bool and r['task_id'] not in seen,
             'duplicated/invalid original answer identity')
        seen.add(r['task_id']); ps = r['probs']
        deny(type(ps) is dict and set(ps) == set(ALL) and
             all(type(v) in (float,int) and isfinite(v) and 0 < v < 1 for v in ps.values()),
             'invalid original Reader probabilities')
        groups[r['source_group'],r['question_slot']].append(r)
    deny(len(groups) == 8 and len({key[0] for key in groups}) == 4 and
         all((g,0) in groups and (g,1) in groups for g,_ in groups),
         'missing source passage/question')
    q = []
    for (g,k), slate in sorted(groups.items()):
        deny(2 <= len(slate) <= 8 and len({r['candidate_id'] for r in slate}) == len(slate) and
             sum(r['original_v1_candidate'] for r in slate) == 1 and
             next(r['candidate_id'] for r in slate if r['original_v1_candidate']) ==
             min(r['candidate_id'] for r in slate), 'altered original alternative slate')
        arms = {}
        for name in ALL:
            p = [r['probs'][name] for r in slate]
            threshold = [v >= .5 if name in LEARNED else v > .5 for v in p]
            arms[name] = {
                'exact_invariant': len(set(p)) == 1,
                'threshold_invariant': len(set(threshold)) == 1,
                'unequal_pairs': sum(a != b for i,a in enumerate(p) for b in p[i+1:]),
                'probability_span': max(p)-min(p),
            }
        q.append({'source_group':g,'question_slot':k,'candidate_count':len(slate),'arms':arms})
    return {'schema':SCHEMA_E22,'authority':'DENY_ALL','production_accepted':False,
            'system2_admitted':False,'model_selected':False,
            'source_e21_sha256':sha256(encoded(blind)).hexdigest(),
            'original_questions':8,'original_candidates':33,'questions':q,
            'fresh_model_forwards':0,'semantic_sufficiency_certified':False,
            'real_answer_swap_observed':False,'key_premise_ablation_observed':False}


def review(blind, sealed, labels, original_e21_review):
    deny(type(sealed) is dict and sealed == analyze(blind),
         'sealed label-blind prediction changed after submission')
    # E21 scorer also verifies all eight original questions have both human
    # truth classes, exact scores, and the 33/4/8 source-group census.
    truth = score_from_labels(blind, labels)
    deny(type(original_e21_review) is dict and
         original_e21_review.get('schema') ==
         'hepta.e21.original-human-question-level-review.v1' and
         original_e21_review.get('authority') == 'DENY_ALL' and
         original_e21_review.get('original_source_and_merge_scores_reconciled') is True,
         'missing independently reconciled original E21 human scorer')
    for name in ALL:
        prior = original_e21_review['method_results'][name]
        deny(truth[name]['correct'] == prior['correct'] and
             truth[name]['complete_question_count'] == prior['complete_question_count'],
             'original source-head/merge human scorer disagreement')
    methods = {}
    for name in ALL:
        exact = sum(q['arms'][name]['exact_invariant'] for q in sealed['questions'])
        hard = sum(q['arms'][name]['threshold_invariant'] for q in sealed['questions'])
        complete = truth[name]['complete_question_count']
        deny(complete <= 8-hard and complete <= 8-exact,
             'mixed-label question incorrectly completed by invariant readout')
        methods[name] = {'exact_invariant_questions':exact,
                         'fixed_threshold_invariant_questions':hard,
                         'complete_human_questions':complete,
                         'correct_human_candidates':truth[name]['correct']}
    return {'schema':REVIEW_E22,'authority':'DENY_ALL','production_accepted':False,
            'original_e21_independent_human_scores_reconciled':True,
            'models':methods,'system2_admitted':False,
            'evidence_ablation_forward_observed':False,
            'future_source_family_observed':False,'general_sufficiency_established':False,
            'cost_adjusted_learning_gain_established':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('blind','score'),required=True)
    p.add_argument('--e21-blind',type=Path,required=True)
    p.add_argument('--sha256',required=True)
    p.add_argument('--sealed',type=Path)
    p.add_argument('--validation',type=Path)
    p.add_argument('--e21-review',type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    deny(not a.out.exists() and not a.out.is_symlink(),'output must be create-once')
    raw=a.e21_blind.read_bytes()
    deny(0 < len(raw) <= 2_000_000 and sha256(raw).hexdigest() == a.sha256,
         'source publisher E21 prelabel SHA mismatch')
    blind=read(a.e21_blind)
    if a.mode == 'blind':
        deny(a.validation is None and a.sealed is None and a.e21_review is None,
             'pre-label stage may not see human labels or scorer')
        result=analyze(blind)
    else:
        deny(a.validation is not None and a.sealed is not None and
             a.e21_review is not None, 'complete second-stage original material required')
        raw_val=a.validation.read_bytes()
        from e21_whole_question import VAL_SHA
        deny(0 < len(raw_val) < 1_000_000 and sha256(raw_val).hexdigest() == VAL_SHA,
             'original human source material not pinned')
        import pyarrow.parquet as pq  # NEVER imported in the blind producer
        from e14_multirc_score import original_labels
        ids=[{k:r[k] for k in ('task_id','source_group','question_slot',
             'candidate_id','original_v1_candidate')} for r in blind['rows']]
        source=pq.read_table(a.validation,columns=[
            'paragraph','question','answer','label','idx']).to_pylist()
        labels=original_labels(source,ids)
        result=review(blind,read(a.sealed),labels,read(a.e21_review))
    with a.out.open('xb') as f:f.write(encoded(result))
    print('E22_SOURCE_BOUND / RESEARCH / DENY_ALL / NO_NEW_MODEL_FORWARD')


if __name__=='__main__': main()
