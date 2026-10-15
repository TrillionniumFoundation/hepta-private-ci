#!/usr/bin/env python3
"""E23 original archived E14/E15 human-mixed-label + E22 real blind obstruction.

Conditional upper bounds on unchanged binary Reader predictions; NOT a new
human-label re-score, new training, NDU execution, or production authority.
Exact score invariance has a SEPARATE deterministic-score-only interpretation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from zipfile import ZipFile

import e22_answer_discrimination as e22

SCHEMA = 'hepta.e23.original-human-mixed-question-hardclass-bound.v1'
ORIGINAL = e22.SOURCE_SHA
VAL = e22.VAL_SHA
ZIP_PINS = (
    ('e14', 'efd3525b6c412b1681333b1f1185a6879973ae93340b12f786139eb45a3ff0f4'),
    ('e15_source', 'f332ab92181a0e088d941dbf4c77165ab2e4c40e48e9bbda4915e8d1543aceb8'),
    ('e15_merge', '63da90cb7da7f2f6ef478e44731e548a62a4b3c1a071593864f23b5896290acc'),
)


class CertificateDenied(ValueError):
    """Insufficient original evidence, no certificate."""


def need(ok: bool, message: str) -> None:
    if not ok:
        raise CertificateDenied(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unpack(p: Path, expected_outer: str, member: str, checksum: str) -> dict:
    need(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= 4_000_000,
         'invalid original archive')
    need(sha(p.read_bytes()) == expected_outer, 'original archive digest changed')
    with ZipFile(p) as z:
        infos = z.infolist()
        need(0 < len(infos) <= 30 and
             len({i.filename for i in infos}) == len(infos) and
             all(i.file_size <= 1_000_000 and not i.filename.startswith('/') and
                 '..' not in i.filename.split('/') for i in infos),
             'unsafe or ambiguous original ZIP')
        need(member in z.namelist() and checksum in z.namelist(),
             'missing authenticated original score')
        raw = z.read(member)
        declared = z.read(checksum).decode('utf8').strip().split()[0]
        need(sha(raw) == declared, 'original score inner SHA mismatch')
    try:
        result = e22.strict_json(raw)
    except e22.EvidenceDenied as exc:
        raise CertificateDenied('invalid original score JSON') from exc
    need(type(result) is dict, 'malformed score object')
    return result


def authenticate_receipts(e14_path: Path, e15_source_path: Path,
                          e15_merge_path: Path) -> tuple[dict, dict, dict]:
    e14 = unpack(e14_path, ZIP_PINS[0][1],
                 'independent-original-human-e14-score.json', 'score.sha256')
    e15s = unpack(e15_source_path, ZIP_PINS[1][1],
                  'original-human-e15-lopo-result.json', 'score.sha256')
    e15m = unpack(e15_merge_path, ZIP_PINS[2][1],
                  'original-human-e15-lopo-result.json', 'score.sha256')
    need(e14.get('schema') == 'hepta.e14.independent-original-multirc-task-control.v1' and
         e14.get('authority') == 'DENY_ALL' and e14.get('production_accepted') is False and
         e14.get('all_questions_mixed_original_labels') is True and
         (e14.get('questions'), e14.get('passages'),
          e14.get('original_human_annotation_candidate_count')) == (8, 4, 33) and
         e14.get('human_validation_sha256') == VAL and
         e14.get('original_archive_sha256') == ORIGINAL and
         e14.get('new_pretrained_model_calls') == 0,
         'not original independently scored E14 human mixed-label witness')
    for candidate in (e15s, e15m):
        need(candidate.get('schema') == 'hepta.e15.independent-original-human-lopo-head-score.v1' and
             candidate.get('authority') == 'DENY_ALL' and
             candidate.get('production_accepted') is False and
             candidate.get('source_archive_sha256') == ORIGINAL and
             candidate.get('human_validation_sha256') == VAL and
             candidate.get('original_human_label_mixed_question_count') == 8 and
             candidate.get('original_question_count') == 8 and
             candidate.get('original_passage_groups') == 4 and
             candidate.get('original_candidate_count') == 33 and
             candidate.get('independent_future_generations_established') is False and
             candidate.get('trained_cell_head_production_admitted') is False and
             candidate.get('source_group_independence_and_statistical_power_not_established') is True and
             candidate.get('model_forwards_new') == 0,
             'E15 original human score or mixed-label census invalid')
        folds = candidate.get('fold_receipts')
        need(type(folds) is list and len(folds) == 4 and
             sorted(f['fold'] for f in folds) == [0, 1, 2, 3] and
             sorted(f['held_count'] for f in folds) == [6, 8, 9, 10] and
             all(f.get('learned_weight_replay') is True for f in folds),
             'original four trained E15 folds not independently attested')
        methods = candidate.get('summary')
        need(type(methods) is dict and set(methods) == set(e22.ALL),
             'original six-model human score incomplete')
        for arm, v in methods.items():
            need(type(v) is dict and type(v.get('correct')) is int and
                 type(v.get('total')) is int and v['total'] == 33 and
                 type(v.get('brier')) in (float, int) and math.isfinite(v['brier']) and
                 sum(v['passage_correct'].values()) == v['correct'] and
                 sum(v['passage_total'].values()) == 33,
                 'invalid original human score arithmetic')
    for arm in e22.ALL:
        ss, mm = e15s['summary'][arm], e15m['summary'][arm]
        need(ss['correct'] == mm['correct'] and
             ss['passage_correct'] == mm['passage_correct'] and
             ss['passage_total'] == mm['passage_total'] and
             abs(ss['brier'] - mm['brier']) < 1e-12,
             'two original human E15 reviewers disagree')
        if arm in e22.FROZEN:
            v = e14['evaluation_arms'][arm]
            need(v['correct'] == ss['correct'] and abs(v['brier'] - ss['brier']) < 1e-12,
                 'E14 and E15 original frozen human scores disagree')
    return e14, e15s, e15m


def certify(blind: dict, e14: dict, e15_source: dict, e15_merge: dict) -> dict:
    try:
        questions = e22.check_original_blind(blind)
    except e22.EvidenceDenied as exc:
        raise CertificateDenied('unqualified original E21 blind output') from exc
    need(e14['all_questions_mixed_original_labels'] is True and
         e15_source['original_human_label_mixed_question_count'] == 8 and
         e15_merge['original_human_label_mixed_question_count'] == 8,
         'human mixed-question witness invalid')
    sorted_questions = sorted(questions.items(), key=lambda kv: str(kv[0]))
    results = {}
    for arm in e22.ALL:
        hard_constant, score_constant = 0, 0
        passages_obstructed = set()
        question_results = []
        for (source, question), rows in sorted_questions:
            probabilities = [r['probs'][arm] for r in rows]
            flat = len(set(probabilities)) == 1
            oneclass = len({e22.hard_class(arm, p) for p in probabilities}) == 1
            hard_constant += int(oneclass)
            score_constant += int(flat)
            if oneclass:
                passages_obstructed.add(source)
            question_results.append({
                'source_group': source, 'question_slot': question,
                'binary_hard_class_constant': oneclass, 'exact_single_score': flat,
            })
        results[arm] = {
            'questions_constant_binary_prediction': hard_constant,
            'questions_exactly_constant_full_probability': score_constant,
            'current_unmodified_binary_policy_max_complete_questions': 8 - hard_constant,
            'current_unmodified_binary_policy_max_complete_passages': 4 - len(passages_obstructed),
            'deterministic_reclassifier_using_only_exact_score_max_complete_questions': 8 - score_constant,
            'historical_original_human_candidate_correct': e15_source['summary'][arm]['correct'],
            'historical_original_human_candidate_total': 33,
            'per_question': question_results,
        }
    need(results['no_query']['questions_exactly_constant_full_probability'] == 8 and
         results['conditioned']['questions_exactly_constant_full_probability'] == 4 and
         all(results[a]['current_unmodified_binary_policy_max_complete_questions'] == 0
             for a in ('conditioned', 'mean_pool_query_fused', 'no_query',
                       'learned_linear_5', 'learned_gated_3')) and
         results['no_evidence']['current_unmodified_binary_policy_max_complete_questions'] <= 1,
         'unexpected original pretrained answer geometry')
    return {
        'schema': SCHEMA, 'original_pretrained_source_sha256': ORIGINAL,
        'original_human_validation_sha256': VAL,
        'e14_original_zip_sha256': ZIP_PINS[0][1],
        'e15_source_original_zip_sha256': ZIP_PINS[1][1],
        'e15_merge_original_zip_sha256': ZIP_PINS[2][1],
        'source_passage_groups': 4, 'mixed_label_questions_per_original_human_receipts': 8,
        'candidate_count': 33, 'original_reader_arms': list(e22.ALL),
        'reader_obstruction_conditional_on_original_human_receipt_truth': True,
        'human_label_parquet_reopened_here': False,
        'whole_question_original_human_score_recomputed_here': False,
        'score_based_impossibility_is_only_for_exactly_invariant_scores': True,
        'hard_class_limit_applies_only_to_unchanged_inference_policy': True,
        'historical_issuer_and_host_signatures_newly_verified': False,
        'no_new_pretrained_forward_or_head_training': True,
        'external_source_and_future_groups_validated': False,
        'new_10t_100t_equivalence_certified': False,
        'reader_information_sufficiency_accepted': False,
        'full_NDU_system2_admitted': False, 'production_accepted': False,
        'authority_posture': 'DENY_ALL', 'arm_upper_bounds': results,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--e21-blind', type=Path, required=True)
    p.add_argument('--e14-original-score-zip', type=Path, required=True)
    p.add_argument('--e15-source-score-zip', type=Path, required=True)
    p.add_argument('--e15-merge-score-zip', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    _, blind = e22.load(args.e21_blind)
    h, s, m = authenticate_receipts(args.e14_original_score_zip,
                                     args.e15_source_score_zip,
                                     args.e15_merge_score_zip)
    print(e22.emit_once(args.output, certify(blind, h, s, m)))


if __name__ == '__main__':
    main()
