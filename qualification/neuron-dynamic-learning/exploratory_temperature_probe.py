"""Public AG News post-hoc temperature exploration, not qualified calibration.

The public test cases have already been examined by researchers. This is a
hypothesis-generating, calibration-split-only fit with a descriptive test score,
not preregistered future-window evidence. Never changes the frozen checkpoint,
Cell Head, production policy, or recorded raw arm receipts.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from paired_independent_audit import ReviewError, canonical, sha, verify

ALPHAS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024)


def scale_probability(p, alpha):
    if type(p) not in (int, float) or not math.isfinite(p) or not 0 < p < 1:
        raise ReviewError('nonfinite or degenerate source probability')
    if alpha not in ALPHAS:
        raise ReviewError('unapproved exploratory temperature scale')
    log_odds = math.log(p) - math.log1p(-p)
    scaled = max(-50.0, min(50.0, alpha * log_odds))
    return min(1-1e-12, max(1e-12, 1 / (1 + math.exp(-scaled))))


def brier(rows, labels, alpha):
    if not rows:
        raise ReviewError('empty observed calibration cohort')
    return sum((scale_probability(row['prob_sports'], alpha) - labels[row['case_id']])**2
               for row in rows) / len(rows)


def _diagnostics(rows, labels, alpha):
    predictions = [(scale_probability(row['prob_sports'], alpha), labels[row['case_id']])
                   for row in rows]
    bins = []
    for bin_id in range(8):
        grp = [(p, y) for p, y in predictions if min(7, int(max(p, 1-p)*8)) == bin_id]
        if grp:
            bins.append(len(grp)/len(predictions) * abs(
                sum((p >= .5) == y for p, y in grp)/len(grp) -
                sum(max(p,1-p) for p, _ in grp)/len(grp)))
    return {'cases': len(predictions),
            'accuracy': sum((p >= .5) == y for p, y in predictions)/len(predictions),
            'brier': sum((p-y)**2 for p,y in predictions)/len(predictions),
            'descriptive_ece_8_bin': sum(bins)}


def probe(panel, receipt, gemma, laya, comparison):
    reviewed = verify(panel, receipt, gemma, laya, comparison)
    labels = {row['case_id']: row['label'] for row in panel['cases']}
    learned = next(r for r in gemma if r['arm_id'] == 'gemma2_trained_head')
    calibration = [row for row in learned['rows'] if row['split'] == 'calibration']
    test = [row for row in learned['rows'] if row['split'] == 'test']
    if len(calibration) != 32 or len(test) != 64:
        raise ReviewError('incomplete fixed calibration or test cohort')
    # No test label enters this fit or selection. The *research design* was
    # formed after test inspection, so the output cannot be called confirmatory.
    score = {alpha: brier(calibration, labels, alpha) for alpha in ALPHAS}
    selected = min(ALPHAS, key=lambda alpha: (score[alpha], alpha))
    return {
        'schema': 'hepta.stem.public-head-temperature-exploration.v1',
        'panel_digest': reviewed['panel_digest'],
        'raw_trained_arm_digest': reviewed['report_digests']['gemma2_trained_head'],
        'training_update': 'none_posthoc_probability_transform_only',
        'candidate_scale_grid': list(ALPHAS),
        'fit_inputs': 'calibration_only_labels_and_raw_probabilities',
        'selected_logit_multiplier': selected,
        'calibration_observed_brier_by_scale': {str(k): v for k,v in score.items()},
        'raw_calibration': _diagnostics(calibration, labels, 1),
        'exploratory_scaled_calibration': _diagnostics(calibration, labels, selected),
        'raw_test': _diagnostics(test, labels, 1),
        'exploratory_scaled_test': _diagnostics(test, labels, selected),
        'test_label_accessed_during_selection': False,
        'test_distribution_already_reviewed_by_researcher': True,
        'confirmatory_future_window_tested': False,
        'independent_model_origin_attested': False,
        'matched_total_lifecycle_cost': False,
        'model_weights_or_selected_head_mutated': False,
        'production_promotion': 'DENY_ALL',
    }


def main():
    parser = argparse.ArgumentParser(description='Exploratory public post-hoc calibration')
    for k in ('panel','source','gemma','laya','comparison','out'):
        parser.add_argument('--'+k, type=Path, required=True)
    a=parser.parse_args()
    result=probe(*[json.loads(getattr(a,k).read_text(encoding='utf-8'))
                   for k in ('panel','source','gemma','laya','comparison')])
    a.out.write_bytes(canonical(result))
    print(json.dumps({'report_digest':sha(canonical(result)),
                      'selected_logit_multiplier':result['selected_logit_multiplier'],
                      'production_promotion':result['production_promotion']},sort_keys=True))


if __name__=='__main__':
    main()
