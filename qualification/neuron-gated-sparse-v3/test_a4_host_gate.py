#!/usr/bin/env python3
"""Synthetic A4 100-slot negative cases; never attest a target host."""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from a4_end_to_end_gate import (validate, percentile, PERF_FIELDS, RECEIPT_FIELDS,
                                PROOFS, CAPS, ALL_ARMS, SCALES)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HostA4GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.baseline=self.root/'selected-v1.bin'
        self.baseline.write_bytes(b'research-fixture-selected')
        self.base_sha=digest(self.baseline.read_bytes())
        self.training={
            'schema':'hepta.neuron.five-arm-differentiable-shadow-train.v1',
            'source_train_sha256':'1'*64,'encoder_digest_claimed':'2'*64,
            'cell_id':'fixture','training_cutoff_utc':'2026-10-01T00:00:00Z',
            'train_source_group_hashes':['3'*64],
            'no_change_v1_selected_sha256':self.base_sha,'no_change_optimizer_steps':0,
            'candidate_optimizer_steps':5,'cpu_only':True,
            'uniform_per_arm_cpu_ceiling_seconds':300.0,'preregistered_window':4,
            'seed':1,'schedule_sha256':'4'*64,'target_host_attested':False,
            'native_q24_parity_verified':False,'training_provenance_independently_verified':False,
            'future_utility_verified':False,'ndu_eligible':False,'production_qualification':False,
            'decision':'NO_PROMOTION','models':[],
            'peak_process_rss_kib_not_arm_comparable':100,
            'evidence_class':'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION',
            'a0_registry_sha256':'5'*64,'a0_host_id':'host-research-fixture',
            'a0_checkpoint_digest_claimed':'6'*64,'a0_generation_claimed':1
        }
        self.expected={}
        for cap in CAPS:
            for arm in ALL_ARMS:
                if arm=='no-change-v1': continue
                path=self.root/str(cap)/(arm+'.safetensors')
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(f'synthetic:{cap}:{arm}'.encode())
                key=(cap,arm)
                count=(129 if arm=='min_gru' else 81 if arm=='v3'
                       else 65 if arm=='ssm' else 33)
                self.expected[key]=count
                self.training['models'].append({
                    'cap':cap,'arm':arm,'weight_file':f'{cap}/{arm}.safetensors',
                    'weight_sha256':digest(path.read_bytes()),'parameter_count':count,
                    'optimizer_steps':5,'width':16,'rank':(1 if arm=='min_gru' else None)
                })
        self.commit='a'*40
        self.host={
            'schema':'hepta.neuron.a4-end-to-end-host-100-slot.v1',
            'host_id':'host-research-fixture','host_profile_sha256':'7'*64,
            'source_commit_sha':self.commit,'encoder_bundle_sha256':'8'*64,
            'a0_registry_sha256':'5'*64,'training_receipt_sha256':'9'*64,
            'measurement_started_at_utc':'2026-10-02T01:00:00Z',
            'measurement_ended_at_utc':'2026-10-02T02:00:00Z',
            'measurements':[]
        }
        for cap in CAPS:
            for arm in ALL_ARMS:
                sha=(self.base_sha if arm=='no-change-v1' else
                     next(m['weight_sha256'] for m in self.training['models']
                          if m['cap']==cap and m['arm']==arm))
                for scale in SCALES:
                    p={field:100 for field in PERF_FIELDS}
                    p.update(measurement_kind='target-host-real-end-to-end',
                             device_kind='cpu',request_count=scale,
                             gpu_peak_alloc_bytes=0,gpu_peak_total_bytes=0,
                             lost_replay_count=0,
                             encoder_forward_invocations=scale,
                             encoder_forward_rows=scale,
                             request_p50_micros=80,request_p95_micros=90,
                             request_p99_micros=100,batch_p95_micros=100,
                             batch_p99_micros=110)
                    self.host['measurements'].append({
                        'parameter_cap':cap,'arm':arm,'cell_count':scale,
                        'model_sha256':sha,
                        'execution_receipts_sha256':{x:'c'*64 for x in RECEIPT_FIELDS},
                        'performance':p,'proofs':{x:True for x in PROOFS}
                    })

    def tearDown(self):
        self.tmp.cleanup()

    def fake_tensor_verification(self, path, sha):
        cap=int(path.parent.name);arm=path.stem
        if arm=='min_gru':
            shapes={
                'temporal.gate_input':(1,16),'temporal.gate_output':(16,1),
                'temporal.candidate_input':(1,16),'temporal.candidate_output':(16,1),
                'temporal.gate_bias':(16,), 'temporal.candidate_bias':(16,),
                'head.weight':(1,16),'head.bias':(1,), 'structure.projection':(16,)
            }
        else:
            shapes={'head.weight':(1,16),'head.bias':(1,)}
        return self.expected[(cap,arm)], shapes

    def check(self):
        with patch('a4_end_to_end_gate.actual_safetensors',
                   side_effect=self.fake_tensor_verification):
            return validate(self.host,self.training,
                host_id='host-research-fixture',train_sha='9'*64,
                physical_weights_root=self.root,selected_v1=self.baseline,
                selected_v1_sha=self.base_sha,
                host_key_fingerprint='d'*64,expected_commit=self.commit,
                expected_encoder_bundle_sha='8'*64,
                expected_host_profile_sha='7'*64)

    def test_exact_hundred_slots_are_only_structural_claims(self):
        r=self.check()
        self.assertEqual(r['100_complete_end_to_end_signed_host_claim_slots'],100)
        self.assertFalse(r['production_qualification'])
        self.assertFalse(r['trusted_host_execution_independently_attested'])

    def test_missing_duplicate_or_extra_slot_blocked(self):
        self.host['measurements'].pop()
        with self.assertRaisesRegex(ValueError,'100 end-to-end'):
            self.check()
        self.host['measurements'].append(self.host['measurements'][0].copy())
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.check()

    def test_preregistered_encoder_commit_host_binding(self):
        self.host['source_commit_sha']='b'*40
        with self.assertRaisesRegex(ValueError,'preregistration'):
            self.check()

    def test_request_percentile_and_encoder_execution_required(self):
        p=self.host['measurements'][0]['performance']
        p['request_p99_micros']=10
        with self.assertRaisesRegex(ValueError,'percentile'):
            self.check()
        p['request_p99_micros']=100
        p['encoder_forward_rows']=0
        with self.assertRaisesRegex(ValueError,'Encoder'):
            self.check()

    def test_refuse_fixture_training_in_real_host_gate(self):
        self.training['evidence_class']='SYNTHETIC_FIXTURE_ONLY'
        with self.assertRaisesRegex(ValueError,'actual A0'):
            self.check()

    def test_reject_lost_acknowledged_replay_and_synthetic_kind(self):
        p=self.host['measurements'][0]['performance']
        p['lost_replay_count']=1
        with self.assertRaisesRegex(ValueError,'history lost'):
            self.check()
        p['lost_replay_count']=0
        p['measurement_kind']='mechanism-only'
        with self.assertRaisesRegex(ValueError,'synthetic sample'):
            self.check()


@unittest.skipUnless(__import__('importlib').util.find_spec('torch') is not None and
                     __import__('importlib').util.find_spec('safetensors') is not None,
                     'requires pinned CPU Torch + safetensors')
class PhysicalArtifactA4StructureTests(HostA4GateTests):
    """Same 100-slot input fixture, but validate REAL on-disk safetensors bytes.

    The target-host receipt contents remain synthetic and no deployment is proven.
    """

    def setUp(self):
        super().setUp()
        import torch
        from safetensors.torch import save_file
        torch.set_num_threads(1)
        for cap in CAPS:
            for arm in ALL_ARMS:
                if arm == 'no-change-v1':
                    continue
                path = self.root/str(cap)/(arm+'.safetensors')
                weights = {
                    'head.weight':torch.zeros((1,16), dtype=torch.float32),
                    'head.bias':torch.zeros(1, dtype=torch.float32),
                    'structure.projection':torch.full((16,),1<<24,dtype=torch.int64),
                }
                if arm == 'v3':
                    for name in ('gate_bias','input_gain','change_gain'):
                        weights['temporal.'+name] = torch.zeros(16,dtype=torch.int64)
                elif arm == 'ssm':
                    for name in ('decay_per_step','input_gain'):
                        weights['temporal.'+name] = torch.zeros(16,dtype=torch.int64)
                elif arm == 'min_gru':
                    weights.update({
                        'temporal.gate_input':torch.zeros((1,16),dtype=torch.int64),
                        'temporal.gate_output':torch.zeros((16,1),dtype=torch.int64),
                        'temporal.candidate_input':torch.zeros((1,16),dtype=torch.int64),
                        'temporal.candidate_output':torch.zeros((16,1),dtype=torch.int64),
                        'temporal.gate_bias':torch.zeros(16,dtype=torch.int64),
                        'temporal.candidate_bias':torch.zeros(16,dtype=torch.int64),
                    })
                save_file(weights,str(path))
                observed_hash=digest(path.read_bytes())
                for m in self.training['models']:
                    if m['cap']==cap and m['arm']==arm:
                        self.assertEqual(sum(t.numel() for t in weights.values()),
                                         m['parameter_count'])
                        m['weight_sha256']=observed_hash
                for m in self.host['measurements']:
                    if m['parameter_cap']==cap and m['arm']==arm:
                        m['model_sha256']=observed_hash

    def test_actual_twenty_safetensors_files_and_100_structural_claims(self):
        from a4_end_to_end_gate import validate
        r=validate(self.host,self.training,
                host_id='host-research-fixture',train_sha='9'*64,
                physical_weights_root=self.root,selected_v1=self.baseline,
                selected_v1_sha=self.base_sha,
                host_key_fingerprint='d'*64,expected_commit=self.commit,
                expected_encoder_bundle_sha='8'*64,
                expected_host_profile_sha='7'*64)
        self.assertEqual(r['100_complete_end_to_end_signed_host_claim_slots'],100)
        self.assertFalse(r['trusted_host_execution_independently_attested'])
        self.assertFalse(r['production_qualification'])



if __name__=='__main__':
    unittest.main()
