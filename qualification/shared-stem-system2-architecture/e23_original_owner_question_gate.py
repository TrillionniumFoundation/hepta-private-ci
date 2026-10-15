"""E23: independently audit complete ORIGINAL MultiRC questions from two prior owner receipts.

Original test-score labels are opened ONLY by this post-seal verifier.  Each of
E15 and E16's four different owner artifacts excludes a different held passage;
three-fold union reconstructs each label three times. Both owner jobs were
independently scheduled but derived from the SAME original human annotation
file: this is corroboration, NOT independent human adjudication, nor a new
future-time test. No learner sees the union. DENY_ALL.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from math import isclose
from pathlib import Path
import json

from e14_multirc_route import read_prelabel
from e15_reader_crossfit import verify_train
from e15_independent_score import independently_fit, independent_features, sha as material_digest
from e16_independent_score import separate_geometry, fit_independent, probability as independent_e16_p
from e21_whole_question import _zip, _json_bytes, E15_SCORES, signflip_p
from e22_e16_question_gate import E16_FOLDS, blind_e22, ALL, E16_METHODS
from e22_independent_human_score import E16_SCORES, question_metrics

SCHEMA = 'hepta.e23.two-original-label-owners-complete-question-verification.v1'
VAL_SHA = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
# Action uploads on two distinct original owner runs: E15 38681145276 and
# E16 38682359793. Outer ZIP bytes, not just claimed material hash, are pinned.
E15_OWNERS = (
    (11949081037, 'cc1c13323cb8377cbd5cdfa5c806796cb85505746e8509f21432d83a1ac4fb2d'),
    (11948881417, '8aa9f4b82a4478e9329cba5468adbea4a5a75bd9707b57358eb78a981cf0fd5e'),
    (11948806536, 'e097d3a3bd210c1b8a84736cc6c219ea2605763c5b83b2c823dd136c00dedec5'),
    (11948681555, '8565aa2c841ad067d58e9ca04222247277de509bb4bdac38eb42e7662d13c6b2'),
)
E16_OWNERS = (
    (11949305579, 'cb303e78cbbb1c9db400591e8a372609766a91213ddbdd323acd119ae1afb976'),
    (11949100961, 'd17c501eb02709ede687c72e7f5c6d6a32e776d365e7f1bbd01ec4587048d4f5'),
    (11949680463, '06c0e9abec8d28d09e5b9e6640bfb806b0d5759916d08ed8301620038de31794'),
    (11949670424, '85f304240802952b5d2909e73e4548aef23073eb348b43c33d19e1cb106ea5f8'),
)


def original_owner_labels(obs: dict, owner_zips: list[str], inventory: tuple, *, name: str):
    """Return labels only after all four exact train-only artifacts are present.

    No original validation parquet is needed here: all 33 labels appear in
    each owner's 4-fold train-3/held-1 material exactly THREE times. This
    reconstruction must NEVER be callable in a blind learner job.
    """
    if type(owner_zips) is not list or len(owner_zips) != 4 or len(inventory) != 4:
        raise ValueError('four original training-label owner ZIPs required')
    values = defaultdict(list)
    seen_groups = set()
    bytes_sha = []
    for fold, (path, (artifact_id, outer_sha)) in enumerate(zip(owner_zips, inventory, strict=True)):
        raw = Path(path).read_bytes()
        if not 0 < len(raw) < 20000 or sha256(raw).hexdigest() != outer_sha:
            raise ValueError('original material owner archive bytes not pinned')
        parts = _zip(path, outer_sha, (f'training-fold-{fold}.json',))
        original = _json_bytes(parts[f'training-fold-{fold}.json'])
        if type(original) is not dict or original.get('schema') != 'hepta.e15.owner-training-only-passage-fold.v1':
            raise ValueError('original human label owner schema mismatch')
        verified = verify_train(obs, original)
        if (original.get('original_validation_human_label_source_sha256') != VAL_SHA
                or original.get('authority') != 'DENY_ALL'
                or original.get('held_labels_exposed') is not False
                or original.get('production_accepted') is not False
                or original.get('fold') != fold
                or original.get('held_group') in seen_groups):
            raise ValueError('original held group identity/label boundary changed')
        seen_groups.add(original['held_group'])
        for task, label in verified.items():
            if type(label) is not int or label not in (0, 1):
                raise ValueError('original task label invalid')
            values[task].append(label)
        bytes_sha.append(sha256(raw).hexdigest())
    expected = {r['task_id'] for r in obs['rows']}
    if len(seen_groups) != 4 or set(values) != expected or len(values) != 33:
        raise ValueError('training owner unable to recover all original held labels')
    if any(len(v) != 3 or len(set(v)) != 1 for v in values.values()):
        raise ValueError('original labels must agree across three independent train views')
    return {task: votes[0] for task, votes in values.items()}, {
        'owner': name, 'original_hosted_zip_artifact_ids': [id for id, _ in inventory],
        'original_zip_sha256': bytes_sha,
        'complete_original_labels': 33, 'independent_owner_runs_not_independent_human_adjudicators': True,
        'each_label_has_three_consistent_training_only_views': True,
    }


def original_human_score_receipts(paths: list[str], registered, expected_schema, filename,
                                  original_head, methods, original_metrics):
    """Verify both *previously hosted original human score* documents byte-for-byte."""
    if type(paths) is not list or len(paths) != 2:
        raise ValueError('both previous source/synthetic original score receipts required')
    hashes = []
    for path, (_, original_zip_sha, expected_head) in zip(paths, registered, strict=True):
        p = _zip(path, original_zip_sha, (filename, 'score.sha256', 'source-head.txt'))
        raw = p[filename]
        if (sha256(raw).hexdigest() != p['score.sha256'].decode().strip().split()[0]
                or p['source-head.txt'].decode().strip() != expected_head):
            raise ValueError('previous original human score seal or source HEAD changed')
        obj = _json_bytes(raw)
        if (obj.get('schema') != expected_schema or obj.get('authority') != 'DENY_ALL'
                or obj.get('production_accepted') is not False):
            raise ValueError('original human score source not qualified')
        score = obj['summary'] if filename.startswith('original-human-e15-') else obj['results']
        for method in methods:
            a = score[method]
            b = original_metrics[method]
            if (type(a.get('correct')) is not int or a['correct'] != b['correct']
                    or not isclose(a['brier'], b['brier'], rel_tol=0., abs_tol=2e-12)):
                raise ValueError('original hosted human score disagrees with reconstructed original labels')
            own = a['passage_correct'] if filename.startswith('original-human-e15-') else a['source_passage_correct']
            if own != b['passage_correct']:
                raise ValueError('historical original source group correct count differs')
        hashes.append(sha256(raw).hexdigest())
    return hashes


def check_e16_true_label_parameter_replay(original_archive: str, owner_labels: dict,
                                          e16_fold_zips: list[str]):
    """Independent reference repeats actual 48-step E16 SGD on ORIGINAL training labels."""
    if type(e16_fold_zips) is not list or len(e16_fold_zips) != 4:
        raise ValueError('all four E16 held predictions required')
    obs = read_prelabel(original_archive)
    source = separate_geometry(obs)
    groups = sorted({r['group'] for r in source})
    if len(groups) != 4 or len(source) != 33:
        raise ValueError('source geometry changed')
    verified_predictions = set()
    for fold, (path, (_, outer, inside)) in enumerate(zip(e16_fold_zips, E16_FOLDS, strict=True)):
        raw = _zip(path, outer, ('held-prediction.json',))['held-prediction.json']
        if sha256(raw).hexdigest() != inside:
            raise ValueError('E16 held predictions fail source SHA')
        rec = _json_bytes(raw)
        held = [r for r in source if r['group'] == groups[fold]]
        training = {r['task_id']: owner_labels[r['task_id']]
                    for r in source if r['group'] != groups[fold]}
        if (rec.get('held_group') != groups[fold] or rec.get('fold') != fold
                or rec.get('held_human_labels_accessed') is not False
                or rec.get('production_accepted') is not False
                or len(rec.get('predictions', [])) != len(held)):
            raise ValueError('E16 original prediction fold invalid')
        for method in E16_METHODS:
            weights, scaling, _ = fit_independent(source, training, method)
            claimed = rec['weights'][method]
            if (type(claimed) is not list or len(claimed) != 5
                    or any(type(c) is not float or abs(a-c)>2e-12
                           for a, c in zip(weights, claimed, strict=True))):
                raise ValueError('E16 independent true-label head parameter replay differs')
            if (type(rec['train_only_scaling']) is not list
                    or any(abs(a-b)>1e-13 for a,b in zip(scaling,rec['train_only_scaling'],strict=True))):
                raise ValueError('E16 train-only normalization replay differs')
        for actual, pred in zip(held, rec['predictions'], strict=True):
            if (pred.get('task_id') != actual['task_id']
                    or pred.get('source_group') != groups[fold]
                    or pred['task_id'] in verified_predictions):
                raise ValueError('incomplete or duplicated E16 prediction')
            verified_predictions.add(actual['task_id'])
            for method in E16_METHODS:
                value = independent_e16_p(actual, method, rec['weights'][method], rec['train_only_scaling'])
                if (not isclose(value, pred['probabilities'][method], rel_tol=0., abs_tol=2e-12)):
                    raise ValueError('E16 original human-trained prediction is forged')
    if verified_predictions != set(owner_labels):
        raise ValueError('not all original labels have a scored E16 out-of-group prediction')
    return {'four_real_training_folds_independently_recomputed': True,
            'forty_eight_sgd_updates_per_head_per_fold': True,
            'future_source_family_generalization_established': False}


def audit(original_archive: str, e15_held: list[str], e16_held: list[str],
          original_blind_path: str, e15_owner: list[str], e16_owner: list[str],
          e15_scores: list[str], e16_scores: list[str]):
    """Complete original-human audit, never execute before original blind SHA seal."""
    bytes_blind = Path(original_blind_path).read_bytes()
    if not 0 < len(bytes_blind) <= 100000:
        raise ValueError('invalid create-only blind input')
    blind = _json_bytes(bytes_blind)
    recreated = blind_e22(original_archive, e15_held, e16_held)
    if blind != recreated:
        raise ValueError('historical original blind prediction changed even if re-signed')
    obs = read_prelabel(original_archive)
    a, a_proof = original_owner_labels(obs,e15_owner,E15_OWNERS,name='E15 original human owner')
    b, b_proof = original_owner_labels(obs,e16_owner,E16_OWNERS,name='E16 original human owner')
    if a != b:
        raise ValueError('independent original CI material owners disagree on human labels')
    metrics = question_metrics(blind,a)
    e15_hashes = original_human_score_receipts(e15_scores, E15_SCORES,
        'hepta.e15.independent-original-human-lopo-head-score.v1',
        'original-human-e15-lopo-result.json','E15', ALL[:6], metrics)
    e16_hashes = original_human_score_receipts(e16_scores, E16_SCORES,
        'hepta.e16.independent-human-lopo-answer-centered.v1',
        'original-human-e16-centered-result.json','E16', ALL, metrics)
    retrain = check_e16_true_label_parameter_replay(original_archive,a,e16_held)
    ref = metrics['mean_pool_query_fused']
    alt = metrics['centered_scaled_5']
    groups=sorted(ref['passage_correct'])
    deltas=[alt['passage_correct'][g]-ref['passage_correct'][g] for g in groups]
    q_deltas=[alt['question_success'][k]-ref['question_success'][k]
              for k in sorted(ref['question_success'])]
    if (ref['correct'] != 17 or alt['correct'] != 20
            or (ref['complete_original_questions'], alt['complete_original_questions']) != (0,0)
            or (ref['complete_original_passages'], alt['complete_original_passages']) != (0,0)
            or sorted(deltas) != [0,0,0,3]
            or sum(q_deltas) != 0):
        raise ValueError('original historic learning outcome changed unexpectedly')
    return {
       'schema': SCHEMA, 'authority': 'DENY_ALL',
       'production_accepted': False, 'model_selected': False,
       'system2_fbsde_admitted': False, 'cost_adjusted_task_improvement_established': False,
       'source_blind_sha256':sha256(bytes_blind).hexdigest(),
       'human_validation_parquet_sha256_declared_by_two_original_owner_runs':VAL_SHA,
       'original_pretrained_forwards_executed_now':0,
       'original_source_families':1,'original_passage_groups':4,'original_questions':8,
       'original_human_candidates':33,
       'two_original_owner_evidence_sets':[a_proof,b_proof],
       'same_33_labels_reconstructed_from_two_original_owner_receipts': True,
       'original_human_source_parquet_re_downloaded_in_this_run':False,
       'both_original_e15_score_sha256s':e15_hashes,
       'both_original_e16_score_sha256s':e16_hashes,
       'e16_original_three_group_label_independent_sgd_replay':retrain,
       'eight_strategy_original_human_question_metrics':metrics,
       'e16_scaled_vs_frozen_mean_pool':{
          'candidate_correct_delta':3, 'brier_delta':alt['brier']-ref['brier'],
          'passage_correct_deltas':deltas,'complete_question_delta':0,
          'four_passage_exact_signflip_p_descriptive_only':signflip_p(deltas),
          'prospective_multi_hypothesis_p_value':None,
          'source_family_generalization_established':False,
       },
       'actual_original_human_full_questions_success_by_any_registered_method':False,
       'every_method_complete_question_count':{k:v['complete_original_questions'] for k,v in metrics.items()},
       'original_owner_artifact_sets_do_not_prove_independent_human_adjudication':True,
       'original_process_label_isolation_not_cryptographic_secrecy':True,
       'whole_service_costs_independently_measured':False,
       'independent_future_generation_gains_established':False,
    }


def main():
    import argparse
    from e21_whole_question import once
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',required=True)
    p.add_argument('--blind',required=True)
    for i in range(4):
        for key in ('e15-fold','e16-fold','e15-owner','e16-owner'):
            p.add_argument('--'+key+'-'+str(i),required=True)
    for key in ('e15-score-source','e15-score-merge','e16-score-source','e16-score-merge'):
        p.add_argument('--'+key,required=True)
    p.add_argument('--output',required=True)
    x=p.parse_args()
    value=audit(x.original,
        [getattr(x,f'e15_fold_{i}') for i in range(4)],
        [getattr(x,f'e16_fold_{i}') for i in range(4)],
        x.blind,
        [getattr(x,f'e15_owner_{i}') for i in range(4)],
        [getattr(x,f'e16_owner_{i}') for i in range(4)],
        [x.e15_score_source,x.e15_score_merge],
        [x.e16_score_source,x.e16_score_merge])
    print(once(x.output,value),'DENY_ALL')

if __name__ == '__main__': main()
