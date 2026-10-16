"""Bounded independent sealed-input inference audits (synthetic only)."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import torch

from bridge_gradient_archive_replay import SHAPES,decode_fp32_checkpoint
from bridge_numpy_forward import weights_from_checkpoint
from bridge_numpy_reference_torch import reference
from bridge_numpy_receipt import verify, _sha, FEATURE_SCHEMA, OBSERVED_SCHEMA


def prepare_case(path,*,seed=601):
    path=Path(path)
    g=torch.Generator().manual_seed(seed)
    state={n:torch.randn(sh,generator=g)*.01 for n,sh in SHAPES.items()}
    model=io.BytesIO()
    torch.save(state,model)
    (path/'candidate.pt').write_bytes(model.getvalue())
    weights,_=weights_from_checkpoint(model.getvalue())
    gen=np.random.default_rng(seed)
    feats=(gen.normal(size=(2,3,4,384)).astype('float32'),
        gen.normal(size=(2,3,384)).astype('float32'),
        gen.normal(size=(2,2,384)).astype('float32'))
    fm=np.ones((2,3,4),dtype='bool');fm[0,-1,:]=False
    qm=np.ones((2,3),dtype='bool');qm[0,-1]=False
    cm=np.ones((2,2),dtype='bool')
    masks=(fm,qm,cm)
    arrays=dict(zip(('facts','question','candidate','fact_mask','question_mask','candidate_mask'),feats+masks))
    np.savez_compressed(path/'feature.npz',**arrays)
    content=(path/'feature.npz').read_bytes()
    case_ids=['case:A','case:B']
    manifest={
      'schema':FEATURE_SCHEMA,'case_ids':case_ids,
      'case_source_sha256':['b'*64,'c'*64],
      'labels_present':False,'production_authorized':False,
      'generation':7, 'encoder_digest':'a'*64,'tokenizer_digest':'d'*64,
      'preprocessor_digest':'e'*64,'principal_digest':'f'*64,'purpose_digest':'0'*64,
      'tensor_archive_sha256':_sha(content),
      'tensors':{name:{'shape':list(t.shape),'dtype':'bool' if name.endswith('mask') else 'float32',
              'raw_sha256':_sha(t.tobytes(order='C'))} for name,t in arrays.items()}
    }
    (path/'manifest.json').write_text(json.dumps(manifest,sort_keys=True)+'\n')
    reference_logits=reference(weights,feats,masks,steps=3)[-1][1]
    external=dict(schema=OBSERVED_SCHEMA,case_ids=case_ids,labels_present=False,
        checkpoint_sha256=_sha(model.getvalue()),tensor_archive_sha256=_sha(content),
        logits=reference_logits.tolist(),production_authorized=False)
    (path/'external.json').write_text(json.dumps(external,sort_keys=True)+'\n')
    return dict(checkpoint=path/'candidate.pt',archive=path/'feature.npz',
                manifest=path/'manifest.json',external=path/'external.json',
                checkpoint_sha=_sha(model.getvalue()),manifest_sha=_sha((path/'manifest.json').read_bytes()))


def run_fixture(paths):
    return verify(paths['checkpoint'],paths['archive'],paths['manifest'],paths['external'],
                  checkpoint_sha=paths['checkpoint_sha'],manifest_sha=paths['manifest_sha'])


class StandaloneNoPretrained(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_independent_tensor_inference_matches_external_torch(self):
        with tempfile.TemporaryDirectory() as directory:
            input_paths=prepare_case(directory)
            result=run_fixture(input_paths)
            self.assertTrue(result['independent_tensor_forward_performed'])
            self.assertEqual(result['model_parameter_count'],42562)
            self.assertEqual(result['case_count'],2)
            self.assertLess(result['max_abs_logit_error'],0.002)
            self.assertFalse(result['future_task_quality_established'])
            self.assertFalse(result['pretrained_encoder_executed'])
            self.assertFalse(result['production_authorized'])

    def test_model_and_manifest_expected_hashes_are_not_self_certified(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            with self.assertRaises(ValueError):
                verify(p['checkpoint'],p['archive'],p['manifest'],p['external'],
                       checkpoint_sha='b'*64,manifest_sha=p['manifest_sha'])
            with self.assertRaises(ValueError):
                verify(p['checkpoint'],p['archive'],p['manifest'],p['external'],
                       checkpoint_sha=p['checkpoint_sha'],manifest_sha='d'*64)

    def test_changed_external_logits_denied_even_if_external_file_is_rehashed(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            original=json.loads(p['external'].read_text())
            original['logits'][0][1]+=0.25
            p['external'].write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError,'disagree'):
                run_fixture(p)

    def test_external_scope_and_case_binding_cannot_be_swapped(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            obj=json.loads(p['external'].read_text())
            obj['case_ids']=obj['case_ids'][::-1]
            p['external'].write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,'not bound'):
                run_fixture(p)

    def test_manifest_cannot_contain_labels_even_with_new_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            obj=json.loads(p['manifest'].read_text())
            obj['labels_present']=True
            p['manifest'].write_text(json.dumps(obj))
            p['manifest_sha']=_sha(p['manifest'].read_bytes())
            with self.assertRaisesRegex(ValueError,'schema'):
                run_fixture(p)

    def test_npz_tensor_buffer_tamper_not_admitted_after_manifest_sealed(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            with np.load(p['archive'],allow_pickle=False) as arc:
                arrays={k:arc[k].copy() for k in arc.files}
            arrays['facts'][0,0,0,0]+=1.25
            np.savez_compressed(p['archive'],**arrays)
            with self.assertRaisesRegex(ValueError,'feature ZIP'):
                run_fixture(p)

    def test_symlink_original_feature_source_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            alias=Path(d)/'link.npz'
            alias.symlink_to(p['archive'])
            p['archive']=alias
            with self.assertRaisesRegex(ValueError,'symlink'):
                run_fixture(p)

    def test_pickle_payload_and_unsupported_dtype_denied(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            with np.load(p['archive'],allow_pickle=False) as arc:
                arrays={k:arc[k].copy() for k in arc.files}
            arrays['candidate']=arrays['candidate'].astype('float64')
            np.savez_compressed(p['archive'],**arrays)
            manifest=json.loads(p['manifest'].read_text())
            manifest['tensor_archive_sha256']=_sha(p['archive'].read_bytes())
            manifest['tensors']['candidate']['dtype']='float64'
            manifest['tensors']['candidate']['raw_sha256']=_sha(arrays['candidate'].tobytes())
            p['manifest'].write_text(json.dumps(manifest))
            p['manifest_sha']=_sha(p['manifest'].read_bytes())
            with self.assertRaisesRegex(ValueError,'NPY header'):
                run_fixture(p)

    def test_large_forged_npy_shape_rejected_before_allocation(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            with zipfile.ZipFile(p['archive'],'r') as z:
                members={v.filename:z.read(v.filename) for v in z.infolist()}
            # Valid header for an impossible multi-GB array, with no body.
            forged=io.BytesIO()
            np.lib.format.write_array_header_1_0(forged,
              {'descr':np.dtype(np.float32).str,'fortran_order':False,
               'shape':(10000000,3,4,384)})
            members['facts.npy']=forged.getvalue()
            with zipfile.ZipFile(p['archive'],'w') as z:
                for name,value in members.items():z.writestr(name,value)
            man=json.loads(p['manifest'].read_text())
            man['tensor_archive_sha256']=_sha(p['archive'].read_bytes())
            p['manifest'].write_text(json.dumps(man))
            p['manifest_sha']=_sha(p['manifest'].read_bytes())
            with self.assertRaisesRegex(ValueError,'NPY header'):
                run_fixture(p)

    def test_near_tie_class_flip_rejected_even_when_logits_within_tolerance(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            # Force a genuine, separately sealed zero-logit Torch checkpoint.
            state=torch.load(p['checkpoint'],weights_only=True)
            state['head.2.weight'].zero_();state['head.2.bias'].zero_()
            torch.save(state,p['checkpoint'])
            p['checkpoint_sha']=_sha(p['checkpoint'].read_bytes())
            obs=json.loads(p['external'].read_text())
            obs['checkpoint_sha256']=p['checkpoint_sha']
            obs['logits']=[[0.,.0001],[0.,.0001]]
            p['external'].write_text(json.dumps(obs))
            with self.assertRaisesRegex(ValueError,'top-class'):
                run_fixture(p)

    def test_no_forged_authority_flags(self):
        with tempfile.TemporaryDirectory() as d:
            p=prepare_case(d)
            observed=json.loads(p['external'].read_text())
            observed['production_authorized']=True
            p['external'].write_text(json.dumps(observed))
            with self.assertRaisesRegex(ValueError,'not bound'):
                run_fixture(p)

if __name__=='__main__': unittest.main()
