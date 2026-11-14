"""Source-constrained public retrospective sensitivity and strict negative tests."""
from __future__ import annotations
import json
import os
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import e1_original_paired_threshold_review_v2 as m

ORIGINAL = Path(os.environ.get('HEPTA_ORIGINAL_E1_ZIP', '/mnt/data/hepta_e1_original_two_38893928466.zip'))


class PairedOriginalExperiment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ORIGINAL.is_file():
            raise FileNotFoundError('original GitHub ZIP REQUIRED; never skip source validation')
        cls.report = m.review_source(ORIGINAL)

    def test_precise_original_two_model_source_identity(self):
        r = self.report
        self.assertEqual(r['original_github_artifact_id'], 12046289415)
        self.assertEqual(r['original_artifact_zip_sha256'], m.ancestry.ZIP_SHA256)
        self.assertEqual(set(r['models']), set(m.MODELS))
        self.assertFalse(r['complete_three_model_study_qualified'])
        self.assertFalse(r['production_model_winner_selected'])
        self.assertEqual(r['authority'], 'DENY_ALL')

    def test_old_public_dataset_not_future_or_hidden(self):
        r = self.report
        self.assertEqual(r['label_population']['test'], 64)
        self.assertTrue(r['label_population']['test_labels_seen_by_original_producer'])
        self.assertTrue(r['result_is_retrospective_public_cross_section_not_hidden_or_future'])
        self.assertFalse(r['independent_semantic_future_test_verified'])
        self.assertFalse(r['negative_transfer_checked'])
        self.assertEqual(r['retrospective_fixed_thresholds_not_originally_preregistered'],[0.49,0.50,0.51])
        self.assertTrue(r['cosine_prototypes_use_train_labels_not_no_change'])
        self.assertTrue(r['frozen_linear_head_is_random_control_not_model_native_policy'])
        self.assertFalse(r['model_encoder_weight_bytes_independently_replayed_here'])

    def test_exact_equal_trained_accuracy_but_not_same_errors(self):
        r = self.report
        for model in m.MODELS:
            self.assertEqual(r['models'][model]['test_arms']['from_zero']['correct'],61)
        d = r['paired_model_comparisons']['from_zero']
        self.assertEqual((d['a_only_correct'],d['b_only_correct']), (2,2))
        self.assertEqual((d['both_correct'],d['both_wrong']), (59,1))
        self.assertEqual(d['nominal_two_sided_exact_discordant_p'], 1.0)

    def test_original_cosine_numerical_controls(self):
        self.assertEqual(self.report['models']['granite_97m_r2']['test_arms']['cosine_prototype']['correct'],62)
        self.assertEqual(self.report['models']['embeddinggemma_2_text']['test_arms']['cosine_prototype']['correct'],60)
        d = self.report['paired_model_comparisons']['cosine_prototype']
        self.assertEqual((d['a_only_correct'],d['b_only_correct']), (2,0))
        self.assertAlmostEqual(d['nominal_two_sided_exact_discordant_p'],.5)

    def test_both_frozen_and_residual_controls_at_chance(self):
        for model in m.MODELS:
            t = self.report['models'][model]['test_arms']
            for arm in ('frozen_head','residual_2k','residual_8k','residual_16k'):
                self.assertEqual(t[arm]['correct'],32)

    def test_recorded_trained_threshold_sensitivity(self):
        a = self.report['models']['granite_97m_r2']['test_arms']['from_zero']['accuracy_by_fixed_threshold']
        b = self.report['models']['embeddinggemma_2_text']['test_arms']['from_zero']['accuracy_by_fixed_threshold']
        self.assertEqual([a[t] for t in ('0.49','0.50','0.51')],[55/64,61/64,62/64])
        self.assertEqual([b[t] for t in ('0.49','0.50','0.51')],[55/64,61/64,61/64])

    def test_conditional_binomial_interval_cannot_be_claimed_target_coverage(self):
        a = self.report['models']['granite_97m_r2']['test_arms']['from_zero']
        self.assertAlmostEqual(a['conditional_iid_binomial_95_interval'][0],.8691,places=3)
        self.assertAlmostEqual(a['conditional_iid_binomial_95_interval'][1],.9902,places=3)
        self.assertTrue(self.report['confidence_intervals_require_iid_unselected_test_samples_not_proved'])

    def test_empty_full_or_balanced_binomial_interval(self):
        self.assertEqual(m.clopper_pearson(0,64)[0],0)
        self.assertEqual(m.clopper_pearson(64,64)[1],1)
        a,b = m.clopper_pearson(32,64)
        self.assertTrue(.37<a<.38 and .62<b<.63)

    def test_exact_discordant_p_known_small_counts(self):
        self.assertEqual(m.exact_discordant_p(0,0),1)
        self.assertEqual(m.exact_discordant_p(2,2),1)
        self.assertEqual(m.exact_discordant_p(0,10),2/1024)
        self.assertEqual(m.exact_discordant_p(1,3),.625)

    def test_bad_pair_counts_or_binomial_inputs_fail(self):
        for x,y in ((-1,0),(0,-1),(65,0),(True,0),(1.1,0)):
            with self.subTest(x=x,y=y), self.assertRaises(m.Invalid):m.exact_discordant_p(x,y)
        for n,k in ((0,0),(65,64),(-1,-1)):
            with self.subTest(n=n,k=k), self.assertRaises(m.Invalid):m.clopper_pearson(k,n)

    def test_unknown_duplicate_or_unbound_original_test_case_denied(self):
        cases={'a':{'split':'test','joint_input_digest':'z'},'b':{'split':'test','joint_input_digest':'y'}}
        rows=[{'case_id':'a','split':'test','joint_input_digest':'z','positive_probability':.6},
              {'case_id':'b','split':'test','joint_input_digest':'y','positive_probability':.4}]
        with mock.patch.object(m.ancestry,'SPLITS',{'test':2}):
            self.assertEqual(m.strict_test_predictions(rows,cases),{'a':.6,'b':.4})
            with self.assertRaises(m.Invalid):m.strict_test_predictions(rows[:1],cases)
            with self.assertRaises(m.Invalid):m.strict_test_predictions(rows[:1]+rows[:1],cases)
            with self.assertRaises(m.Invalid):m.strict_test_predictions(rows[:1]+[dict(rows[1],case_id='x')],cases)
            with self.assertRaises(m.Invalid):m.strict_test_predictions(rows[:1]+[dict(rows[1],joint_input_digest='tampered')],cases)

    def test_boolean_nan_infinite_probabilities_denied(self):
        for p in (True,False,float('nan'),float('inf'),-0.1,1.1,None):
            self.assertFalse(m.is_probability(p))
            with self.subTest(p=p),self.assertRaises(m.Invalid):m.classify_scores({'c':p},{'c':0})

    def test_pairing_requires_exact_identity_and_bool_outcomes(self):
        with self.assertRaises(m.Invalid):m.paired({'x':True},{'y':True})
        with self.assertRaises(m.Invalid):m.paired({'x':1},{'x':True})
        d = m.paired({'x':True,'y':False},{'x':False,'y':True})
        self.assertEqual((d['a_only_correct'],d['b_only_correct']), (1,1))

    def test_repacked_altered_original_zip_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'repacked.zip'
            with zipfile.ZipFile(target,'w') as z:
                z.writestr('e1-public/panel.json', '{}')
            with self.assertRaises(m.ancestry.Invalid):m.review_source(target)

    def test_no_case_text_or_identifiers_in_aggregate_receipt(self):
        receipt = json.dumps(self.report,sort_keys=True)
        original = m.ancestry.strict_original_artifact(ORIGINAL)
        panel = m.ancestry.strict_json(original['e1-public/panel.json'])
        self.assertNotIn(panel['cases'][0]['case_id'],receipt)
        self.assertNotIn(panel['cases'][0]['joint_input']['state'],receipt)
        self.assertEqual(self.report['unavailable_model']['model'],'mmbert_small')

    def test_safe_create_only_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory)/'receipt.json'
            with mock.patch('sys.argv',['prog','--original-run-zip',str(ORIGINAL),'--output',str(destination)]):
                m.main()
            self.assertEqual(json.loads(destination.read_text())['authority'],'DENY_ALL')
            with mock.patch('sys.argv',['prog','--original-run-zip',str(ORIGINAL),'--output',str(destination)]):
                with self.assertRaises(FileExistsError):m.main()


if __name__ == '__main__':unittest.main()
