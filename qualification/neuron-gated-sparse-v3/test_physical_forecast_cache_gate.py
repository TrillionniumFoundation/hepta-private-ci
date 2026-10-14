#!/usr/bin/env python3
"""Physical metadata-insensitive forecast forward reuse, synthetic research only."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from precommit_future import seal
from physical_tensor_identity import canonical_tensor_sha
from test_realized_budget_audit import fixture, sha


class PhysicalForecastCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        _,self.receipt=fixture(self.root,width=16)
        self.receipt.update(cell_id='synthetic-no-owner',encoder_digest_claimed='1'*64,
            train_source_group_hashes=['e'*64],training_cutoff_utc='2026-10-01T00:00:00Z',
            no_change_v1_selected_sha256='f'*64)
        self.save_receipt()
        cases=[{'case_id':f'future-{i}', 'source_group':f'unseen-group-{i}',
                'sequence':1,'event_time_utc':f'2026-10-0{i+2}T00:00:00Z',
                'partition':'future' if i<3 else 'ood',
                'feature_q24':[10000+(i+j)*100 for j in range(16)]}
                for i in range(6)]
        self.future=self.root/'unlabelled.json'
        self.future.write_text(json.dumps({
            'schema':'hepta.neuron.unlabelled-future-q24.v1',
            'encoder_digest':'1'*64,'cell_id':'synthetic-no-owner','samples':cases}))
        self.owner=self.root/'frozen-v1-unselected-predictions.json'
        self.owner.write_text(json.dumps({
            'schema':'hepta.neuron.owner-v1-frozen-predictions.v1',
            'selected_v1_sha256':'f'*64,'cell_id':'synthetic-no-owner',
            'predictions':[{'case_id':c['case_id'],'probability_ppm':500000,
                            'model_invocation_digest':'b'*64} for c in cases]}))
        self.args=argparse.Namespace(
            trained_root=str(self.root),receipt_sha256=self.receipt_sha,
            future_features=str(self.future),future_sha256=sha(self.future),
            frozen_v1_predictions=str(self.owner),
            frozen_v1_predictions_sha256=sha(self.owner),
            seal_output=str(self.root/'new-seal.json'),synthetic_canary=True)

    def save_receipt(self):
        path=self.root/'training-receipt.json'
        path.write_text(json.dumps(self.receipt,sort_keys=True)+'\n')
        self.receipt_sha=sha(path)
        if hasattr(self,'args'):
            self.args.receipt_sha256=self.receipt_sha

    def update_candidate_sha(self,cap=8192,arm='v2'):
        for model in self.receipt['models']:
            if model['cap']==cap and model['arm']==arm:
                model['weight_sha256']=sha(self.root/model['weight_file'])
        self.save_receipt()

    def seal_and_read(self):
        result=seal(self.args)
        sealed=json.loads(Path(self.args.seal_output).read_text())
        self.assertFalse(result['ndu_eligible'])
        self.assertFalse(sealed['production_qualification'])
        return sealed

    def test_twenty_slots_only_four_actual_surrogate_forwards(self):
        from precommit_future import make_model
        called=[]
        def watch(*args,**kwargs):
            called.append(args[0]);return make_model(*args,**kwargs)
        with patch('precommit_future.make_model',side_effect=watch):
            sealed=self.seal_and_read()
        reuse=sealed['physical_tensor_reuse_observation']
        self.assertEqual(len(called),4)
        self.assertEqual((reuse['nominal_candidate_slots'],
                          reuse['actual_per_group_surrogate_forward_executions'],
                          reuse['redundant_surrogate_model_forwards_eliminated']),(20,4,16))
        for row in sealed['rows']:
            self.assertEqual(len(row['candidates']),20)
            for group in reuse['alias_groups']:
                self.assertEqual(len({row['candidates'][alias]
                                      for alias in group['alias_candidate_keys']}),1)

    def test_alternative_safetensors_metadata_cannot_create_new_execution(self):
        path=self.root/'8192'/'v2.safetensors'
        previous=canonical_tensor_sha(path)
        data=path.read_bytes();h=int.from_bytes(data[:8],'little')
        headers=json.loads(data[8:8+h]);headers['__metadata__']={'research-only':'different-name'}
        new=json.dumps(headers,sort_keys=True).encode()
        path.write_bytes(len(new).to_bytes(8,'little')+new+data[8+h:])
        self.assertEqual(canonical_tensor_sha(path),previous)
        self.update_candidate_sha()
        sealed=self.seal_and_read()
        self.assertEqual(sealed['physical_tensor_reuse_observation'][
            'actual_per_group_surrogate_forward_executions'],4)

    def test_actual_tensor_change_requires_fifth_forward(self):
        from safetensors.torch import load_file,save_file
        path=self.root/'8192'/'v2.safetensors'
        tensors=load_file(str(path));tensors['head.bias']+=0.25
        save_file(tensors,str(path));self.update_candidate_sha()
        sealed=self.seal_and_read()
        self.assertEqual(sealed['physical_tensor_reuse_observation'][
            'actual_per_group_surrogate_forward_executions'],5)

    def test_mutated_model_without_receipt_update_blocks_seal(self):
        path=self.root/'8192'/'v2.safetensors'
        with path.open('ab') as file:file.write(b'evade')
        with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
            seal(self.args)

    def test_unlabelled_future_enforced_before_model_execution(self):
        data=json.loads(self.future.read_text());data['samples'][0]['label']=1
        self.future.write_text(json.dumps(data));self.args.future_sha256=sha(self.future)
        with patch('precommit_future.make_model') as model:
            with self.assertRaisesRegex(ValueError,'no labels allowed'):
                seal(self.args)
            model.assert_not_called()


if __name__=='__main__':
    unittest.main()
