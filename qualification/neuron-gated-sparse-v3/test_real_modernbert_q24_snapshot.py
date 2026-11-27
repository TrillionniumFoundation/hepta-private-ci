"""Synthetic fixture tests of the *real physical* train-only PCA/serialization path.

This suite NEVER claims pretrained ModernBERT invocation: the dedicated hosted
job calls the independently reviewed frozen source and real public weights.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import tempfile
import unittest
import os
import real_modernbert_q24_snapshot as p


class DeterministicFixtureEncoder:
    dimension=768
    calls=0

    def encode(self,row):
        import torch
        self.calls+=1
        seed=int.from_bytes(hashlib.sha256(row['state'].encode()).digest()[:8],'big')
        generator=torch.Generator().manual_seed(seed)
        return torch.randn(768,dtype=torch.float32,generator=generator),19

    def reverify(self):
        return None


@unittest.skipUnless(
    os.environ.get('HEPTA_NEURON_PHYSICAL_TESTS') == '1',
    'physical Torch snapshot suite requires pinned CPU job',
)
class ModelSnapshotResearchTests(unittest.TestCase):
    def prepare(self):
        fit=[{'id':f'fit:{i}', 'text':f'synthetic train {i}', 'label':i%4} for i in range(64)]
        held=[{'id':f'held:{i}', 'text':f'synthetic heldout {i}'} for i in range(32)]
        return {'schema':'hepta.banking77-four-intent-inputs.v1',
                'intents':list(p.CLASSES),'input_id':'research-synthetic-study-only',
                'fit':fit,'heldout':held}

    def test_physical_projection_reopen_and_snapshot_admission(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'physical'
            backend=DeterministicFixtureEncoder()
            result=p.produce(self.prepare(),backend,hashlib.sha256(b'fake-model').hexdigest(),
                             target,public_inputs_id='research-synthetic-study-only')
            self.assertEqual(result['physical_encoder_invocations'],96)
            self.assertEqual(backend.calls,96)
            self.assertEqual(result['train_only_projection_fit_count'],64)
            self.assertEqual(result['heldout_projection_fit_count'],0)
            self.assertFalse(result['production_qualification'])
            self.assertTrue((target/'projection.safetensors').stat().st_size > 0)
            from real_encoder_q24_snapshot_gate import validate
            import json
            registry=json.loads((target/'registry.json').read_text())
            snapshot=json.loads((target/'snapshot.json').read_text())
            report=validate(snapshot,registry,expected_encoder=result['encoder_snapshot_sha256'],
                            expected_projection=result['projection_safetensors_sha256'],
                            expected_registry_sha=result['registry_sha256'])
            self.assertEqual(report['split_count'],{'fit':64,'heldout':32})
            self.assertEqual(len(snapshot['feature_rows']),96)
            self.assertEqual(len(snapshot['feature_rows'][0]['feature_q24']),32)
            self.assertNotIn('label',snapshot['feature_rows'][0])

    def test_projection_is_train_only_even_if_heldout_changes(self):
        import torch
        torch.manual_seed(87)
        fit=torch.randn(64,768)
        held=torch.randn(32,768)
        p1,f1,h1=p.project_train_only(torch,fit,held)
        p2,f2,h2=p.project_train_only(torch,fit,held+123.456)
        self.assertTrue(torch.equal(p1['mean'],p2['mean']))
        self.assertTrue(torch.equal(p1['basis'],p2['basis']))
        self.assertTrue(torch.equal(p1['scale'],p2['scale']))
        self.assertTrue(torch.equal(f1,f2))
        self.assertFalse(torch.equal(h1,h2))

    def test_heldout_labels_fail_closed(self):
        bad=self.prepare()
        bad['heldout'][0]['label']=2
        with self.assertRaises(ValueError):p.verify_public_rows(bad)

    def test_input_duplicate_rejected(self):
        bad=self.prepare()
        bad['heldout'][0]['id']=bad['fit'][0]['id']
        with self.assertRaises(ValueError):p.verify_public_rows(bad)

    def test_explicit_model_id_required(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                p.produce(self.prepare(),DeterministicFixtureEncoder(),'notsha',Path(td)/'f',
                          public_inputs_id='research-synthetic-study-only')

    def test_negative_end_to_end_no_old_output_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'f'
            target.mkdir()
            with self.assertRaises(FileExistsError):
                p.produce(self.prepare(),DeterministicFixtureEncoder(),
                          hashlib.sha256(b'x').hexdigest(),target,
                          public_inputs_id='research-synthetic-study-only')


if __name__=='__main__':
    unittest.main()
