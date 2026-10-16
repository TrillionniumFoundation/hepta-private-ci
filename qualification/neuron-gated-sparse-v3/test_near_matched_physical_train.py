"""Synthetic-mechanism checks, not a claim of a passing Rust native experiment."""
from __future__ import annotations
from argparse import Namespace
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from near_matched_physical_fixture import generate
from near_matched_physical_train import train
from near_matched_physical_native_oracle import product, adapter, physically_load, verify
from matched_train import unique_json
from near_matched_capacity_design import choose

Q=1<<24

# The fast A0 protocol job has intentionally no Tensor framework.  It must
# still discover this suite, but only the separately pinned CPU Torch jobs may
# exercise physical weights and create the eight artifacts.
@unittest.skipUnless(
    os.environ.get("HEPTA_NEURON_PHYSICAL_TESTS") == "1",
    "physical Torch/safetensors suite runs in the dedicated pinned CPU job only",
)
class NearMatchedPhysicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        cls.inputs=cls.root/'inputs'
        cls.claim=generate(cls.inputs)
        cls.weights=cls.root/'models'
        cls.report=train(Namespace(
            train_data=cls.inputs/'train.json',
            train_sha256=cls.claim['train_sha256'],
            output=cls.weights, steps=2, seed=20261015, synthetic_canary=True,
        ))
        cls.trace=unique_json((cls.inputs/'trace.json').read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_physical_census_and_no_promotion(self):
        self.assertEqual(self.report['physical_model_file_count'],8)
        self.assertEqual(len(self.report['cells']),8)
        self.assertFalse(self.report['original_selected_v1_a0_verified'])
        self.assertFalse(self.report['real_shared_encoder_forward_invoked'])
        self.assertFalse(self.report['native_Q24_adapter_head_executed'])
        self.assertFalse(self.report['production_qualification'])
        for row in self.report['cells']:
            chosen=choose(32,row['arm'],row['cap'],max_rank=4)
            self.assertEqual(row['complete_realized_parameters'],
                             chosen['complete_proposed_private_parameters'])
            self.assertTrue(row['complete_realized_parameters']<=row['cap'])
            self.assertLessEqual((row['cap']-row['complete_realized_parameters'])*1000000,
                                 20000*row['cap'])
            self.assertEqual(row['optimizer_steps'],2)

    def test_all_eight_byte_verified_safetensors_reloaded(self):
        for row in self.report['cells']:
            tensors=physically_load(self.weights,row)
            self.assertIn('adapter.weight',tensors)
            self.assertIn('head.weight',tensors)
            self.assertEqual(tensors['adapter.weight'].shape[1],32)
            self.assertEqual(tensors['adapter.weight'].shape[0],row['hidden_width'])

    def test_independent_integer_adapter_on_physical_weight_bytes(self):
        row=self.report['cells'][0]
        tensors=physically_load(self.weights,row)
        event=self.trace['events'][0]
        o,p=adapter(event['temporal_drive_q24'],event['prediction_q24'],
                    tensors,row['hidden_width'])
        self.assertEqual(len(o),row['hidden_width'])
        self.assertEqual(p,[0]*row['hidden_width'])

    def test_ties_even_signed_q24(self):
        self.assertEqual(product(1,Q//2),0)
        self.assertEqual(product(3,Q//2),2)
        self.assertEqual(product(-3,Q//2),-2)
        self.assertEqual(product(-5,Q//2),-2)
        self.assertEqual(product(Q,Q//4),Q//4)

    def test_absent_live_A0_must_reject(self):
        args=Namespace(train_data=self.inputs/'train.json',
                       train_sha256=self.claim['train_sha256'],
                       output=self.root/'forbidden',steps=1,seed=2,
                       synthetic_canary=False)
        with self.assertRaises(ValueError):
            train(args)
        self.assertFalse(args.output.exists())

    def test_tampered_sha_rejects_instead_of_retraining(self):
        row=copy.deepcopy(self.report['cells'][0])
        row['weight_sha256']='0'*64
        with self.assertRaises(ValueError):
            physically_load(self.weights,row)

    def test_native_claim_must_not_be_inferred_from_fake_receipt(self):
        row=self.report['cells'][0]
        tensors=physically_load(self.weights,row)
        bad={'schema':'hepta.neuron.near-matched-native-adapter-replay.v1',
             'arm':row['arm'],
             'production_qualification':True}
        with self.assertRaises(ValueError):
            verify(bad,self.trace,row,tensors,self.claim['trace_sha256'])

    def test_native_adapter_cannot_be_claimed_from_producer(self):
        self.assertEqual(self.report['decision'],'NO_MODEL_PROMOTION')
        self.assertFalse(self.report['future_utility_verified'])
        self.assertFalse(self.report['equal_training_FLOPs_verified'])

    def test_fixture_data_source_is_explicitly_synthetic(self):
        training=unique_json((self.inputs/'train.json').read_bytes())
        self.assertEqual(training['cell_id'],'synthetic-near-match-cell-only')
        self.assertEqual(len(training['samples']),32)
        self.assertEqual(self.claim['source_kind'],'SYNTHETIC_ONLY')

    def test_create_only_training_output(self):
        args=Namespace(train_data=self.inputs/'train.json',
                       train_sha256=self.claim['train_sha256'],
                       output=self.weights,steps=1,seed=3,
                       synthetic_canary=True)
        with self.assertRaises(FileExistsError):
            train(args)

if __name__=='__main__':
    unittest.main()
