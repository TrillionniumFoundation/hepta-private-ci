#!/usr/bin/env python3
"""Synthetic negative cases: these NEVER establish actual Hepta learning efficacy."""
import argparse
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from matched_train import training_input, rank_for_budget, require_selected_owner_a0, Q, SCHEMA, sha_bytes
from precommit_future import future_data, binary_metrics, score


def at(day: int, second: int = 0) -> str:
    return (datetime(2026, 10, day, tzinfo=timezone.utc) + timedelta(seconds=second)).isoformat().replace('+00:00','Z')


def sample(i: int, grp='train') -> dict:
    return {'case_id':f'row-{grp}-{i}', 'source_group':grp, 'sequence':i,
            'event_time_utc':at(1,i),'feature_q24':[Q//2]*16,'label':i%2}


def train_fixture() -> dict:
    return {'schema':SCHEMA, 'encoder_digest':'1'*64,'cell_id':'fixture',
            'train_cutoff_utc':at(2),'samples':[sample(1),sample(2)]}


class TestInputAndBudgets(unittest.TestCase):
    def test_train_admits_only_chronological_binary_q24(self):
        width, groups = training_input(train_fixture())
        self.assertEqual((width,len(groups)), (16,1))

    def test_no_future_label_or_extra_fields(self):
        x=train_fixture();x['samples'][0]['future_label']=1
        with self.assertRaisesRegex(ValueError,'wrong|unrecognized'):
            training_input(x)

    def test_train_cutoff_and_clock_enforced(self):
        x=train_fixture();x['samples'][1]['event_time_utc']=at(3)
        with self.assertRaisesRegex(ValueError,'cutoff'):
            training_input(x)
        x=train_fixture();x['samples'][1]['event_time_utc']=at(1,-1)
        with self.assertRaisesRegex(ValueError,'clock'):
            training_input(x)

    def test_q24_dimension_and_label(self):
        x=train_fixture();x['samples'][0]['feature_q24']=[9*Q]*16
        with self.assertRaisesRegex(ValueError,'Q24'):
            training_input(x)
        x=train_fixture();x['samples'][0]['label']=True
        with self.assertRaisesRegex(ValueError,'label'):
            training_input(x)

    def test_live_selected_v1_a0_required_outside_fixture(self):
        with self.assertRaisesRegex(ValueError, 'A0 signed live owner'):
            require_selected_owner_a0(argparse.Namespace(synthetic_canary=False),
                                      'fixture', '1'*64)
        result=require_selected_owner_a0(argparse.Namespace(synthetic_canary=True),
                                         'fixture', '1'*64)
        self.assertEqual(result['evidence_class'],'SYNTHETIC_FIXTURE_ONLY')

    def test_min_gru_budget_counts_entire_private_profile(self):
        self.assertEqual(rank_for_budget(128,2048), 2)
        with self.assertRaisesRegex(ValueError,'cannot fit'):
            rank_for_budget(256,2048)
        self.assertTrue(1<=rank_for_budget(128,262144)<=128)

    def test_future_without_labels_and_source_group_isolation(self):
        rc={'encoder_digest_claimed':'1'*64,'cell_id':'fixture','training_cutoff_utc':at(2),
            'models':[{'width':16}], 'train_source_group_hashes':[sha_bytes(b'train')]}
        rows=[{'case_id':f'fu-{i}','source_group':f'new{i}','sequence':1,
               'event_time_utc':at(3,i),'feature_q24':[0]*16,
               'partition':('future' if i==0 else 'ood')} for i in range(2)]
        data={'schema':'hepta.neuron.unlabelled-future-q24.v1',
              'encoder_digest':'1'*64,'cell_id':'fixture','samples':rows}
        self.assertEqual(len(future_data(data,rc)[1]),2)
        rows[0]['label']=1
        with self.assertRaisesRegex(ValueError,'wrong fields'):
            future_data(data,rc)
        rows[0].pop('label');rows[0]['source_group']='train'
        with self.assertRaisesRegex(ValueError,'crossed'):
            future_data(data,rc)

    @unittest.skipUnless(importlib.util.find_spec('torch') is not None,
                         'requires optional Torch CPU')
    def test_low_rank_factors_get_nonzero_initial_projection(self):
        import torch
        from matched_train import make_model, TIME_QUANTUM_MICROS
        torch.manual_seed(7)
        model = make_model('min_gru', 16, 2, torch)
        self.assertGreater(float(model.gate_input.abs().sum()), 0)
        self.assertGreater(float(model.candidate_input.abs().sum()), 0)
        self.assertEqual(TIME_QUANTUM_MICROS, 1000000)

    def test_metrics_are_only_descriptive(self):
        self.assertEqual(binary_metrics([(500000,0),(500000,1)])['brier_ppm'],250000)
        with self.assertRaisesRegex(ValueError,'empty'):
            binary_metrics([])


@unittest.skipUnless(importlib.util.find_spec('cryptography') is not None,
                     'requires Ed25519 cryptography for independent signer negative cases')
class TestIndependentlySignedChronology(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.payload={'schema':'hepta.neuron.five-arm-research-forecast-seal.v2',
                      'a0_evidence_class':'SYNTHETIC_FIXTURE_ONLY',
                      'cell_id':'fixture','training_cutoff_utc':at(1),
                      'sealed_at_utc_untrusted_local_clock':at(3,2),
                      'model_sha256':{'2048:v3':'3'*64},
                      'rows':[{'case_id':f'fu{i}', 'source_group_sha256':str(i+1)*64,
                               'event_time_utc':at(3,1), 'partition':('future' if i==0 else 'ood'),
                               'candidates':{'2048:v3':500000}, 'owner_v1_probability_ppm':500000}
                              for i in range(2)],'ndu_eligible':False,'production_qualification':False}
        self.seal=self.root/'seal.json'
        self.seal.write_text(json.dumps(self.payload))
        self.sha=hashlib.sha256(self.seal.read_bytes()).hexdigest()
        self.wit={'schema':'hepta.neuron.five-arm-precommit-witness.v1',
                  'seal_sha256':self.sha,'committed_at_utc':at(3,3),
                  'host_id':'fixture-host','operation_id':'fixture-op'}
        self.outcome={'schema':'hepta.neuron.five-arm-independent-outcomes.v1',
                      'cell_id':'fixture','input_seal_sha256':self.sha,
                      'rows':[{'case_id':f'fu{i}','source_group_sha256':str(i+1)*64,
                               'partition':('future' if i==0 else 'ood'),
                               'label':i,'label_available_at_utc':at(3,4)} for i in range(2)]}
        self.make_signed(self.wit,'witness')
        self.make_signed(self.outcome,'outcomes')

    def tearDown(self):
        self.temp.cleanup()

    def make_signed(self,obj,prefix):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
        sk=Ed25519PrivateKey.generate()
        pub=sk.public_key()
        self.root.joinpath(prefix+'.pem').write_bytes(pub.public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo))
        fingerprint=hashlib.sha256(pub.public_bytes(Encoding.Raw,PublicFormat.Raw)).hexdigest()
        canonical=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
        self.root.joinpath('signed-'+prefix+'.json').write_text(json.dumps({
            'payload':obj,'signer_key_id':fingerprint,
            'signature_b64':base64.b64encode(sk.sign(canonical)).decode()}))

    def args(self):
        return argparse.Namespace(seal_file=str(self.seal),seal_sha256=self.sha,
                                  witness_pubkey=str(self.root/'witness.pem'),
                                  signed_witness=str(self.root/'signed-witness.json'),
                                  outcome_pubkey=str(self.root/'outcomes.pem'),
                                  signed_outcomes=str(self.root/'signed-outcomes.json'),
                                  synthetic_canary=True)

    def test_synthetic_future_seal_rejected_without_explicit_flag(self):
        args=self.args()
        args.synthetic_canary=False
        with self.assertRaisesRegex(ValueError,'untrusted seal schema|authority'):
            score(args)

    def test_frozen_seal_score_never_promotes(self):
        r=score(self.args())
        self.assertFalse(r['ndu_eligible'])
        self.assertFalse(r['native_q24_parity_verified'])
        self.assertEqual(set(r['partitions']),{'future','ood'})
        self.assertEqual(r['decision'],'NO_PRODUCTION_PROMOTION')

    def test_late_prediction_fails(self):
        self.outcome['rows'][0]['label_available_at_utc']=at(3,2)
        self.make_signed(self.outcome,'outcomes')
        with self.assertRaisesRegex(ValueError,'leakage'):
            score(self.args())

    def test_wrong_evaluator_key_or_missing_pair_fails(self):
        self.outcome['rows'].pop()
        self.make_signed(self.outcome,'outcomes')
        with self.assertRaisesRegex(ValueError,'incomplete'):
            score(self.args())
        self.outcome['rows'].append({'case_id':'fu1','source_group_sha256':'2'*64,
                    'partition':'ood','label':1,'label_available_at_utc':at(3,4)})
        self.make_signed(self.outcome,'outcomes')
        x=self.args();x.outcome_pubkey=x.witness_pubkey
        with self.assertRaisesRegex(ValueError,'same key'):
            score(x)

    def test_changed_seal_rejected_by_sha256(self):
        self.seal.write_text(self.seal.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
            score(self.args())


@unittest.skipUnless(importlib.util.find_spec('torch') is not None and
                     importlib.util.find_spec('safetensors') is not None,
                     'physical Torch/safetensors optional for isolated CPU research qualification')
class TestPhysicalTorchCanary(unittest.TestCase):
    def test_twenty_physical_trained_weight_files_no_authority(self):
        import torch
        from safetensors.torch import save_file,load_file
        from matched_train import train
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            data=train_fixture()
            # Synthetic canary: these are NOT production data or selected V1 weights.
            src=root/'train.json';src.write_text(json.dumps(data))
            baseline=root/'fixture-only-v1.safetensors'
            save_file({'head.weight':torch.zeros((1,16)),
                       'head.bias':torch.zeros(1)},str(baseline))
            out=root/'models'
            args=argparse.Namespace(train_data=str(src),
                    train_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                    selected_v1=str(baseline),
                    selected_v1_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
                    output=str(out),steps=1,window=2,seed=12,lr=.01,synthetic_canary=True,max_train_cpu_seconds=300.0)
            receipt=train(args)
            self.assertEqual(len(receipt['models']),20)
            physical_audit = out / 'realized-budget-audit.json'
            self.assertTrue(physical_audit.is_file())
            with physical_audit.open(encoding='utf-8') as handle:
                realized = json.load(handle)
            self.assertEqual(realized['schema'], 'hepta.neuron.realized-budget-physical-audit.v2')
            self.assertEqual(realized['physical_candidate_artifact_slots'],20)
            self.assertEqual(realized['distinct_physical_candidate_contents'],4)
            self.assertEqual(realized['effective_independent_physical_model_comparisons'],4)
            self.assertFalse(realized['five_tier_exact_realized_parameter_design_valid'])
            self.assertIn('DUPLICATED_CAPACITY_ACROSS_NOMINAL_TIERS',
                          realized['five_tier_design_blockers'])
            self.assertFalse(realized['ndu_eligible'])
            self.assertFalse(receipt['native_q24_parity_verified'])
            self.assertFalse(receipt['future_utility_verified'])
            self.assertFalse(receipt['production_qualification'])
            for entry in receipt['models']:
                self.assertLessEqual(entry['parameter_count'],entry['cap'])
                physical=out/entry['weight_file']
                self.assertEqual(hashlib.sha256(physical.read_bytes()).hexdigest(),
                                 entry['weight_sha256'])
                tensors=load_file(str(physical))
                self.assertEqual(sum(t.numel() for t in tensors.values()),entry['parameter_count'])
                if entry['arm']=='min_gru':
                    self.assertEqual(tensors['temporal.gate_input'].shape[0], entry['rank'])


if __name__=='__main__':
    unittest.main()
