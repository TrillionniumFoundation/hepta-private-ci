"""Independent E16 original-human scorer, re-derives all centered SGD weights.

The blinded training job never loads human held truth; this separate job
fetches labels only AFTER all four fold predictions have been sealed.
It uses an independent centering, optimizer, and predictor implementation.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from math import exp, isclose, isfinite
from pathlib import Path
from time import process_time_ns

from e14_multirc_route import read_prelabel, strict_json, write_once, ARMS, ARCHIVE_SHA, OBS_ID
from e14_multirc_score import read_validation, original_labels, historical_owner_score, VAL_SHA
from e15_independent_score import (independent_features, independently_fit,
                                   independent_probability, derive_training_material, sha)

SCHEMA = 'hepta.e16.independent-human-lopo-answer-centered.v1'
PRED_SCHEMA = 'hepta.e16.answer-centered-real-logits.v1'
METHODS = ('centered_raw_5', 'centered_scaled_5')
PARENT_METHODS = ('learned_linear_5', 'learned_gated_3')


def separate_geometry(observation):
    """No import of E16 proposer for model math or feature transformation."""
    source = independent_features(observation)
    sums = {}
    for row in source:
        sums.setdefault((row['group'], row['question']), []).append(row['x'][1:])
    if len(sums) != 8 or any(not 2 <= len(values) <= 8 for values in sums.values()):
        raise ValueError('original answer slates incomplete')
    means = {k: tuple(sum(q[j] for q in values) / len(values) for j in range(4))
             for k, values in sums.items()}
    result = []
    for r in source:
        avg = means[(r['group'], r['question'])]
        c = [r['x'][i + 1] - avg[i] for i in range(4)]
        derived = (c[0], c[1], c[2], c[1] * c[2])
        if any(not isfinite(v) or abs(v) > 128 for v in derived):
            raise ValueError('unbounded independent source feature')
        result.append({**r, 'centered': derived})
    return result


def fit_independent(rows, training, method):
    """Independent per-step derivative construction, never invokes proposer."""
    if method not in METHODS or not 20 <= len(training) <= 30:
        raise ValueError('unregistered Head/reference partition')
    included = [r for r in rows if r['task_id'] in training]
    if len(included) != len(training):
        raise ValueError('training rows omitted')
    norm = tuple(max(1e-5, max(abs(r['centered'][j]) for r in included)) for j in range(4))
    weight = [0.0 for _ in range(5)]
    started = process_time_ns()
    for iteration in range(48):
        derivatives = []
        for item in included:
            f = item['centered'] if method == 'centered_raw_5' else tuple(a / b for a, b in zip(item['centered'], norm, strict=True))
            z = (1.0,) + f
            t = sum(a * b for a, b in zip(weight, z, strict=True))
            t = min(10000, max(-10000, t))
            s = (1 / (1 + exp(-t))) if t >= 0 else (exp(t) / (1 + exp(t)))
            gradient = 2 * (s - training[item['task_id']]) * s * (1 - s)
            derivatives.append([gradient * v for v in z])
        for j in range(5):
            average = sum(g[j] for g in derivatives) / len(included)
            weight[j] -= 0.5 * (average + (0.001 * weight[j] if j else 0.0))
        if any(not isfinite(w) or abs(w) > 128 for w in weight):
            raise ValueError('invalid nonlinear head fitting')
    elapsed = process_time_ns() - started
    return weight, norm, elapsed


def probability(row, method, weights, norm):
    if len(weights) != 5 or len(norm) != 4:
        raise ValueError('wrong independent parameter structure')
    x = row['centered'] if method == 'centered_raw_5' else tuple(a / b for a, b in zip(row['centered'], norm, strict=True))
    logit = weights[0] + sum(weights[i + 1] * x[i] for i in range(4))
    return 1 / (1 + exp(-logit)) if logit >= 0 else exp(logit) / (1 + exp(logit))


def evaluate(archive, validation_parquet, paths, hashes):
    if len(paths) != 4 or len(hashes) != 4:
        raise ValueError('four original passage folds mandatory')
    obs = read_prelabel(archive)
    truths = original_labels(read_validation(validation_parquet), obs['rows'])
    owner = historical_owner_score(archive)
    raw = independent_features(obs)
    inputs = separate_geometry(obs)
    if len(inputs) != 33 or set(truths) != {r['task_id'] for r in inputs}:
        raise ValueError('original human material incomplete')
    groups = sorted({r['group'] for r in inputs})
    if len(groups) != 4:
        raise ValueError('four independent source group IDs required')
    scores = {name: {'hits': [], 'brier': [], 'passage': {}} for name in
              (*ARMS, *PARENT_METHODS, *METHODS)}
    for r in raw:
        for j, arm in enumerate(ARMS):
            pp = r['p'][j]; truth = truths[r['task_id']]
            scores[arm]['hits'].append(int((pp >= 0.5) == bool(truth)))
            scores[arm]['brier'].append(2 * (pp - truth) ** 2)
            scores[arm]['passage'].setdefault(r['group'], []).append(int((pp >= .5) == bool(truth)))
    for arm in ARMS:
        original = owner['results'][arm]
        if (sum(scores[arm]['hits']) != original['correct'] or
            not isclose(sum(scores[arm]['brier']) / 33, original['brier'], abs_tol=2e-12, rel_tol=0)):
            raise ValueError('original human Reader baseline altered')

    signed_groups = set()
    predicted_ids = set()
    heads_cpu = 0
    baseline_replayed_cpu = 0
    receipts = []
    for fold, (path, expected) in enumerate(zip(paths, hashes, strict=True)):
        raw_file = Path(path).read_bytes()
        if sha256(raw_file).hexdigest() != expected:
            raise ValueError('held predictions were mutated after sealing')
        rec = strict_json(raw_file)
        allowed = {'schema', 'authority', 'fold', 'held_group', 'original_archive_sha256',
                   'original_observation_id', 'train_only_material_sha256', 'train_only_past_groups',
                   'train_only_scaling', 'methods', 'weights', 'meters', 'predictions',
                   'held_human_labels_accessed', 'original_model_forwards_new',
                   'physical_train_steps_completed', 'total_service_cost_measured',
                   'natural_future_task_gain', 'reader_semantic_adequacy_proven', 'production_accepted'}
        if (type(rec) is not dict or set(rec) != allowed or rec['schema'] != PRED_SCHEMA
                or rec['authority'] != 'DENY_ALL' or type(rec['fold']) is not int or rec['fold'] != fold
                or rec['held_group'] != groups[fold] or rec['original_archive_sha256'] != ARCHIVE_SHA
                or rec['original_observation_id'] != OBS_ID or rec['train_only_past_groups'] != 3
                or rec['held_human_labels_accessed'] is not False
                or rec['original_model_forwards_new'] != 0
                or rec['physical_train_steps_completed'] != 48
                or rec['total_service_cost_measured'] is not False
                or rec['natural_future_task_gain'] is not False
                or rec['reader_semantic_adequacy_proven'] is not False
                or rec['production_accepted'] is not False
                or rec['methods'] != list(METHODS)
                or type(rec['weights']) is not dict or set(rec['weights']) != set(METHODS)
                or type(rec['meters']) is not dict or set(rec['meters']) != set(METHODS)):
            raise ValueError('unqualified/promotion or incomplete fold')
        material = derive_training_material(obs, truths, fold)
        if rec['train_only_material_sha256'] != sha(material):
            raise ValueError('label/method/source group training boundary mismatch')
        train = {r['task_id']: r['label'] for r in material['training_label_rows']}
        held = [r for r in inputs if r['group'] == groups[fold]]
        base_held = [r for r in raw if r['group'] == groups[fold]]
        if (type(rec['predictions']) is not list or len(rec['predictions']) != len(held)
                or not 3 <= len(held) <= 10 or set(r['task_id'] for r in held) & set(train)):
            raise ValueError('missing/contaminated held group')
        references = {}
        for method in METHODS:
            weight, units, cpu = fit_independent(inputs, train, method)
            reported = rec['weights'][method]
            if (type(reported) is not list or len(reported) != 5 or
                any(type(v) is not float or not isfinite(v) or
                    not isclose(v, ref, abs_tol=2e-12, rel_tol=0)
                    for v, ref in zip(reported, weight, strict=True))):
                raise ValueError('learned feature-weight replay failed')
            if (type(rec['train_only_scaling']) is not list or len(rec['train_only_scaling']) != 4 or
                any(type(t) is not float or not isclose(t, u, abs_tol=1e-13, rel_tol=0)
                    for t, u in zip(rec['train_only_scaling'], units, strict=True))):
                raise ValueError('train-only scaler changed from source values')
            meter = rec['meters'][method]
            if (type(meter) is not dict or set(meter) != {'train_cpu_ns', 'held_cpu_ns', 'parameter_count', 'steps'}
                    or any(type(meter[k]) is not int or not 0 < meter[k] < 10**12 for k in ('train_cpu_ns', 'held_cpu_ns'))
                    or meter['parameter_count'] != 5 or meter['steps'] != 48):
                raise ValueError('unaccounted original-learning CPU')
            heads_cpu += meter['train_cpu_ns'] + meter['held_cpu_ns']
            references[method] = (weight, units)
        for method in PARENT_METHODS:
            cpu = process_time_ns()
            ref = independently_fit(raw, train, method)
            baseline_replayed_cpu += process_time_ns() - cpu
            references[method] = ref
        for original, predicted, parent_row in zip(held, rec['predictions'], base_held, strict=True):
            if (type(predicted) is not dict or set(predicted) != {'task_id', 'source_group',
                    'question_slot', 'candidate_id', 'probabilities'}
                    or predicted['task_id'] != original['task_id']
                    or predicted['source_group'] != original['group']
                    or predicted['question_slot'] != original['question']
                    or predicted['candidate_id'] != original['candidate_id']
                    or type(predicted['probabilities']) is not dict
                    or set(predicted['probabilities']) != set(METHODS)):
                raise ValueError('held candidate source identity mismatch')
            task = original['task_id']
            if task in predicted_ids:
                raise ValueError('duplicate held original candidate')
            predicted_ids.add(task)
            for method in (*METHODS, *PARENT_METHODS):
                if method in METHODS:
                    weights, units = references[method]
                    predicted_p = probability(original, method, weights, units)
                    claimed = predicted['probabilities'][method]
                    if (type(claimed) is not float or not isclose(
                            claimed, predicted_p, abs_tol=2e-12, rel_tol=0)):
                        raise ValueError('forged learning/probability evidence')
                else:
                    predicted_p = independent_probability(parent_row, references[method], method)
                if not isfinite(predicted_p) or not 0 < predicted_p < 1:
                    raise ValueError('nonfinite probability')
                truth = truths[task]
                hit = int((predicted_p >= 0.5) == bool(truth))
                scores[method]['hits'].append(hit)
                scores[method]['brier'].append(2 * (predicted_p - truth) ** 2)
                scores[method]['passage'].setdefault(groups[fold], []).append(hit)
        signed_groups.add(groups[fold])
        receipts.append({'fold': fold, 'held_source_group': groups[fold],
                         'held_candidate_count': len(held), 'independent_weight_replay': True})
    if signed_groups != set(groups) or predicted_ids != set(truths):
        raise ValueError('not a complete original-candidate source-held panel')
    result = {}
    for method, item in scores.items():
        if len(item['hits']) != 33 or len(item['brier']) != 33:
            raise ValueError('incomplete original evaluation panel')
        result[method] = {'correct': sum(item['hits']), 'total': 33,
                          'accuracy': sum(item['hits']) / 33,
                          'brier': sum(item['brier']) / 33,
                          'source_passage_correct': {g: sum(v) for g, v in item['passage'].items()},
                          'source_passage_total': {g: len(v) for g, v in item['passage'].items()}}
    return {'schema': SCHEMA, 'authority': 'DENY_ALL', 'source_archive_sha256': ARCHIVE_SHA,
            'original_validation_source_sha256': VAL_SHA,
            'original_readers_count': 4, 'original_passage_count': 4, 'original_question_count': 8,
            'original_human_candidate_count': 33, 'folds': receipts, 'results': result,
            'observed_E16_python_training_inference_cpu_ns': heads_cpu,
            'E15_replayed_learner_CPU_ns_in_review_only_not_original_runner': baseline_replayed_cpu,
            'original_pretrained_encoder_forwards_in_E16': 0,
            'four_E15_E16_methods_same_brier_optimizer_updates': True,
            'E15_retrospective_parent_head_source_replayed_not_E15_hosted_receipt': True,
            'original_human_labels_only_applied_post_four_seals': True,
            'independent_original_human_signatures_present': False,
            'all_data_from_one_historical_family': True,
            'four_passages_statistically_underpowered': True,
            'prospective_future_time_gain_established': False,
            'complete_online_model_plus_student_cost_qualified': False,
            'pretrained_model_or_head_selected': False, 'production_accepted': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for fold in range(4):
        ap.add_argument(f'--fold-{fold}', required=True)
        ap.add_argument(f'--fold-{fold}-sha256', required=True)
    for name in ('archive', 'validation-parquet', 'output'):
        ap.add_argument('--' + name, required=True)
    args = ap.parse_args()
    paths = [getattr(args, f'fold_{i}') for i in range(4)]
    hashes = [getattr(args, f'fold_{i}_sha256') for i in range(4)]
    print(write_once(args.output, evaluate(args.archive, args.validation_parquet,
                                          paths, hashes)), 'DENY_ALL')


if __name__ == '__main__':
    main()
