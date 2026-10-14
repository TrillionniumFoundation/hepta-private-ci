"""Independent read-only numerical review of the public Stem/Laya three-arm trial.

Consumes immutable experiment artefacts after inference. Recomputes provenance
linkage and metrics without importing either inference runner or trainable Head.
The source bytes and model executions remain externally/self attested: no
FinalUse, future-window, causal gain, equal-lifecycle-cost or release authority.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

SPLITS = ('train', 'calibration', 'test')
ARMS = ('gemma2_frozen_head', 'gemma2_trained_head', 'laya421_frozen')
GEMMA_REV = '914f7f89142e33e77833254d9c9b90c3cef7303b'
LAYA_REV = '55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851'
STEM = 'google/embeddinggemma-2'


class ReviewError(ValueError):
    """Mismatched, leaked or falsely elevated empirical claim."""


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(x):
    return hashlib.sha256(x).hexdigest()


def require(condition, why):
    if not condition:
        raise ReviewError(why)


def true_sha(x):
    return isinstance(x, str) and len(x) == 64 and all(c in '0123456789abcdef' for c in x)


def _source_cases(panel, receipt):
    from public_agnews_panel import FILES
    require(isinstance(panel, dict) and panel.get('schema') ==
            'hepta.stem.agnews-binary-capability-panel.v1' and
            panel.get('dataset') == 'szhuggingface/ag_news' and
            panel.get('dataset_commit_prefix') == '98c5322' and
            panel.get('cross_sectional_not_future') is True and
            panel.get('pretrained_model_execution') is False and
            panel.get('production_promotion') == 'DENY_ALL' and
            panel.get('independent_outcome_observer') is False and
            panel.get('fair_cpu_model_budget_verified') is False and
            panel.get('dataset_file_sha256') == {k: v[1] for k, v in FILES.items()},
            'invalid registered public source panel')
    digest = sha(canonical(panel))
    require(isinstance(receipt, dict) and
            receipt.get('schema') == 'hepta.stem.agnews-input-receipt.v1' and
            receipt.get('panel_digest') == digest and
            receipt.get('source_sha256') == panel['dataset_file_sha256'] and
            receipt.get('production_promotion') == 'DENY_ALL' and
            receipt.get('external_source_signer_authenticated') is False and
            receipt.get('future_longitudinal_evidence') is False and
            receipt.get('physical_model_weights_executed') is False,
            'source receipt mismatch or origin overclaim')
    cases = panel.get('cases')
    require(isinstance(cases, list) and len(cases) == 224 and
            panel.get('case_count') == len(cases), 'incomplete source cases')
    by_id = {}
    source_set = set()
    counts = Counter()
    for row in cases:
        require(isinstance(row, dict) and set(row) == {
            'case_id', 'source_digest', 'joint_input_digest', 'split', 'label',
            'label_name', 'group_id', 'joint_input'}, 'incomplete source case')
        joint = row['joint_input']
        require(isinstance(joint, dict) and set(joint) == {'question', 'options', 'state'}
                and joint['question'] == 'Which category does the news report describe?'
                and joint['options'] == ['world', 'sports'] and
                isinstance(joint['state'], str) and
                row['source_digest'] == sha(joint['state'].encode('utf-8')) and
                row['joint_input_digest'] == sha(canonical(joint)) and
                row['group_id'] == row['source_digest'] and
                row['case_id'] == row['source_digest'][:24] and
                type(row['label']) is int and row['label'] in (0, 1) and
                row['label_name'] == joint['options'][row['label']] and
                row['split'] in SPLITS and row['case_id'] not in by_id and
                row['source_digest'] not in source_set,
                'source case hash, option, label or group invalid')
        source_set.add(row['source_digest'])
        by_id[row['case_id']] = row
        counts[(row['split'], row['label'])] += 1
    expected_counts = {('train', 0): 64, ('train', 1): 64,
                       ('calibration', 0): 16, ('calibration', 1): 16,
                       ('test', 0): 32, ('test', 1): 32}
    require(dict(counts) == expected_counts, 'wrong sample or label balance')
    require(receipt.get('counts_by_split_label') == {
        f'{split}/{label}': count for (split, label), count in expected_counts.items()},
        'owner dataset receipt label counts differ')
    return digest, by_id


def _index_report(report, arm, panel_digest, cases):
    require(isinstance(report, dict) and report.get('schema') ==
            'hepta.stem.agnews-physical-arm.v1' and
            report.get('arm_id') == arm and report.get('panel_digest') == panel_digest and
            report.get('production_promotion') == 'DENY_ALL' and
            report.get('real_model_execution_claim') is True and
            report.get('model_execution_independently_attested') is False and
            report.get('source_outcome_independently_attested') is False and
            report.get('cross_sectional_not_future') is True and
            report.get('full_lifecycle_equal_cost_verified') is False and
            report.get('physical_transformer_forward_calls') is None,
            'model report identity or authority claim differs')
    info = report.get('metadata')
    require(isinstance(info, dict), 'model identity is unbound')
    if arm == 'laya421_frozen':
        require(info.get('backend') == 'convaiinnovations/laya' and
                info.get('revision') == LAYA_REV and
                info.get('trainable_parameters') == 0 and
                info.get('pretrained_checkpoint_verified_by_loader') is True and
                type(info.get('model_parameter_count')) is int and
                400_000_000 <= info['model_parameter_count'] <= 450_000_000,
                'frozen Laya checkpoint mismatch')
    else:
        require(info.get('backend') == STEM and info.get('revision') == GEMMA_REV and
                true_sha(info.get('stem_digest')) and
                true_sha(info.get('head_artifact_digest')) and
                type(info.get('head_parameters')) is int and
                0 < info['head_parameters'] <= 2048 and
                type(info.get('model_encode_api_calls')) is int and
                info['model_encode_api_calls'] >= 1 and
                info.get('cpu_batch_wall_allocation') ==
                'equal_shared_batch_wall_amortized_not_direct_latency',
                'frozen Gemma/Head identity or budget mismatch')
        steps = 0 if arm == 'gemma2_frozen_head' else 40
        require(info.get('optimizer_steps') == steps and
                type(info.get('local_head_train_micros')) is int and
                (info['local_head_train_micros'] == 0 if steps == 0 else
                 info['local_head_train_micros'] > 0),
                'frozen control or actual training iteration mismatch')
    expected = {cid: row for cid, row in cases.items()
                if row['split'] in ('calibration', 'test')}
    rows = report.get('rows')
    require(isinstance(rows, list) and len(rows) == len(expected), 'missing paired task rows')
    seen = {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {
            'case_id', 'source_digest', 'joint_input_digest', 'split',
            'prob_sports', 'measured_serving_micros'}, 'unknown per-case output')
        case = expected.get(row['case_id'])
        require(case is not None and row['case_id'] not in seen and
                all(row[k] == case[k] for k in ('source_digest', 'joint_input_digest', 'split'))
                and type(row['prob_sports']) in (int, float) and
                math.isfinite(row['prob_sports']) and 0 <= row['prob_sports'] <= 1 and
                type(row['measured_serving_micros']) is int and
                row['measured_serving_micros'] > 0,
                'case reuse, mismatched evidence, nonfinite prediction or fake measured cost')
        seen[row['case_id']] = row
    return seen, info


def _metrics(rows, panel, split):
    ids = sorted(cid for cid, c in panel.items() if c['split'] == split)
    pairs = [(rows[cid]['prob_sports'], panel[cid]['label']) for cid in ids]
    correct = sum((p >= .5) == y for p, y in pairs)
    brier = sum((p - y)**2 for p, y in pairs) / len(pairs)
    ece = 0.0
    for bin_id in range(8):
        assigned = [(p, y) for p, y in pairs
                    if min(7, int(max(p, 1-p)*8)) == bin_id]
        if assigned:
            accuracy = sum((p >= .5) == y for p, y in assigned) / len(assigned)
            confidence = sum(max(p, 1-p) for p, _ in assigned) / len(assigned)
            ece += len(assigned) / len(pairs) * abs(accuracy - confidence)
    return {'cases': len(pairs), 'accuracy': correct / len(pairs),
            'brier': brier, 'uncalibrated_ece_8_bin': ece,
            'sum_measured_serving_micros': sum(rows[cid]['measured_serving_micros'] for cid in ids)}


def verify(panel, source_receipt, gemma_reports, laya_report, comparison):
    digest, cases = _source_cases(panel, source_receipt)
    require(isinstance(gemma_reports, list) and len(gemma_reports) == 2,
            'exact frozen and learned Gemma arms are required')
    reports = [*gemma_reports, laya_report]
    require(all(isinstance(r, dict) for r in reports) and
            sorted(r['arm_id'] for r in reports) == list(ARMS),
            'incomplete or duplicate model arm')
    indexed = {}
    details = {}
    for r in reports:
        indexed[r['arm_id']], details[r['arm_id']] = _index_report(
            r, r['arm_id'], digest, cases)
    frozen, trained = details['gemma2_frozen_head'], details['gemma2_trained_head']
    require(frozen['stem_digest'] == trained['stem_digest'] and
            frozen['head_parameters'] == trained['head_parameters'] and
            frozen['model_encode_api_calls'] == trained['model_encode_api_calls'] and
            frozen['head_artifact_digest'] != trained['head_artifact_digest'],
            'frozen and learned Heads not comparably derived from same Stem')
    require(isinstance(comparison, dict) and comparison.get('schema') ==
            'hepta.stem.agnews-comparison.shadow.v1' and
            comparison.get('panel_digest') == digest and
            comparison.get('arms') == list(ARMS) and
            comparison.get('paired_same_source_case_ids') is True and
            comparison.get('pretrained_forward_claims_locally_recorded') is True and
            all(comparison.get(k) is False for k in (
                'independent_model_and_outcome_authentication',
                'matched_full_lifecycle_cost', 'three_future_windows_present',
                'ood_discrimination_tested', 'posthoc_calibration_fit',
                'causal_longitudinal_learning')) and
            comparison.get('production_promotion') == 'DENY_ALL',
            'unsupported comparison claim')
    recorded = comparison.get('windows')
    require(isinstance(recorded, dict) and set(recorded) == {'calibration', 'test'},
            'invalid output evaluation splits')
    metrics = {}
    for split in ('calibration', 'test'):
        require(isinstance(recorded[split], dict) and set(recorded[split]) == set(ARMS),
                'missing matched arm statistics')
        metrics[split] = {}
        for arm in ARMS:
            actual = _metrics(indexed[arm], cases, split)
            for key, measured in actual.items():
                claimed = recorded[split][arm].get(key)
                require(type(claimed) in (int, float) and math.isfinite(claimed) and
                        math.isclose(claimed, measured, rel_tol=1e-10, abs_tol=1e-10),
                        'self-reported accuracy, Brier, ECE, or runtime has been modified')
            metrics[split][arm] = actual
    test = metrics['test']
    gains = {
        'trained_minus_frozen_accuracy': test['gemma2_trained_head']['accuracy'] -
            test['gemma2_frozen_head']['accuracy'],
        'trained_minus_frozen_brier_reduction': test['gemma2_frozen_head']['brier'] -
            test['gemma2_trained_head']['brier'],
        'trained_minus_laya_accuracy': test['gemma2_trained_head']['accuracy'] -
            test['laya421_frozen']['accuracy'],
        'trained_minus_laya_brier_reduction': test['laya421_frozen']['brier'] -
            test['gemma2_trained_head']['brier'],
    }
    return {
        'schema': 'hepta.stem.paired-public-independent-numeric-review.v1',
        'panel_digest': digest,
        'report_digests': {r['arm_id']: sha(canonical(r)) for r in reports},
        'comparison_digest': sha(canonical(comparison)),
        'source_receipt_digest': sha(canonical(source_receipt)),
        'case_count': len(cases),
        'paired_scored_cases': 96,
        'arms': list(ARMS),
        'metrics': metrics,
        'test_descriptive_deltas': gains,
        'numeric_and_case_integrity_verified': True,
        'physical_forward_counts_independently_verified': False,
        'foundation_pretraining_cost_included': False,
        'equal_full_lifecycle_cost_verified': False,
        'independent_model_execution_authentication': False,
        'independent_source_label_authentication': False,
        'future_longitudinal_learning_proven': False,
        'production_promotion': 'DENY_ALL',
    }


def main():
    p = argparse.ArgumentParser(description='Numerically re-evaluate untrusted cross-sectional trials')
    for x in ('panel', 'source', 'gemma', 'laya', 'comparison', 'out'):
        p.add_argument('--'+x, required=True, type=Path)
    a = p.parse_args()
    result = verify(*[json.loads(getattr(a, key).read_text(encoding='utf-8'))
                      for key in ('panel', 'source', 'gemma', 'laya', 'comparison')])
    a.out.write_bytes(canonical(result))
    print(json.dumps({'review_digest': sha(canonical(result)),
                      'production_promotion': result['production_promotion']}, sort_keys=True))


if __name__ == '__main__':
    main()
