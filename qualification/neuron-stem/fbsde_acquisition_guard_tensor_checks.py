"""Actual encoding, fitting and calibrated routing on explicit synthetic fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from four_gate_common import digest
from fbsde_acquisition_study import run
from fbsde_acquisition_audit import audit
from fbsde_acquisition_data import TRAVEL_INTENTS
from fbsde_acquisition_support import SUPPORTED_KERNEL


class GuardTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)/'run'
        cls.parts={}
        for split,n in (('fit',3),('kernel',4),('selection',1),('validation',2),('test',2)):
            cls.parts[split]=[]
            for label,intent in enumerate(TRAVEL_INTENTS):
                for i in range(n):
                    text=f'please {intent} for this request fixture {split} {i}'
                    cls.parts[split].append({'id':f'{split}-{label}-{i}', 'text':text,
                        'text_sha256':digest(text),'label':label})
        with patch('fbsde_acquisition_study.load_publisher',return_value={}), \
             patch('fbsde_acquisition_study.partition',return_value=cls.parts):
            cls.result=run(cls.root, kernel_profile=SUPPORTED_KERNEL,cohort='travel_guard_v1')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_complete_chain_keeps_all_controls_and_abstains_without_support(self):
        self.assertEqual(len(self.result['metrics']),13)
        self.assertEqual(self.result['metrics']['risk_selected']['answered'],0)
        self.assertIsNone(self.result['metrics']['risk_selected']['accepted_error'])
        self.assertFalse(self.result['production_promotion_permitted'])
        self.assertFalse(self.result['validation_not_used_for_selection'])

    def test_arithmetic_reconstructs_calibration_and_actual_view_attempts(self):
        self.assertTrue(audit(self.root,self.parts)['original_arithmetic_recomputed'])
        plan=json.loads((self.root/'plan.json').read_text())
        self.assertEqual(plan['prediction_cpu_limit_ns'],100_000_000)
        self.assertFalse((self.root/'validation-risk_selected.jsonl').exists())
        self.assertTrue((self.root/'risk-calibration.json').is_file())

    def test_edited_risk_winner_rejected(self):
        p=self.root/'risk-calibration.json'; raw=p.read_bytes()
        try:
            d=json.loads(raw);d['selected']='full_symbol';p.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,'winner'):audit(self.root,self.parts)
        finally:p.write_bytes(raw)

    def test_counterfeit_zero_risk_bound_rejected(self):
        p=self.root/'risk-calibration.json';raw=p.read_bytes()
        try:
            d=json.loads(raw);d['profiles']['ndu_bsde']['accepted_error_ucb']=0.;p.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,'bound'):audit(self.root,self.parts)
        finally:p.write_bytes(raw)

    def test_wrong_cohort_decoder_rejected(self):
        p=self.root/'plan.json';raw=p.read_bytes()
        try:
            d=json.loads(raw);d['intents'].reverse();p.write_text(json.dumps(d))
            with self.assertRaisesRegex(ValueError,'mapping'):audit(self.root,self.parts)
        finally:p.write_bytes(raw)
