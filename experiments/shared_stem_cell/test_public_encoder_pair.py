"""Retrospective E1 pilot contracts: only actual approved weight jobs can count."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.shared_stem_cell.public_encoder_pair import (
    BASELINE_ID, CANDIDATE_ID, CANDIDATE_REVISION, verify_baseline,
)
from experiments.shared_stem_cell.public_encoder_pair_review import paired_review, _load
from experiments.shared_stem_cell.preflight_review import ARMS, PreflightError
from experiments.shared_stem_cell.wire import canonical, sha

R = 'b' * 40
H = 'a' * 64


def cohort():
    rows = []
    for i in range(128):
        split = 'train' if i < 64 else 'calibration' if i < 96 else 'holdout'
        rows.append({'case_id': f'case-{i}', 'group': f'src-{i}', 'split': split,
                     'observed_at': None, 'cell': i % 2, 'scope': 'public-ag-news-research',
                     'text': f'public example {i}', 'label': i % 4})
    return rows


def seed_pair(root):
    baseline = root / 'baseline'
    candidate = root / 'modern'
    baseline.mkdir(); candidate.mkdir()
    rows = cohort()
    raw = b''.join(canonical(x) for x in rows)
    base_model = {'model_id': BASELINE_ID, 'revision': R, 'kind': 'masked_lm'}
    modern_model = {'model_id': CANDIDATE_ID, 'revision': CANDIDATE_REVISION,
                    'kind': 'masked_lm', 'conversion': None}
    config = {'schema': 'hepta.shared-stem-execution.v1', 'classes': 4, 'cells': 2,
              'steps': 20, 'seed': 20261013, 'batch_size': 8, 'maximum_tokens': 512,
              'dataset': {'path': 'dataset.jsonl', 'sha256': sha(raw)}}
    before_plan = {**config, 'model': base_model}
    after_plan = {**config, 'model': modern_model}
    for where, plan, source in ((baseline, before_plan, BASELINE_ID),
                                (candidate, after_plan, CANDIDATE_ID)):
        (where / 'manifest.json').write_bytes(canonical(plan))
        (where / 'model-source.json').write_bytes(canonical({'model_id': source,
                                                             'revision': plan['model']['revision']}))
        (where / 'dataset.jsonl').write_bytes(raw)
    member = {'schema': 'hepta.public-two-stem-member.v1',
              'baseline_model_id': BASELINE_ID, 'baseline_revision': R,
              'candidate_model_id': CANDIDATE_ID,
              'candidate_revision': CANDIDATE_REVISION,
              'dataset_sha256': sha(raw),
              'manifest_sha256': sha(canonical(after_plan)),
              'producer_report_sha256': H,
              'independent_future_outcomes': False, 'production_accepted': False}
    (candidate / 'pair-member.json').write_bytes(canonical(member))
    def records(model):
        predictions = []
        for head in ARMS:
            for row in rows[96:]:
                # Distinct decisions; exact pairability rather than winner.
                index = 0 if model == BASELINE_ID else 1
                p = [.025] * 4
                p[index] = .925
                predictions.append({'arm': head, 'case_id': row['case_id'],
                                    'group': row['group'], 'split': row['split'],
                                    'cell': row['cell'], 'input_digest': sha(canonical([row['scope'], row['text']])),
                                    'probabilities': p})
        return {'predictions': predictions}
    def result(model):
        plan = before_plan if model == BASELINE_ID else after_plan
        training = {head: [{'steps': 20, 'parameters': 2000},
                           {'steps': 20, 'parameters': 2000}] for head in ARMS}
        report = {'training': training, 'process_lifetime_peak_rss_bytes': 10**9}
        proof = {'preflight': {'manifest_sha256': sha(canonical(plan)),
                              'producer_report_sha256': H},
                 'replay': {'physical_head_checkpoint_count': 16,
                            'checked_prediction_vectors': 256}}
        return plan, report, records(model), proof
    return baseline, candidate, result(BASELINE_ID), result(CANDIDATE_ID)


class PublicPairTests(unittest.TestCase):
    def test_accepts_only_small_fixed_public_retrospective_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, _, _, _ = seed_pair(Path(tmp))
            plan, data = verify_baseline(baseline)
            self.assertEqual(plan['dataset']['sha256'], sha(data))
            self.assertEqual(len(data.splitlines()), 128)

    def test_paired_predictions_are_recomputed_without_stem_winner_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, modern, b, m = seed_pair(Path(tmp))
            with patch('experiments.shared_stem_cell.public_encoder_pair_review._load',
                       side_effect=[b, m]):
                answer = paired_review(baseline, modern)
            self.assertEqual(answer['paired_holdout_cases'], 32)
            self.assertTrue(answer['same_training_and_dataset_manifest_except_model'])
            self.assertEqual(len(answer['trained_heads']), 4)
            for head in answer['trained_heads']:
                self.assertEqual((head['mmbert_only_correct'], head['modern_only_correct'],
                                  head['correctness_ties']), (8, 8, 16))
            self.assertFalse(answer['four_encoder_e1_completed'])
            self.assertFalse(answer['future_ndu_utility_evaluated'])
            self.assertFalse(answer['production_accepted'])

    def test_pair_weakens_on_unmatched_dataset_even_with_mocked_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, modern, b, m = seed_pair(Path(tmp))
            (modern / 'dataset.jsonl').write_text('{}\n')
            with patch('experiments.shared_stem_cell.public_encoder_pair_review._load',
                       side_effect=[b, m]), self.assertRaisesRegex(PreflightError, 'digest mismatch'):
                paired_review(baseline, modern)

    def test_pair_refuses_mismatched_train_seed_or_head_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, modern, b, m = seed_pair(Path(tmp))
            (modern / 'manifest.json').write_bytes(canonical({**m[0], 'seed': 15}))
            with patch('experiments.shared_stem_cell.public_encoder_pair_review._load',
                       side_effect=[b, ({**m[0], 'seed': 15}, m[1], m[2], m[3])]), self.assertRaisesRegex(PreflightError, 'plan and train condition drift'):
                paired_review(baseline, modern)

    def test_pair_refuses_dropped_prediction_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, modern, b, m = seed_pair(Path(tmp))
            m[2]['predictions'].pop()
            with patch('experiments.shared_stem_cell.public_encoder_pair_review._load',
                       side_effect=[b, m]), self.assertRaisesRegex(PreflightError, 'set incomplete'):
                paired_review(baseline, modern)

    def test_pair_refuses_rehashed_fake_model_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, modern, b, m = seed_pair(Path(tmp))
            path = modern / 'pair-member.json'
            data = json.loads(path.read_bytes())
            data['candidate_revision'] = 'c' * 40
            path.write_bytes(canonical(data))
            with patch('experiments.shared_stem_cell.public_encoder_pair_review._load',
                       side_effect=[b, m]), self.assertRaisesRegex(PreflightError, 'registration mismatch'):
                paired_review(baseline, modern)

    def test_loading_actual_head_report_enforces_parameters_and_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, modern, b, m = seed_pair(Path(tmp))
            (modern / 'execution').mkdir()
            (modern / 'execution/predictions.json').write_bytes(canonical({'predictions': []}))
            (modern / 'execution/report.json').write_bytes(canonical({
                'predictions_sha256': sha((modern / 'execution/predictions.json').read_bytes()),
                'training': {head: [{'steps': 20, 'parameters': 16385},
                                    {'steps': 20, 'parameters': 2000}] for head in ARMS}}))
            with patch('experiments.shared_stem_cell.public_encoder_pair_review.review',
                       return_value={}), patch('experiments.shared_stem_cell.public_encoder_pair_review.replay',
                                               return_value={'physical_head_checkpoint_count': 16,
                                                             'checked_prediction_vectors': 256}):
                with self.assertRaisesRegex(PreflightError, 'Head has exceeded'):
                    _load(modern)


if __name__ == '__main__':
    unittest.main()
