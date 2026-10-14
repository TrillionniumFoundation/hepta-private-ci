"""Pure numerical audit contract fixtures; never pretrained-model evidence."""
import copy
import unittest

from public_agnews_panel import select_rows
from agnews_paired_shadow import check_panel, compare, _bound_report, _row
from paired_independent_audit import ReviewError, canonical, sha, verify


def trial():
    tr = [{'text': f'Training report about topic {i%2} case {i}', 'label': i%2}
          for i in range(160)]
    ho = [{'text': f'Holdout report about topic {i%2} case {i}', 'label': i%2}
          for i in range(160)]
    panel = select_rows(tr, ho)
    digest, groups = check_panel(panel)
    receipt = {
        'schema': 'hepta.stem.agnews-input-receipt.v1',
        'panel_digest': digest, 'source_sha256': panel['dataset_file_sha256'],
        'counts_by_split_label': {
            f'{split}/{label}': sum(row['split'] == split and row['label'] == label
                                   for row in panel['cases'])
            for split in ('train', 'calibration', 'test') for label in (0, 1)
        },
        'future_longitudinal_evidence': False,
        'physical_model_weights_executed': False,
        'external_source_signer_authenticated': False,
        'production_promotion': 'DENY_ALL',
    }
    rows = [_row(c, 0.7 if c['label'] == 1 else 0.3, 100)
            for kind in ('calibration', 'test') for c in groups[kind]]
    gemma = []
    for arm, steps, artifact in (('gemma2_frozen_head', 0, 'a' * 64),
                                 ('gemma2_trained_head', 40, 'b' * 64)):
        gemma.append(_bound_report(digest, arm, copy.deepcopy(rows),
            backend='google/embeddinggemma-2',
            revision='914f7f89142e33e77833254d9c9b90c3cef7303b',
            stem_digest='c'*64, optimizer_steps=steps,
            local_head_train_micros=300 if steps else 0,
            head_parameters=2048, head_artifact_digest=artifact,
            model_encode_api_calls=28,
            cpu_batch_wall_allocation='equal_shared_batch_wall_amortized_not_direct_latency'))
    laya = _bound_report(digest, 'laya421_frozen', copy.deepcopy(rows),
        backend='convaiinnovations/laya',
        revision='55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851',
        trainable_parameters=0, pretrained_checkpoint_verified_by_loader=True,
        model_parameter_count=421_000_000)
    comparison = compare(panel, [*gemma, laya])
    return [panel, receipt, gemma, laya, comparison]


class Audit(unittest.TestCase):
    def test_numeric_review_recomputes_all_model_slices_without_authority(self):
        result = verify(*trial())
        self.assertEqual(result['case_count'], 224)
        self.assertEqual(result['paired_scored_cases'], 96)
        self.assertEqual(result['production_promotion'], 'DENY_ALL')
        self.assertTrue(result['numeric_and_case_integrity_verified'])
        self.assertFalse(result['independent_source_label_authentication'])
        self.assertFalse(result['future_longitudinal_learning_proven'])
        self.assertEqual(result['metrics']['test']['laya421_frozen']['accuracy'], 1.0)
        self.assertAlmostEqual(result['metrics']['test']['laya421_frozen']['brier'], 0.09)
        self.assertTrue(all(len(d) == 64 for d in result['report_digests'].values()))

    def test_corrupted_owner_source_or_labels_rejected(self):
        for kind in ('source_hash', 'source_claim', 'label', 'input'):
            values = trial()
            if kind == 'source_hash':
                values[1]['panel_digest'] = '0'*64
            elif kind == 'source_claim':
                values[1]['future_longitudinal_evidence'] = True
            elif kind == 'label':
                values[0]['cases'][0]['label'] = 17
            else:
                values[0]['cases'][0]['joint_input']['state'] = 'changed source'
            with self.subTest(kind=kind), self.assertRaises(ReviewError):
                verify(*values)

    def test_tampered_prediction_or_fake_equal_cost_rejected(self):
        for kind in ('drop', 'input_digest', 'metric', 'model_origin', 'equal_cost',
                     'revision', 'reordered', 'modified_frozen', 'not_trained'):
            values = trial()
            if kind == 'drop':
                values[2][0]['rows'].pop()
            elif kind == 'input_digest':
                values[2][0]['rows'][0]['joint_input_digest'] = '0'*64
            elif kind == 'metric':
                values[4]['windows']['test']['laya421_frozen']['accuracy'] = 0.0
            elif kind == 'model_origin':
                values[2][0]['model_execution_independently_attested'] = True
            elif kind == 'equal_cost':
                values[4]['matched_full_lifecycle_cost'] = True
            elif kind == 'revision':
                values[3]['metadata']['revision'] = 'f'*40
            elif kind == 'reordered':
                values[2][0]['rows'][1] = copy.deepcopy(values[2][0]['rows'][0])
            elif kind == 'modified_frozen':
                values[2][0]['metadata']['optimizer_steps'] = 40
            else:
                values[2][1]['metadata']['head_artifact_digest'] = 'a'*64
            with self.subTest(kind=kind), self.assertRaises(ReviewError):
                verify(*values)

    def test_reports_are_order_independent_not_label_independent(self):
        values = trial()
        base = verify(*values)
        values[2][0]['rows'].reverse()
        values[3]['rows'].reverse()
        checked = verify(*values)
        self.assertEqual(base['metrics'], checked['metrics'])
        self.assertEqual(base['panel_digest'], checked['panel_digest'])
        self.assertNotEqual(base['report_digests'], checked['report_digests'])

    def test_undocumented_or_nonfinite_probability_rejected(self):
        for value in (float('nan'), float('inf'), -0.1, 1.1, True):
            cases = trial()
            cases[3]['rows'][0]['prob_sports'] = value
            with self.subTest(probability=str(value)), self.assertRaises(ReviewError):
                verify(*cases)


if __name__ == '__main__':
    unittest.main()
