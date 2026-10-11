"""Actual Torch V2 training/inference; fixture vectors are not pretrained results."""
import json
from pathlib import Path
import tempfile
import unittest
import torch
from fbsde_encoder import train_and_compare
from fbsde_design import INDEPENDENT
from fbsde_audit import recompute_comparison
from four_gate_common import digest


class IndependentQuestionTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.output=Path(cls.temp.name)
        cls.parts={};features={};torch.set_num_threads(2);torch.manual_seed(130363)
        for split in ('train','validation','calibration','test'):
            cls.parts[split]=[]
            for i in range(32):
                uid=f'{split}:{i}';label=i%4
                cls.parts[split].append({'id':uid,'intent':label,'source_sha256':digest(uid)})
                v=torch.randn(384)*.01;v[label]=2.;features[uid]=v
        cls.report=train_and_compare(torch,cls.parts,features,cls.output,130363,profile=INDEPENDENT)
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_full_versioned_runner_and_independent_arithmetic(self):
        audit=recompute_comparison(self.output,self.parts)
        self.assertEqual(audit['cases'],192)
        self.assertEqual(len(audit['metrics']),9)
        self.assertTrue(audit['cpu_envelope_reconciled'])
        self.assertFalse(audit['scientific_superiority_established'])

    def test_no_text_baseline_has_no_semantic_training_charge(self):
        self.assertEqual(self.report['adaptation_plus_inference_cpu_ns']['syntax_prior'],
                         self.report['inference_cpu_ns']['syntax_prior'])
        self.assertTrue(self.report['standalone_costs_are_lower_bounds'])

    def test_changed_decoded_text_is_rejected(self):
        path=self.output/'light_head-predictions.json';original=path.read_bytes()
        try:
            rows=json.loads(original);rows[0]['text']='Invented conclusion.'
            path.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'faithful'):
                recompute_comparison(self.output,self.parts)
        finally: path.write_bytes(original)

    def test_fake_cpu_total_is_rejected(self):
        path=self.output/'comparison.json';original=path.read_bytes()
        try:
            row=json.loads(original);row['study_cpu_envelope_ns']+=1
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError,'envelope'):
                recompute_comparison(self.output,self.parts)
        finally:path.write_bytes(original)

    def test_publisher_label_drift_is_rejected(self):
        altered={k:[dict(x) for x in rows] for k,rows in self.parts.items()}
        for row in altered['test']: row['intent']=(row['intent']+1)%4
        with self.assertRaisesRegex(ValueError,'publisher labels'):
            recompute_comparison(self.output,altered)

    def test_syntax_prior_cannot_use_a_different_probability_law(self):
        path=self.output/'syntax_prior-predictions.json';original=path.read_bytes()
        try:
            rows=json.loads(original);rows[0]['probability']=.9
            rows[0]['text']='Yes, the stated condition is satisfied.'
            path.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'syntax prior'):
                recompute_comparison(self.output,self.parts)
        finally:path.write_bytes(original)

    def test_belief_model_identity_cannot_be_relabelled(self):
        path=self.output/'belief-inputs.json';original=path.read_bytes()
        try:
            data=json.loads(original);next(iter(data.values()))['semantic_sha256']=digest('other-model')
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'semantic identity'):
                recompute_comparison(self.output,self.parts)
        finally:path.write_bytes(original)

    def test_source_reuse_not_iid_evidence(self):
        census=self.report['source_census']
        self.assertEqual(census['source_connected_components'],1)
        self.assertEqual(census['cases'],192)
        self.assertFalse(census['iid_case_confidence_intervals_permitted'])

if __name__=='__main__': unittest.main()
