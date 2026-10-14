"""Cross-check two actual pretrained Encoders on exactly the same retrospective cohort.

Scores are per-example paired diagnostics, not external NDU, prospective retention,
independent source groups or production acceptance. It never trains a model.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import math

from experiments.shared_stem_cell.public_encoder_pair import (
    BASELINE_ID, CANDIDATE_ID, CANDIDATE_REVISION, verify_baseline,
)
from experiments.shared_stem_cell.preflight_review import (
    ARMS, checked_bytes, require, review,
)
from experiments.shared_stem_cell.physical_head_replay import replay
from experiments.shared_stem_cell.wire import decode, sha, write_once

SCHEMA = 'hepta.public-encoder-paired-review.v1'
MAX_HEAD_PARAMETERS = 16384


def _load(directory: Path) -> tuple[dict, dict, dict, dict]:
    plan = decode(checked_bytes(directory / 'manifest.json'))
    member_path = directory / 'execution' / 'report.json'
    report_raw = checked_bytes(member_path)
    report_digest = sha(report_raw)
    physical = review(directory / 'manifest.json', directory / 'execution', report_digest)
    replayed = replay(directory / 'manifest.json', directory / 'execution', report_digest)
    report = decode(report_raw)
    packet = decode(checked_bytes(directory / 'execution/predictions.json',
                                  report['predictions_sha256']))
    require(type(packet) is dict and type(packet.get('predictions')) is list,
            'sealed probability packet missing')
    for head, costs in report['training'].items():
        require(head in ARMS and type(costs) is list and len(costs) == 2,
                'unexpected trained Head inventory')
        for row in costs:
            require(type(row.get('steps')) is int and row['steps'] == plan['steps']
                    and type(row.get('parameters')) is int
                    and 1 <= row['parameters'] <= MAX_HEAD_PARAMETERS,
                    'Head has exceeded matched 16K parameter ceiling or steps')
    require(replayed['physical_head_checkpoint_count'] == 16
            and replayed['checked_prediction_vectors'] == 256,
            'incomplete checkpoint and prediction proof')
    return plan, report, packet, {'preflight': physical, 'replay': replayed}


def paired_review(baseline: Path, candidate: Path) -> dict:
    baseline_plan, source = verify_baseline(baseline)
    before_plan, before_report, before_packet, before_proofs = _load(baseline)
    after_plan, after_report, after_packet, after_proofs = _load(candidate)
    require(before_plan == baseline_plan, 'baseline changed during comparison')
    for key, value in baseline_plan.items():
        if key != 'model':
            require(after_plan.get(key) == value, 'paired plan and train condition drift')
    require(set(after_plan) == set(baseline_plan), 'unexpected paired execution plan field')
    require(after_plan['model'].get('model_id') == CANDIDATE_ID
            and after_plan['model'].get('revision') == CANDIDATE_REVISION
            and after_plan['model'].get('kind') == 'masked_lm'
            and after_plan['model'].get('conversion') is None,
            'wrong or converted candidate weights')
    actual_source = decode(checked_bytes(candidate / 'model-source.json'))
    require(actual_source.get('model_id') == CANDIDATE_ID
            and actual_source.get('revision') == CANDIDATE_REVISION,
            'publisher model/revision mismatch')
    require(checked_bytes(candidate / 'dataset.jsonl', sha(source)) == source,
            'different actual public inputs')
    member = decode(checked_bytes(candidate / 'pair-member.json'))
    require(member.get('schema') == 'hepta.public-two-stem-member.v1'
            and member.get('baseline_model_id') == BASELINE_ID
            and member.get('baseline_revision') == baseline_plan['model']['revision']
            and member.get('candidate_model_id') == CANDIDATE_ID
            and member.get('candidate_revision') == CANDIDATE_REVISION
            and member.get('dataset_sha256') == sha(source)
            and member.get('manifest_sha256') == after_proofs['preflight']['manifest_sha256']
            and member.get('producer_report_sha256') == after_proofs['preflight']['producer_report_sha256']
            and member.get('independent_future_outcomes') is False
            and member.get('production_accepted') is False,
            'paired member registration mismatch')
    truth = {}
    cases = [decode(line) for line in source.splitlines()]
    for item in cases:
        if item['split'] == 'holdout':
            truth[item['case_id']] = item
    require(len(truth) == 32, 'public holdout case census drift')
    indexed = []
    for name, packet in ((BASELINE_ID, before_packet), (CANDIDATE_ID, after_packet)):
        obs = {}
        for record in packet['predictions']:
            require(record['case_id'] in truth and record['arm'] in ARMS,
                    'unregistered paired prediction')
            key = record['arm'], record['case_id']
            require(key not in obs, 'duplicate paired prediction')
            obs[key] = record
        require(len(obs) == 32 * len(ARMS), 'paired prediction set incomplete')
        indexed.append(obs)
    before, after = indexed
    require(set(before) == set(after), 'paired cohort mismatch')
    per_head = []
    for head in ARMS:
        win = loss = tie = correct_a = correct_b = 0
        brier_a = brier_b = 0.0
        for key, row in sorted(before.items()):
            if key[0] != head:
                continue
            other = after[key]
            original = truth[key[1]]
            require(all(row[x] == other[x] == original[x] for x in ('case_id', 'group', 'split', 'cell'))
                    and row['input_digest'] == other['input_digest'],
                    'paired original input metadata drift')
            label = original['label']
            pa, pb = row['probabilities'], other['probabilities']
            a = int(max(range(len(pa)), key=pa.__getitem__) == label)
            b = int(max(range(len(pb)), key=pb.__getitem__) == label)
            win += int(b > a)
            loss += int(a > b)
            tie += int(a == b)
            correct_a += a
            correct_b += b
            brier_a += math.fsum((p - int(j == label))**2 for j, p in enumerate(pa))
            brier_b += math.fsum((p - int(j == label))**2 for j, p in enumerate(pb))
        per_head.append({'head': head, 'paired_cases': 32,
                         'modern_only_correct': win, 'mmbert_only_correct': loss,
                         'correctness_ties': tie, 'mmbert_correct': correct_a,
                         'modern_correct': correct_b, 'mmbert_brier_sum': brier_a,
                         'modern_brier_sum': brier_b,
                         'modern_minus_mmbert_accuracy': (correct_b - correct_a)/32,
                         'modern_minus_mmbert_brier': (brier_b - brier_a)/32})
    return {'schema': SCHEMA,
            'physical_member_models': [BASELINE_ID, CANDIDATE_ID],
            'cohort_sha256': sha(source),
            'baseline_manifest_sha256': before_proofs['preflight']['manifest_sha256'],
            'candidate_manifest_sha256': after_proofs['preflight']['manifest_sha256'],
            'paired_holdout_cases': len(truth), 'same_training_and_dataset_manifest_except_model': True,
            'same_budget_cap_per_cell': MAX_HEAD_PARAMETERS,
            'trained_heads': per_head,
            'source_execution_receipt_sha256': before_proofs['preflight']['producer_report_sha256'],
            'candidate_execution_receipt_sha256': after_proofs['preflight']['producer_report_sha256'],
            'saved_weights_replay_verified': True,
            'mmbert_process_lifetime_peak_rss_bytes': before_report['process_lifetime_peak_rss_bytes'],
            'modern_process_lifetime_peak_rss_bytes': after_report['process_lifetime_peak_rss_bytes'],
            'host_process_isolation_attested': False,
            'model_weights_independently_attested': False,
            'source_family_independence_verified': False,
            'retrospective_publisher_holdout': True,
            'future_ndu_utility_evaluated': False,
            'laya_teacher_comparison_completed': False,
            'four_encoder_e1_completed': False,
            'five_head_budgets_e2_completed': False,
            'production_accepted': False,
            'model_selection_authority': False}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--candidate', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    r = paired_review(args.baseline, args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_once(args.output, r)


if __name__ == '__main__':
    main()
