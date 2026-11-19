"""Paired outcome and full-cost evidence negative admissions."""
from __future__ import annotations
import copy
import math
import unittest

from paired_utility_gate import _mcnemar_exact, audit_paired_utility
from physical_bank import Denied, train
from test_physical_bank import original
from test_modernbert_feature_bridge import prepared, stage_original, fake_feature_bundle, fake_receipt
from modernbert_feature_bridge import review_original


class PairedUtilityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.labels = original()
        cls.trial = train(cls.bundle)
        cls.audit = audit_paired_utility(cls.bundle, cls.trial, cls.labels)

    def test_complete_original_synthetic_paired_denominator(self):
        a = self.audit
        self.assertEqual(a['matched_case_census'], 32)
        self.assertEqual(a['source_partition_families_present'], ['test-C'])
        self.assertEqual(a['independent_publisher_source_families_verified'], 0)
        self.assertEqual(a['observed_prospective_future_windows'], 0)
        self.assertEqual(a['disposition'], 'HOLD_NO_GO')
        self.assertFalse(a['qualifying_task_benefit'])
        self.assertFalse(a['ndu_incremental_net_utility_verified'])
        self.assertFalse(a['production_authorized'])
        self.assertIsNone(a['observed_full_encoder_plus_reader_training_tco'])

    def test_paired_synthetic_route_control(self):
        pairs = self.audit['nominal_case_level_pairs']
        self.assertEqual(pairs['split']['paired_questions'], 32)
        self.assertEqual(pairs['split']['candidate_only_correct'], 16)
        self.assertEqual(pairs['split']['baseline_only_correct'], 0)
        self.assertEqual(pairs['swapped']['candidate_only_correct'], 0)
        self.assertEqual(pairs['swapped']['baseline_only_correct'], 16)
        for row in pairs.values():
            self.assertEqual(sum(row[k] for k in ('candidate_only_correct','baseline_only_correct',
                           'both_correct','neither_correct')), 32)
            self.assertFalse(row['statistical_superiority_certified'])

    def test_exact_binomial_discordance_and_no_discordance(self):
        self.assertEqual(_mcnemar_exact(0, 0), 1.0)
        self.assertEqual(_mcnemar_exact(16, 0), 2 ** -15)
        self.assertAlmostEqual(_mcnemar_exact(10, 4), 0.1795654296875)
        self.assertEqual(_mcnemar_exact(4, 10), _mcnemar_exact(10, 4))
        self.assertTrue(0 <= _mcnemar_exact(512, 512) <= 1)

    def test_charges_all_training_arms_even_when_wrong(self):
        paid = self.audit['charged_known_work']
        self.assertEqual(paid['physical_head_train_sgd_updates'], 768)
        self.assertEqual(paid['estimated_head_parameter_touches'], 2560 + 1280 + 1280)
        self.assertGreater(paid['reported_cpu_ns_unattested'], 0)
        self.assertFalse(self.audit['nominal_case_level_pairs']['split']['statistical_superiority_certified'])

    def test_tamper_individual_prediction_or_head_digest_denied(self):
        for kind in ('prediction', 'weight', 'cost', 'identity'):
            trial = copy.deepcopy(self.trial)
            if kind == 'prediction':
                trial['predictions']['split'][0]['p1'] = 0.0
            elif kind == 'weight':
                trial['arms']['shared_dense']['weights_digest'] = 'a'*64
            elif kind == 'cost':
                trial['arms']['split']['actual_sgd_steps'] = 1
            else:
                trial['trial_identity'] = 'b'*64
            with self.subTest(kind=kind), self.assertRaises(Denied):
                audit_paired_utility(self.bundle, trial, self.labels)

    def test_target_scope_or_label_type_denied(self):
        for which in ('type', 'id', 'missing', 'duplicate'):
            labels = copy.deepcopy(self.labels)
            if which == 'type':
                labels['targets'][0]['type'] = 'other'
            elif which == 'id':
                labels['targets'][0]['id'] = 'wrong-case'
            elif which == 'missing':
                labels['targets'].pop()
            else:
                labels['targets'][0] = copy.deepcopy(labels['targets'][1])
            with self.subTest(which=which), self.assertRaises(Denied):
                audit_paired_utility(self.bundle, self.trial, labels)

    def test_actual_model_review_consumes_new_no_go_science(self):
        inputs, observer, selection = prepared()
        pub, priv = stage_original(inputs, observer, selection)
        bundle = fake_feature_bundle(pub)
        trial = train(bundle, steps=24)
        review = review_original(pub, priv, bundle, fake_receipt(pub, bundle), trial, expected_steps=24)
        self.assertIn('paired_science_gate', review)
        gate = review['paired_science_gate']
        self.assertEqual(gate['disposition'], 'HOLD_NO_GO')
        self.assertEqual(gate['matched_case_census'], 32)
        self.assertEqual(gate['charged_known_work']['physical_head_train_sgd_updates'], 72)
        self.assertFalse(gate['physical_cell_split_authorized'])


if __name__ == '__main__':
    unittest.main()
