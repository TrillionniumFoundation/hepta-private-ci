#!/usr/bin/env python3
"""Exact-original E1 AG News paired/threshold sensitivity, never Stem selection.

Uses public TEST labels only *after* a source-bound original E1/E2 two-model
partial audit. Producer already had these labels. Does not reuse or train an
Encoder, independently execute a frozen Head, or admit absent mmBERT.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import e1_original_partial_two_model_audit_v1 as ancestry

SCHEMA = 'hepta.e1e2.original-public-paired-threshold-sensitivity.v2'
MODELS = tuple(ancestry.MODEL_INFO)
ARMS = ('frozen_head', 'from_zero', 'cosine_prototype',
        'residual_2k', 'residual_8k', 'residual_16k')
THRESHOLDS = (0.49, 0.50, 0.51)


class Invalid(ValueError):
    pass


def is_probability(p):
    return type(p) in (float, int) and math.isfinite(p) and 0 <= p <= 1


def strict_test_predictions(rows, case_index):
    """Align probabilities by original SHA-bound TEST case, never row position."""
    expected = {k for k, case in case_index.items() if case['split'] == 'test'}
    if type(rows) is not list or not expected:
        raise Invalid('missing prediction rows or original test cases')
    seen = {}
    for row in rows:
        if type(row) is not dict or set(row) != {
            'case_id', 'joint_input_digest', 'split', 'positive_probability'}:
            raise Invalid('altered probability envelope')
        if row['split'] != 'test':
            # The paired audit never accepts an unchecked CAL or novel split,
            # even though those rows have no TEST label used here.
            key = row['case_id']
            if (row['split'] != 'calibration' or type(key) is not str or
                    key not in case_index or case_index[key]['split'] != 'calibration' or
                    row['joint_input_digest'] != case_index[key]['joint_input_digest'] or
                    not is_probability(row['positive_probability'])):
                raise Invalid('unbound non-TEST prediction in source')
            continue
        key = row['case_id']
        if type(key) is not str or key not in expected or key in seen:
            raise Invalid('duplicate, absent or injected public test case')
        if (row['joint_input_digest'] != case_index[key]['joint_input_digest'] or
                not is_probability(row['positive_probability'])):
            raise Invalid('changed view hash or unsafe score')
        seen[key] = float(row['positive_probability'])
    if set(seen) != expected or len(seen) != ancestry.SPLITS['test']:
        raise Invalid('incomplete original TEST probability census')
    return seen


def exact_discordant_p(wins, losses):
    """Two-sided paired exact sign/McNemar p; exploratory NOT promotion."""
    if (type(wins) is not int or type(losses) is not int or wins < 0 or losses < 0
            or wins + losses > ancestry.SPLITS['test']):
        raise Invalid('unsafe discordant counts')
    n = wins + losses
    if n == 0:
        return 1.0
    tail = math.fsum(math.comb(n, i) for i in range(min(wins, losses) + 1))
    return min(1.0, 2.0 * tail / (2 ** n))


def clopper_pearson(n_correct, n, alpha=0.05):
    """Conditional iid-binomial sensitivity interval, not deployment coverage."""
    if (type(n_correct) is not int or type(n) is not int or n <= 0 or
            not 0 <= n_correct <= n or n != ancestry.SPLITS['test'] or alpha != 0.05):
        raise Invalid('invalid conditional interval setup')

    def cdf_at_least(k, probability):
        return math.fsum(math.comb(n, i) * probability ** i *
                         (1.0 - probability) ** (n - i) for i in range(k, n + 1))

    def cdf_at_most(k, probability):
        return math.fsum(math.comb(n, i) * probability ** i *
                         (1.0 - probability) ** (n - i) for i in range(k + 1))

    low = 0.0
    if n_correct > 0:
        lo, hi = 0.0, 1.0
        for _ in range(88):
            mid = (lo + hi) / 2
            if cdf_at_least(n_correct, mid) < alpha / 2:
                lo = mid
            else:
                hi = mid
        low = (lo + hi) / 2
    high = 1.0
    if n_correct < n:
        lo, hi = 0.0, 1.0
        for _ in range(88):
            mid = (lo + hi) / 2
            if cdf_at_most(n_correct, mid) > alpha / 2:
                lo = mid
            else:
                hi = mid
        high = (lo + hi) / 2
    return [low, high]


def classify_scores(probabilities, labels, *, threshold=0.5):
    if (type(probabilities) is not dict or type(labels) is not dict or
            set(probabilities) != set(labels) or not probabilities or
            type(threshold) is not float or not 0.0 < threshold < 1.0):
        raise Invalid('misaligned score source or threshold')
    out = {}
    for key, score in probabilities.items():
        label = labels[key]
        if not is_probability(score) or type(label) is not int or label not in (0, 1):
            raise Invalid('unsafe public prediction/label')
        out[key] = bool(score >= threshold) == bool(label)
    return out


def paired(a, b):
    if type(a) is not dict or type(b) is not dict or set(a) != set(b) or not a:
        raise Invalid('different sample identities in paired comparison')
    if any(type(x) is not bool for x in list(a.values()) + list(b.values())):
        raise Invalid('invalid paired success status')
    a_only = sum(a[k] and not b[k] for k in a)
    b_only = sum(b[k] and not a[k] for k in a)
    agree_success = sum(a[k] and b[k] for k in a)
    agree_failure = sum(not a[k] and not b[k] for k in a)
    return {'a_only_correct': a_only, 'b_only_correct': b_only,
            'both_correct': agree_success, 'both_wrong': agree_failure,
            'nominal_two_sided_exact_discordant_p': exact_discordant_p(a_only, b_only),
            'exploratory_public_labels_not_formal_significance': True}


def review_source(original_zip):
    # Independent existing v1 reviewer SHA-checks entire exact historical zip,
    # every internal file, FIT/CAL/TEST panel, source and E1/E2 identity, every
    # baseline probability and the real mmBERT failed slot. Do not replace it.
    base = ancestry.audit_original_zip(original_zip)
    if (base['schema'] != ancestry.SCHEMA or
            base['original_complete_three_encoder_panel_qualified'] is not False or
            base['authority'] != 'DENY_ALL' or
            base['unavailable_model'] != {
                'model':'mmbert_small','status':'original_physical_model_failed','scored':False}):
        raise Invalid('incomplete authentic two-model predecessor audit')
    raw = ancestry.strict_original_artifact(original_zip)
    panel = ancestry.strict_json(raw['e1-public/panel.json'])
    cases = ancestry.validate_panel(panel)
    test = {k: c['label'] for k, c in cases.items() if c['split'] == 'test'}
    if len(test) != 64 or sorted(test.values()) != [0]*32 + [1]*32:
        raise Invalid('public TEST cohort/label balance altered')

    series = {}
    models = {}
    for model in MODELS:
        body = ancestry.strict_json(raw['e1-public/' + model + '.e2.json'])
        if set(body.get('arms', {})) != set(ARMS):
            raise Invalid('missing original E2 paired controls')
        series[model] = {}
        arm_metrics = {}
        for arm in ARMS:
            probabilities = strict_test_predictions(body['arms'][arm]['predictions'], cases)
            success = classify_scores(probabilities, test)
            correct = sum(success.values())
            scores = [probabilities[k] for k in test]
            arm_metrics[arm] = {
                'correct': correct, 'test_cases': len(test), 'accuracy': correct/len(test),
                'brier': math.fsum((probabilities[k] - test[k]) ** 2 for k in test) / len(test),
                'conditional_iid_binomial_95_interval': clopper_pearson(correct, len(test)),
                'within_0_01_of_binary_boundary': sum(abs(p - 0.5) < 0.01 for p in scores),
                'probability_min': min(scores), 'probability_max': max(scores),
                'accuracy_by_fixed_threshold': {
                    f'{threshold:.2f}': sum(classify_scores(probabilities, test,
                                                           threshold=threshold).values()) / len(test)
                    for threshold in THRESHOLDS},
            }
            series[model][arm] = success
        models[model] = {
            'original_revision': ancestry.MODEL_INFO[model][0],
            'test_arms': arm_metrics,
            'trained_against_frozen': paired(series[model]['from_zero'], series[model]['frozen_head']),
            'trained_against_2k_residual': paired(series[model]['from_zero'], series[model]['residual_2k']),
            'trained_against_cosine': paired(series[model]['from_zero'], series[model]['cosine_prototype']),
            'observed_model_cpu_execution_only_self_reported': True,
        }
    comparisons = {
        arm: paired(series['granite_97m_r2'][arm], series['embeddinggemma_2_text'][arm])
        for arm in ('from_zero', 'cosine_prototype')
    }
    return {
        'schema': SCHEMA, 'original_public_source_head': ancestry.SOURCE_HEAD,
        'original_github_actions_run_id': ancestry.ORIGINAL_RUN,
        'original_github_artifact_id': ancestry.ORIGINAL_ARTIFACT,
        'original_artifact_zip_sha256': ancestry.ZIP_SHA256,
        'original_panel_sha256': ancestry.PANEL_SHA256,
        'label_population': {'train':128,'calibration':32,'test':64,
                             'test_labels_seen_by_original_producer':True},
        # Chosen for retrospective sensitivity AFTER the original study; not
        # pre-registered, not a threshold-tuning study and never optimize here.
        'retrospective_fixed_thresholds_not_originally_preregistered': list(THRESHOLDS),
        'models': models, 'paired_model_comparisons': comparisons,
        'unavailable_model': {'model':'mmbert_small', 'status':'original_physical_model_failed'},
        'confidence_intervals_require_iid_unselected_test_samples_not_proved':True,
        'nominal_p_values_are_exploratory_not_an_admission_rule':True,
        'result_is_retrospective_public_cross_section_not_hidden_or_future':True,
        'model_encoder_weight_bytes_independently_replayed_here':False,
        'training_optimization_independently_replayed_here':False,
        'independent_semantic_future_test_verified':False,
        'negative_transfer_checked':False,
        'frozen_linear_head_is_random_control_not_model_native_policy':True,
        'cosine_prototypes_use_train_labels_not_no_change':True,
        'actual_target_host_latency_cpu_rss_4096_cell_verified':False,
        'complete_three_model_study_qualified':False,
        'production_model_winner_selected':False,
        'production_promotion_permitted':False,
        'authority':'DENY_ALL',
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--original-run-zip', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError('create-only paired retrospective research evidence')
    result = review_source(args.original_run_zip)
    data = ancestry.canonical(result) + b'\n'
    with args.output.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({'schema':SCHEMA,'two_models_retrospectively_reviewed':2,
                      'model_selected':False,'authority':'DENY_ALL'},sort_keys=True))


if __name__ == '__main__':
    main()
