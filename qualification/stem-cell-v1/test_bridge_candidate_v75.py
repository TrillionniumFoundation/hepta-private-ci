"""Actual historical V6 weights + separate Torch/NumPy predictions on synthetic tokens.

The real old 128 case IDs and original checkpoint weights are authentic; token
features are EXPLICITLY SYNTHETIC. These tests cannot certify Granite efficacy.
"""
import io
import subprocess
import sys
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np

from bridge_candidate_v75 import (seal_features,seal_logits,seal_scope_receipt,
    _load,_json,_digest,_read_tensor_archive,check_source_bindings)
from bridge_candidate_v75_review import audit_one,audit_grid
from bridge_numpy_forward import weights_from_checkpoint
from bridge_numpy_reference_torch import reference
from bridge_portable_v74 import originals

ROOT=Path('/mnt/data/hepta_research_material')
ARCHIVES={
 'v4':ROOT/'hepta_token_evidence_ndu_v4_20261015.zip',
 'v5':ROOT/'hepta_binding_learning_v5_20261015.zip',
 'v6':ROOT/'hepta_bridge_learning_v6_20261015.zip'
}


def synthetic_batches():
    rng=np.random.default_rng(7341)
    for idx in range(8):
        f=rng.normal(size=(16,4,3,384)).astype('float32')
        q=rng.normal(size=(16,2,384)).astype('float32')
        a=rng.normal(size=(16,2,384)).astype('float32')
        fm=np.ones((16,4,3),dtype=bool)
        fm[0,2,:]=False
        fm[:,1,2]=False
        qm=np.ones((16,2),dtype=bool)
        cm=np.ones((16,2),dtype=bool)
        yield (f,q,a,fm,qm,cm)


class OriginalWeightsSyntheticFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(x.is_file() for x in ARCHIVES.values()):
            raise RuntimeError('Original archive absent; cannot count as a passing original-weight test')
        cls.material=originals(**ARCHIVES)
        cls.rows=cls.material['source']['reader_train']
        with zipfile.ZipFile(ARCHIVES['v6']) as z:
            cls.checkpoints={}
            for seed in (41,47,53):
                cls.checkpoints[seed]=z.read(f'reader-v6-bridge/seed-{seed}/bridge/warmup.pt')

    def create_fixture(self,folder,*,seed=41):
        p=Path(folder)
        features=p/'features'
        seal_features(features,self.rows,synthetic_batches(),
            model_sha='a'*64, tokenizer_sha='b'*64,preprocess_sha='c'*64,
            principal_sha='d'*64,purpose_sha='e'*64,
            origin='synthetic_test_only')
        ck=p/'original-v6.pt'
        ck.write_bytes(self.checkpoints[seed])
        weights,_=weights_from_checkpoint(self.checkpoints[seed])
        def physical_torch(arrays):
            feats=tuple(arrays[x] for x in ('facts','question','candidate'))
            masks=tuple(arrays[x] for x in ('fact_mask','question_mask','candidate_mask'))
            return reference(weights,feats,masks,steps=3)[-1][1]
        predictions=p/'predictions'
        seal_logits(features,predictions,seed=seed,arm='joint',checkpoint=ck,
                    torch_predict=physical_torch)
        probs=[]
        for i in range(8):
            row=json.loads((predictions/f'batch-{i:03d}.json').read_text())
            arr=np.array(row['logits'],dtype=np.float64)
            probs.extend(np.exp(arr[:,1]-np.logaddexp(arr[:,0],arr[:,1])).tolist())
        return dict(features=features, predictions=predictions,ck=ck,probs=probs)

    def test_genuine_original_model_bytes_independent_numpy_on_128_synthetic_feature_rows(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            r=audit_one(p['features'],p['predictions'],p['ck'],self.rows,p['probs'],
                        seed=41,arm='joint',allow_synthetic=True)
            self.assertEqual(r['case_count'],128)
            self.assertEqual(r['candidate_parameter_count'],42562)
            self.assertTrue(r['numerical_checks_passed'])
            self.assertLess(r['max_abs_torch_numpy_logit_error'],.002)
            self.assertFalse(r['authenticator_witness_verified'])
            self.assertFalse(r['old_task_future_retention_verified'])
            self.assertEqual(r['source_origin'],'synthetic_test_only')
            self.assertFalse(r['production_authorized'])
            self.assertEqual(len(r['batches']),8)

    def test_synthetic_source_is_ineligible_for_real_qualification_even_when_weights_are_real(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            with self.assertRaisesRegex(ValueError,'synthetic tokens'):
                audit_one(p['features'],p['predictions'],p['ck'],self.rows,p['probs'],
                          seed=41,arm='joint')

    def test_resealed_fake_logits_rejected_against_original_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            logit=p['predictions']/'batch-000.json'
            x=json.loads(logit.read_text());x['logits'][0][1]+=0.35
            logit.write_bytes(_json(x))
            index_path=p['predictions']/'index.json'
            index=json.loads(index_path.read_text())
            index['batches'][0]['sha256']=_digest(logit.read_bytes())
            index_path.write_bytes(_json(index))
            with self.assertRaisesRegex(ValueError,'disagree'):
                audit_one(p['features'],p['predictions'],p['ck'],self.rows,p['probs'],
                          seed=41,arm='joint',allow_synthetic=True)

    def test_wrong_previously_observed_old_task_probabilities_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            probs=list(p['probs']);probs[50]=0.0 if probs[50]>.5 else 1.0
            with self.assertRaisesRegex(ValueError,'existing old-task score'):
                audit_one(p['features'],p['predictions'],p['ck'],self.rows,probs,
                          seed=41,arm='joint',allow_synthetic=True)

    def test_swapped_real_checkpoint_denied_by_preseal_commitment(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            p['ck'].write_bytes(self.checkpoints[47])
            with self.assertRaisesRegex(ValueError,'candidate frozen weight ZIP mismatch'):
                audit_one(p['features'],p['predictions'],p['ck'],self.rows,p['probs'],
                          seed=41,arm='joint',allow_synthetic=True)

    def test_original_source_id_or_labels_cannot_be_changed_in_independent_reviewer(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            rows=[dict(row) for row in self.rows]
            rows[0]['answer_id']='F0RGED'
            with self.assertRaisesRegex(ValueError,'original source-case census'):
                audit_one(p['features'],p['predictions'],p['ck'],rows,p['probs'],
                          seed=41,arm='joint',allow_synthetic=True)

    def test_cannot_accept_incomplete_nine_model_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            with self.assertRaises(Exception):
                seal_scope_receipt(p['features'],Path(td)/'missing-nine',
                    output=Path(td)/'assembly.json',original_rows=self.rows)
            self.assertFalse((Path(td)/'assembly.json').exists())

    def test_all_nine_original_model_identity_slots_on_synthetic_tokens_without_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            p=self.create_fixture(td)
            features=p['features']
            output=root/'nine-predictions'
            for seed in (41,47,53):
                model=root/f'authentic-v6-seed-{seed}.pt'
                model.write_bytes(self.checkpoints[seed])
                weights,_=weights_from_checkpoint(self.checkpoints[seed])
                def torch_reference(arrays):
                    f=tuple(arrays[x] for x in ('facts','question','candidate'))
                    masks=tuple(arrays[x] for x in ('fact_mask','question_mask','candidate_mask'))
                    return reference(weights,f,masks,steps=3)[-1][1]
                for arm in ('joint','protect_old','protect_old_guarded'):
                    folder=output/f'seed-{seed}'/arm
                    folder.parent.mkdir(parents=True,exist_ok=True)
                    seal_logits(features,folder,seed=seed,arm=arm,
                                checkpoint=model,torch_predict=torch_reference)
            with self.assertRaisesRegex(ValueError,'synthetic tokens'):
                seal_scope_receipt(features,output,output=root/'strict.json',
                                   original_rows=self.rows)
            self.assertFalse((root/'strict.json').exists())
            result=seal_scope_receipt(features,output,output=root/'fixture-only.json',
                         original_rows=self.rows,allow_synthetic=True)
            self.assertEqual(len(result['predictions']),9)
            self.assertEqual(result['number_of_models'],9)
            self.assertTrue(result['synthetic_test_only'])
            self.assertFalse(result['tokenbank_authenticity_proven'])
            self.assertFalse(result['model_selection_authorized'])
            self.assertFalse(result['production_authorized'])

    def test_label_injection_into_input_six_tuple_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            def wrong():
                for pack in synthetic_batches():
                    yield (*pack,np.zeros((16,),dtype=np.int64))
            with self.assertRaisesRegex(ValueError,'six-tensor'):
                seal_features(Path(td)/'source',self.rows,wrong(),model_sha='a'*64,
                    tokenizer_sha='b'*64,preprocess_sha='c'*64,principal_sha='d'*64,
                    purpose_sha='e'*64,origin='synthetic_test_only')
            self.assertFalse((Path(td)/'source'/'index.json').exists())

    def test_missing_one_batch_denied_before_publish(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'incomplete eight-batch'):
                seal_features(Path(td)/'source',self.rows,list(synthetic_batches())[:-1],
                    model_sha='a'*64,tokenizer_sha='b'*64,preprocess_sha='c'*64,
                    principal_sha='d'*64,purpose_sha='e'*64,origin='synthetic_test_only')

    def test_real_v75_cli_blocks_missing_original_97m_before_output_or_synthetic_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            script=Path(__file__).with_name('bridge_candidate_v75_cli.py')
            output=root/'must-not-exist'
            result=subprocess.run([sys.executable,str(script),
                '--v4',str(ARCHIVES['v4']),'--v5',str(ARCHIVES['v5']),
                '--v6',str(ARCHIVES['v6']), '--snapshot',str(root/'missing-model'),
                '--run',str(root/'missing-v74'), '--output',str(output)],
                capture_output=True,text=True,timeout=45)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('original public pretrained Granite97 material absent',result.stderr)
            self.assertFalse(output.exists())

    def test_producer_does_not_claim_train_label_access_is_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            index=json.loads((p['features']/'index.json').read_text())
            self.assertTrue(index['training_labels_available_to_source_builder'])
            self.assertFalse(index['serialized_class_targets'])
            producer=json.loads((p['predictions']/'index.json').read_text())
            self.assertFalse(producer['payload_contains_targets'])
            self.assertFalse(producer['producer_label_isolation_independently_proven'])

    def test_additional_batch_denied_before_publish(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,'unregistered extra'):
                seal_features(Path(td)/'source',self.rows,list(synthetic_batches())+
                    [next(synthetic_batches())],model_sha='a'*64,tokenizer_sha='b'*64,
                    preprocess_sha='c'*64,principal_sha='d'*64,purpose_sha='e'*64,
                    origin='synthetic_test_only')

    def test_source_manifest_does_not_contain_labels_answers_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.create_fixture(td)
            for file in p['features'].rglob('*.json'):
                data=json.loads(file.read_text())
                self.assertNotIn('labels',data)
                self.assertNotIn('targets',data)
                self.assertNotIn('credentials',data)
                self.assertNotIn('answer_id',data)

if __name__=='__main__':
    unittest.main()
