"""Adversarial tests of independent real P0 Granite97 numeric replay.

Never downloads or reads owner-only held-test labels. Uses only exact existing
public/unscored FIT, BLIND and physical model artifact ZIPs.
"""
from __future__ import annotations
import copy
from pathlib import Path
import unittest
from safetensors.numpy import load as load_safetensors, save as save_safetensors
import hepta_p0_granite97_partial_replay as replay

ROOT=Path(__file__).resolve().parent


class RealOriginalGranite97ReadOnlyReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fit=ROOT/'p0_multirc_fit_38868208650.zip'
        blind=ROOT/'p0_multirc_blind_38868208650.zip'
        model=ROOT/'p0_granite97_38868208650.zip'
        cls.fit=replay.read_json(replay.get_zip_blob(fit,'fit.json'))
        cls.blind=replay.read_json(replay.get_zip_blob(blind,'blind.json'))
        cls.report=replay.read_json(replay.get_zip_blob(model,'granite_97m_r2.json'))
        cls.manifest=replay.read_json(replay.get_zip_blob(model,'granite_97m_r2.replay/COMMITTED.json'))
        cls.feature_bytes=replay.get_zip_blob(model,'granite_97m_r2.replay/features.safetensors',max_bytes=20_000_000)
        cls.weight_bytes=replay.get_zip_blob(model,'granite_97m_r2.replay/heads.safetensors')

    def check(self,**changes):
        return replay.evaluate(changes.get('fit',self.fit),changes.get('blind',self.blind),
                changes.get('report',self.report),changes.get('manifest',self.manifest),
                changes.get('features',self.feature_bytes),changes.get('weights',self.weight_bytes))

    def test_exact_real_no_label_artifacts_replay_348(self):
        o=self.check()
        self.assertEqual(o['total_predictions_replayed'],348)
        self.assertEqual(o['source_case_count'],362)
        self.assertEqual(o['held_unlabeled_view_count'],116)
        self.assertLess(max(v['maximum_absolute_probability_error'] for v in o['numeric_replay'].values()),3e-5)
        self.assertFalse(o['stem_selected'])
        self.assertFalse(o['original_human_held_labels_opened'])

    def test_forged_probability_plus_matching_new_report_sha_rejected(self):
        r=copy.deepcopy(self.report);m=copy.deepcopy(self.manifest)
        p=r['control']['trained_head']['predictions'][0]
        p['positive_probability']=1.-p['positive_probability']
        m['physical_prediction_report_sha256']=replay.sha_doc(r)
        with self.assertRaisesRegex(replay.Invalid,'independent NumPy'):
            self.check(report=r,manifest=m)

    def test_changed_and_rehashed_complete_head_tensor_denied(self):
        from safetensors.numpy import save
        tensors=load_safetensors(self.weight_bytes)
        tensors={k:v.copy() for k,v in tensors.items()}
        tensors['evidence_trained.bias'][0]+=1.0
        new_weights=save(tensors)
        m=copy.deepcopy(self.manifest);r=copy.deepcopy(self.report)
        m['head_weights_safetensors_sha256']=replay.sha_bytes(new_weights)
        new_head=replay.head_sha(tensors,'evidence_trained')
        m['four_head_tensor_sha256']['evidence_trained']=new_head
        r['control']['trained_head']['head_sha256']=new_head
        m['physical_prediction_report_sha256']=replay.sha_doc(r)
        with self.assertRaisesRegex(replay.Invalid,'independent NumPy'):
            self.check(weights=new_weights,manifest=m,report=r)

    def test_blind_view_tamper_and_new_sha_cannot_create_original_source(self):
        b=copy.deepcopy(self.blind);m=copy.deepcopy(self.manifest);r=copy.deepcopy(self.report)
        b['cases'][0]['view_sha256']='a'*64
        m['blind_sha256']=replay.sha_doc(b)
        r['blind_material_sha256']=replay.sha_doc(b)
        m['physical_prediction_report_sha256']=replay.sha_doc(r)
        with self.assertRaisesRegex(replay.Invalid,'wrong original view'):
            self.check(blind=b,manifest=m,report=r)

    def test_held_human_label_leak_refused(self):
        b=copy.deepcopy(self.blind)
        b['cases'][0]['label']=0
        with self.assertRaisesRegex(replay.Invalid,'label leakage'):
            self.check(blind=b)

    def test_false_signature_or_production_authority_refused(self):
        for k,v in [('physical_origin_independently_signed',True),('production_promotion_permitted',True),('authority','GRANTED')]:
            m=copy.deepcopy(self.manifest);m[k]=v
            with self.subTest(key=k),self.assertRaises(replay.Invalid):self.check(manifest=m)

    def test_report_model_identity_and_checkpoint_source_fixed(self):
        r=copy.deepcopy(self.report);r['model_revision']='f'*40
        with self.assertRaises(replay.Invalid):self.check(report=r)
        m=copy.deepcopy(self.manifest);m['features_safetensors_sha256']='f'*64
        with self.assertRaises(replay.Invalid):self.check(manifest=m)

    def test_truncated_or_missing_native_weight_tensors_refused(self):
        with self.assertRaises(Exception):self.check(features=self.feature_bytes[:-10])
        tensors=load_safetensors(self.weight_bytes)
        tensors.pop('question_trained.bias')
        changed=save_safetensors(tensors)
        m=copy.deepcopy(self.manifest);m['head_weights_safetensors_sha256']=replay.sha_bytes(changed)
        with self.assertRaisesRegex(replay.Invalid,'missing/extra head tensor'):
            self.check(weights=changed,manifest=m)

if __name__=='__main__':unittest.main()
