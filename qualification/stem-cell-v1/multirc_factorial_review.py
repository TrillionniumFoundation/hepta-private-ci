"""Strictly label-blind per-passage review of a *sealed* MultiRC factorial.

Only the original probability movements are compared. Crossed questions and
candidate answers have no verified labels; this module never trains, selects a
winner, estimates statistical significance or manufactures accuracy.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from multirc_query_factorial import SCHEMA, INSENSITIVITY_PROBE_EPSILON, _verified_original_stress
from multirc_reader_study import check_seal
from next_round_matrix import _digest

FACTORS = ('abs_change_question_only', 'abs_change_answer_only',
           'abs_change_question_and_answer')
REVIEW_SCHEMA = 'hepta.multirc.factorial-descriptive-review.v2'
SEAL_SCHEMA = 'hepta.multirc.factorial-descriptive-review-seal.v1'


def _sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(ch in '0123456789abcdef' for ch in value))


def _finite_probability(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _validate_report(report, *, expected_factorial_id):
    if (not isinstance(report, dict) or report.get('schema') != SCHEMA
            or report.get('factorial_id') != expected_factorial_id
            or not _sha(expected_factorial_id)
            or _digest({k: v for k, v in report.items() if k != 'factorial_id'}) != expected_factorial_id):
        raise ValueError('exact sealed factorial observation required')
    for field in ('source_observation_id', 'source_panel_id', 'source_snapshot_sha256',
                  'trained_reader_weights_sha256', 'related_blinded_stress_id'):
        if not _sha(report.get(field)):
            raise ValueError(f'missing source identity: {field}')
    n, q = report.get('passage_count'), report.get('question_count')
    if (type(n) is not int or not 1 <= n <= 128 or type(q) is not int or q != 2*n
            or type(report.get('physical_encoder_calls')) is not int
            or report['physical_encoder_calls'] != n
            or type(report.get('newly_computed_question_embeddings')) is not int
            or report['newly_computed_question_embeddings'] != 4*n
            or type(report.get('conditioned_reader_calls')) is not int
            or report['conditioned_reader_calls'] != 4*n):
        raise ValueError('incomplete physically executed factorial inventory')
    epsilon = report.get('insensitive_epsilon')
    if type(epsilon) not in (int, float) or epsilon != INSENSITIVITY_PROBE_EPSILON:
        raise ValueError('registered descriptive epsilon changed')
    if (report.get('counterfactual_accuracy') is not None
            or report.get('cross_question_answer_combinations_have_no_valid_labels') is not True
            or report.get('independent_question_understanding_established') is not False
            or report.get('statistical_superiority_established') is not False
            or report.get('native_or_production_authorized') is not False
            or report.get('work_separate_from_original_inference') is not True):
        raise ValueError('unqualified counterfactual or production claims')
    work = report.get('work_observation')
    if (not isinstance(work, dict) or work.get('schema') != 'hepta.execution-work-observation.v1'
            or work.get('unknown_operators') != {} or work.get('stopped') is not None
            or type(work.get('phase_flops', {}).get('inference')) is not int
            or work['phase_flops']['inference'] < 0):
        raise ValueError('unknown or incomplete measured intervention cost')
    rows = report.get('records')
    if not isinstance(rows, list) or len(rows) != q:
        raise ValueError('incomplete paired question inventory')
    groups, seen, seen_ids = {}, set(), set()
    sums = {factor: 0.0 for factor in FACTORS}
    counts = {factor: 0 for factor in FACTORS}
    for row in rows:
        if (not isinstance(row, dict)
                or set(row) != {'task_id', 'source_group', 'question_slot',
                                'positive_probability_original', *FACTORS}
                or type(row.get('question_slot')) is not int
                or row['question_slot'] not in (0, 1)
                or not isinstance(row.get('task_id'), str) or not row['task_id']
                or len(row['task_id']) > 256
                or not isinstance(row.get('source_group'), str) or not row['source_group']
                or len(row['source_group']) > 256
                or not _finite_probability(row.get('positive_probability_original'))):
            raise ValueError('invalid typed, label-free intervention row')
        key = (row['source_group'], row['question_slot'])
        if key in seen or row['task_id'] in seen_ids:
            raise ValueError('duplicate source, slot or task identity')
        seen.add(key)
        seen_ids.add(row['task_id'])
        group = groups.setdefault(row['source_group'], [])
        group.append(row)
        for factor in FACTORS:
            if not _finite_probability(row.get(factor)):
                raise ValueError('invalid/nonfinite probability movement')
            sums[factor] += row[factor]
            counts[factor] += int(row[factor] <= epsilon)
    if (len(groups) != n or any(len(pair) != 2 or
            {row['question_slot'] for row in pair} != {0, 1} for pair in groups.values())):
        raise ValueError('source group missing or duplicated question')
    means = report.get('mean_absolute_positive_probability_change')
    registered = report.get('insensitive_question_counts')
    if (not isinstance(means, dict) or set(means) != set(FACTORS)
            or not isinstance(registered, dict) or set(registered) != set(FACTORS)):
        raise ValueError('registered population aggregates missing')
    for factor in FACTORS:
        if (not _finite_probability(means[factor])
                or abs(means[factor] - sums[factor] / q) > 1e-12
                or type(registered[factor]) is not int
                or registered[factor] != counts[factor]):
            raise ValueError('factorial aggregate contradicts individual questions')
    return groups, epsilon


def review_factorial(report, *, expected_factorial_id, epsilon=None):
    """Review descriptive effects only; epsilon MUST equal original locked value."""
    # Audit uses the original report's preregistered descriptive threshold.
    # Do not allow shifting a threshold after seeing which rows were insensitive.
    groups, locked = _validate_report(report, expected_factorial_id=expected_factorial_id)
    if epsilon is not None and (type(epsilon) not in (float, int)
                                or not math.isfinite(epsilon) or epsilon != locked):
        raise ValueError('posthoc change to registered epsilon refused')
    outputs = []
    for group in sorted(groups):
        pair = groups[group]
        means = {factor: sum(row[factor] for row in pair) / 2 for factor in FACTORS}
        question_count = sum(row[FACTORS[0]] <= locked for row in pair)
        answer_count = sum(row[FACTORS[1]] <= locked for row in pair)
        both_count = sum(row[FACTORS[0]] <= locked and row[FACTORS[1]] <= locked for row in pair)
        outputs.append(dict(source_group=group, question_count=2,
            mean_absolute_probability_shifts=means,
            insensitive_to_question=question_count, insensitive_to_answer=answer_count,
            insensitive_to_both=both_count))
    result = dict(schema=REVIEW_SCHEMA, source_factorial_id=expected_factorial_id,
        original_source_observation_id=report['source_observation_id'],
        original_source_panel_id=report['source_panel_id'], epsilon=locked,
        passage_count=len(outputs), question_count=len(report['records']),
        by_passage=outputs,
        double_insensitive_question_count=sum(row['insensitive_to_both'] for row in outputs),
        registered_original_factor_means=dict(report['mean_absolute_positive_probability_change']),
        separately_metered_inference_formula_work=report['work_observation']['phase_flops']['inference'],
        crossed_question_answer_labels_available=False, answer_accuracy=None,
        independence_of_passages_certified=False, statistical_superiority_established=False,
        interaction_sign_identifiable_from_absolute_changes=False,
        question_understanding_established=False, production_authorized=False)
    result['review_id'] = _digest(result)
    return result


def read_exact_factorial(folder, *, expected_factorial_seal_id,
                         owner_dir, expected_owner_seal_id,
                         stress_dir, expected_stress_seal_id):
    """Independently bind bytes and all three owners before reading any labels."""
    root = Path(folder)
    if (root / 'FAILED.json').exists() or (root / 'COMMITTED.json').is_symlink() or \
            (root / 'factorial.json').is_symlink():
        raise ValueError('failed or symlinked factorial evidence refused')
    seal = strict_json(root / 'COMMITTED.json')
    if (not _sha(expected_factorial_seal_id)
            or seal.get('seal_id') != expected_factorial_seal_id
            or _digest({k: v for k, v in seal.items() if k != 'seal_id'}) != expected_factorial_seal_id
            or seal.get('schema') != 'hepta.multirc.blind-factorial-seal.v1'
            or seal.get('owner_prediction_seal') != expected_owner_seal_id
            or seal.get('source_stress_seal') != expected_stress_seal_id
            or seal.get('externally_labeled_answers_used') is not False
            or seal.get('weights_uploaded') is not False
            or seal.get('production_authorized') is not False
            or file_sha256(root / 'factorial.json') != seal.get('factorial_sha256')):
        raise ValueError('factorial seal/external provenance/hash mismatch')
    original = strict_json(root / 'factorial.json')
    if original.get('factorial_id') != seal.get('factorial_id'):
        raise ValueError('factorial content does not match seal')
    owner = check_seal(owner_dir, expected_owner_seal_id)
    stress = _verified_original_stress(stress_dir, expected_stress_seal_id)
    if (original.get('source_observation_id') != owner.get('observation_id')
            or original.get('source_panel_id') != owner.get('panel_id')
            or original.get('source_snapshot_sha256') != owner.get('model_snapshot_sha256')
            or original.get('trained_reader_weights_sha256') != owner['training']['conditioned']['weights_sha256']
            or original.get('related_blinded_stress_id') != stress.get('stress_id')
            or stress.get('source_observation_id') != owner.get('observation_id')):
        raise ValueError('factorial input provenance does not match original owners')
    # Original question-order and source attribution are checked from the true
    # prediction seal rather than inferred from only the factorial aggregate.
    pred = owner['predictions']['conditioned']
    if [(r['task_id'], r['source_group']) for r in original['records']] != [
            (r['task_id'], r['source_group']) for r in pred]:
        raise ValueError('factorial question/source sequence differs from sealed model')
    return original


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('factorial-dir', 'expected-factorial-seal-id', 'owner-dir',
                'expected-owner-seal-id', 'stress-dir', 'expected-stress-seal-id', 'output'):
        p.add_argument('--' + key, required=True)
    args = p.parse_args()
    target = Path(args.output)
    target.mkdir(exist_ok=False)
    try:
        original = read_exact_factorial(args.factorial_dir,
            expected_factorial_seal_id=args.expected_factorial_seal_id,
            owner_dir=args.owner_dir, expected_owner_seal_id=args.expected_owner_seal_id,
            stress_dir=args.stress_dir, expected_stress_seal_id=args.expected_stress_seal_id)
        result = review_factorial(original, expected_factorial_id=original['factorial_id'])
        write_json_exclusive(target / 'review.json', result)
        seal = dict(schema=SEAL_SCHEMA, source_factorial_seal=args.expected_factorial_seal_id,
            source_prediction_seal=args.expected_owner_seal_id,
            source_stress_seal=args.expected_stress_seal_id, review_id=result['review_id'],
            review_sha256=file_sha256(target / 'review.json'),
            external_labels_loaded=False, statistical_superiority_established=False,
            production_authorized=False)
        seal['seal_id'] = _digest(seal)
        write_json_exclusive(target / 'COMMITTED.json', seal)
        print(json.dumps(dict(review_id=result['review_id'], seal_id=seal['seal_id'],
                              production_authorized=False), sort_keys=True))
    except Exception as exc:
        write_json_exclusive(target / 'FAILED.json', dict(
            schema='hepta.multirc.factorial-descriptive-review-failed.v1',
            error_type=type(exc).__name__, production_authorized=False))
        raise


if __name__ == '__main__':
    main()
