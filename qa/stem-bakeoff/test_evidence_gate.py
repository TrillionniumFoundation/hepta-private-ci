import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from evidence_gate import assess, REQUIRED_SPLITS, SCALES
from stem_bakeoff import (RESULT_SCHEMA, POSTURE, REQUIRED_GATES,
                          REQUIRED_METRICS, CELL_COMPONENTS)

HEAD = 'd' * 40


def receipt():
    metrics = {key: 0.25 for key in REQUIRED_METRICS}
    metrics.update({'p99_ms': 6.5, 'throughput_per_host': 50.0,
                    'rss_bytes': 8192, 'gpu_peak_bytes': 0,
                    'per_cell_incremental_bytes': 512})
    return {
        'schema': RESULT_SCHEMA,
        'authority': 'qualification_only',
        'runtime_posture': dict(POSTURE),
        'candidate': 'hepta_latent_150m',
        'artifact': {'digest': 'sha256:' + 'a'*64, 'revision': 'b'*40},
        'metrics': metrics,
        'gates': {key: True for key in REQUIRED_GATES},
        'cell_components': list(CELL_COMPONENTS),
        'evidence': {
            'evidence_class': 'REAL_MODEL_OBSERVED',
            'loaded_pretrained_weights': True,
            'checkpoint_inventory_sha256': 'c'*64,
            'runtime_sha256': 'e'*64,
            'source_sha256': 'f'*64,
            'splits': {key: str(i+1)*64 for i,key in enumerate(REQUIRED_SPLITS)},
            'held_labels_hidden': True,
            'future_source_disjoint': True,
            'instrumentation': {'level': 'model_forward_hook', 'backend_forward_count_observed': True},
            'scale_measurements': [
                {'cells': n, 'unique_input_batches': 2, 'encoder_forward_calls': 2,
                 'private_backbone_bytes': 0, 'p95_ms': 4.0, 'p99_ms': 6.5,
                 'peak_rss_bytes': 1000000 + n*512} for n in SCALES
            ],
        },
        'ci': {'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success',
               'run_id': 123456, 'workflow': 'blocking-ci'},
    }


class EvidenceGateTests(unittest.TestCase):
    def test_well_shaped_self_report_can_only_request_review(self):
        result = assess(receipt(), HEAD)
        self.assertEqual(result['evidence_status'], 'REVIEW_REQUIRED')
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['authority'], 'DENY_ALL')
        self.assertFalse(result['production_activation_allowed'])
        self.assertTrue(result['independent_review_required'])

    def test_vacuous_fields_and_fake_digest_cannot_close_gate(self):
        data = receipt()
        data['artifact']['digest'] = 'sha256:fake'
        data['metrics']['p99_ms'] = 0
        data['evidence']['loaded_pretrained_weights'] = False
        outcome = assess(data, HEAD)
        self.assertEqual(outcome['evidence_status'], 'REJECTED')
        self.assertGreaterEqual(len(outcome['blockers']), 3)

    def test_missing_real_model_forward_proof_is_not_api_call(self):
        data = receipt()
        data['evidence']['instrumentation'] = {'level': 'sentence_transformer_encode_api',
                                                 'backend_forward_count_observed': False}
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')

    def test_future_or_ood_holdout_must_be_independent(self):
        data = receipt()
        data['evidence']['splits']['ood'] = data['evidence']['splits']['train']
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')

    def test_physical_fanout_and_all_six_scales_required(self):
        data = receipt()
        data['evidence']['scale_measurements'][3]['encoder_forward_calls'] = 256
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')
        data = receipt()
        data['evidence']['scale_measurements'].pop()
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')
        data = receipt()
        data['evidence']['scale_measurements'][0]['private_backbone_bytes'] = 1
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')

    def test_invalid_measures_and_non_finite_metrics_rejected(self):
        data = receipt()
        data['metrics']['calibration_error'] = float('nan')
        data['evidence']['scale_measurements'][0]['p99_ms'] = 1
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')

    def test_ci_pending_cancelled_and_stale_head_rejected(self):
        for field, value in (('status','queued'),('conclusion','cancelled'),
                             ('head_sha','e'*40)):
            with self.subTest(field=field):
                data = receipt()
                data['ci'][field] = value
                self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')

    def test_authority_smuggling_and_extra_fields_rejected(self):
        data = receipt()
        data['production_activation_allowed'] = True
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')
        data = receipt()
        data['runtime_posture']['authority'] = 'GRANT_ALL'
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')

    def test_wrong_structures_and_metric_booleans_rejected(self):
        data = receipt()
        data['metrics']['task_utility'] = True
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')
        data = receipt()
        data['ci']['run_id'] = True
        self.assertEqual(assess(data, HEAD)['evidence_status'], 'REJECTED')
        self.assertEqual(assess(None, HEAD)['evidence_status'], 'REJECTED')


if __name__ == '__main__':
    unittest.main()
