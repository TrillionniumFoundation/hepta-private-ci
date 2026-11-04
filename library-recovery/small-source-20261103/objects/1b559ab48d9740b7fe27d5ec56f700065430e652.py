"""Exact original frozen-feature exploratory balanced 4145 Head tests, no TEST labels."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import os
import unittest

from actual_feature_head_shadow_v1 import Invalid
from train_only_balanced_head_v1 import train_only_pos_weight,run_balanced,SCHEMA

ROOT=Path(os.environ.get('HEPTA_ORIGINAL_ARTIFACT_ROOT',str(Path(__file__).resolve().parent)))
RECEIPT=Path(__file__).resolve().parent/'shadow_result.json'


class BalancedHeadOriginalSourceChecks(unittest.TestCase):
    def test_source_label_ratio_exact(self):
        self.assertEqual(train_only_pos_weight([0]*59+[1]*32),59/32)

    def test_both_classes_required(self):
        for labels in ([0]*91,[1]*91,[]):
            with self.subTest(labels=labels[:1]), self.assertRaises(Invalid):
                train_only_pos_weight(labels)

    def test_only_exact_binary_training_labels(self):
        for labels in ([0]*31+[1]*58+[2],[0]*31+[1]*58+[True],
                       [0]*31+[1]*58+[None], [0]*2+[1]*3):
            with self.subTest(invalid=str(labels[-1])),self.assertRaises(Invalid):
                train_only_pos_weight(labels)

    def test_shadow_source_integrity_required(self):
        with self.assertRaises(Invalid):run_balanced(ROOT,{'schema':'fake'})

    @classmethod
    def setUpClass(cls):
        cls.results=run_balanced(ROOT,json.loads(RECEIPT.read_text()))

    def test_actual_training_count_equal_budget(self):
        for name,model in self.results['models'].items():
            self.assertEqual(len(model['arms']),6)
            self.assertEqual(model['original_train_positive_count'],32)
            self.assertEqual(model['original_train_negative_count'],59)
            self.assertTrue(model['only_train_labels_in_gradient'])
            self.assertEqual(model['new_foundation_encoder_forwards'],0)
            for arm in model['arms']:
                self.assertEqual(arm['parameter_count'],4145)
                self.assertEqual(arm['optimizer_steps'],40)
                self.assertEqual(arm['train_only_positive_class_weight'],59/32)
                self.assertEqual(arm['calibration_actual_positive_count'],16)

    def test_source_prefix_stays_partial_no_selection(self):
        r=self.results
        self.assertEqual(r['schema'],SCHEMA)
        self.assertEqual(r['authority'],'DENY_ALL')
        self.assertFalse(r['original_four_model_admission_passed'])
        self.assertFalse(r['original_human_held_labels_accessed'])
        self.assertFalse(r['production_promotion_permitted'])
        self.assertFalse(r['model_selected'])
        self.assertTrue(r['calibration_metrics_not_independent_future_test'])

    def test_class_reweighting_does_not_claim_robust_improvement(self):
        r=self.results
        all_accuracies=[]
        for model in r['models'].values():
            a=[x['calibration_accuracy_not_independent_test'] for x in model['arms']]
            all_accuracies.extend(a)
            self.assertGreater(max(a),.5)
            self.assertLess(max(a),.7)
            for arm in model['arms']:
                self.assertTrue(0<=arm['calibration_brier_not_independent_test']<=1)
        self.assertLess(min(all_accuracies),.5)

    def test_no_held_accuracy_or_case_labels_in_receipt(self):
        text=json.dumps(self.results)
        for name in ('test_accuracy','human_held_label_values',
                     'test_predictions_scored','test_winner','test_case_id'):
            self.assertNotIn(name,text)


if __name__=='__main__':unittest.main()
