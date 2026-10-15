"""Adversarial P0 *synthetic-feature* replay tests, not pretrained efficacy."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest

import numpy as np
from safetensors.numpy import load_file, save_file

from p0_multirc_semantic_material import Invalid, canonical, sha
from p0_multirc_semantic_execute import fit_head, run
from p0_question_only_head import fit_question_only
from p0_physical_replay_v5 import (export_original_replay, independent_numeric_replay,
                                   MODEL_WIDTHS,SCHEMA,MAX_BYTES,_hash_bytes)
from test_p0_multirc_semantic import setup, mocked_report
from test_p0_question_only_matched import fake_vectors


class OriginalTensorReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,cls.fit,cls.blind,_=setup()
        cls.template={}
        for model,width in MODEL_WIDTHS.items():
            vec=fake_vectors(cls.fit['cases']+cls.blind['cases'],width)
            tensor={}
            parent=fit_head(cls.fit['cases'],cls.blind['cases'],vec,width,replay_heads=tensor)
            prior=fit_question_only(cls.fit,cls.blind,vec,width,parent,replay_heads=tensor)
            report=mocked_report(model,cls.fit,cls.blind)
            report['training']=parent
            report['control']=parent['controls']
            report['matched_question_only_control']=prior
            cls.template[model]=(vec,tensor,report)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.model='granite_97m_r2'
        self.path=Path(self.tmp.name)/'granite_97m_r2.replay'
        vec,heads,report=self.template[self.model]
        self.report=copy.deepcopy(report)
        self._create(vec,heads)

    def _create(self,vec,heads):
        return export_original_replay(self.path,self.fit,self.blind,self.report,self.model,vec,heads)

    def _check(self):
        return independent_numeric_replay(self.path,self.fit,self.blind,self.report,model=self.model)

    def _manifest(self):
        return json.loads((self.path/'COMMITTED.json').read_text())

    def _put(self,obj):
        (self.path/'COMMITTED.json').write_bytes(canonical(obj)+b'\n')

    def test_full_independent_numpy_replay_384(self):
        r=self._check()
        self.assertEqual(r['replayed_original_and_question_head_predictions'],
                         2*len(self.blind['cases'])+2*(len(self.blind['cases'])//2))
        self.assertLess(r['max_probability_disagreement'],3e-5)
        self.assertFalse(r['physical_model_origin_independently_authenticated'])
        self.assertFalse(r['production_promotion_permitted'])

    def test_full_independent_numpy_replay_256(self):
        model='embeddinggemma_2_text'
        vec,weights,report=self.template[model]
        second=Path(self.tmp.name)/'gemma.replay'
        export_original_replay(second,self.fit,self.blind,report,model,vec,weights)
        o=independent_numeric_replay(second,self.fit,self.blind,report,model=model)
        self.assertEqual(o['head_parameter_count_each'],514)
        self.assertEqual(o['source_case_count'],len(self.fit['cases'])+len(self.blind['cases']))

    def test_strict_three_models_remain_distinct(self):
        with self.assertRaises(Invalid):
            independent_numeric_replay(self.path,self.fit,self.blind,self.report,model='mmbert_small')
        with self.assertRaises(Invalid):
            export_original_replay(Path(self.tmp.name)/'fake',self.fit,self.blind,self.report,
                                   'laya421_nochange',{}, {})

    def test_create_only_no_overwrite(self):
        vec,weights,_=self.template[self.model]
        with self.assertRaises(FileExistsError):self._create(vec,weights)
        self.assertTrue((self.path/'COMMITTED.json').is_file())

    def test_reject_missing_commit(self):
        (self.path/'COMMITTED.json').unlink()
        with self.assertRaises(Invalid):self._check()

    def test_reject_missing_weight_file(self):
        (self.path/'heads.safetensors').unlink()
        with self.assertRaises(Invalid):self._check()

    def test_reject_tampered_weight_archive_even_faked_json(self):
        p=self.path/'heads.safetensors'
        tensors=load_file(str(p)); tensors['evidence_trained.weight'][0,0]+=0.15
        save_file(tensors,str(p)); manifest=self._manifest()
        manifest['head_weights_safetensors_sha256']=_hash_bytes(p.read_bytes())
        self._put(manifest)
        with self.assertRaises(Invalid):self._check()

    def test_reject_changed_feature_bytes(self):
        p=self.path/'features.safetensors'; b=p.read_bytes();p.write_bytes(b[:-1]+bytes([b[-1]^1]))
        with self.assertRaises(Invalid):self._check()

    def test_even_new_feature_sha_cannot_forge_original_prediction(self):
        p=self.path/'features.safetensors'
        t=load_file(str(p));t['features_q24_fp32'][len(self.fit['cases']),:]+=0.7
        save_file(t,str(p))
        m=self._manifest();m['features_safetensors_sha256']=_hash_bytes(p.read_bytes());self._put(m)
        with self.assertRaisesRegex(Invalid,'prediction|disagrees'):
            self._check()

    def test_reject_wrong_feature_width_even_resigned(self):
        p=self.path/'features.safetensors';t=load_file(str(p))
        t['features_q24_fp32']=t['features_q24_fp32'][:,:128].copy();save_file(t,str(p))
        m=self._manifest();m['features_safetensors_sha256']=_hash_bytes(p.read_bytes());self._put(m)
        with self.assertRaises(Invalid):self._check()

    def test_reject_float64_feature_input(self):
        p=self.path/'features.safetensors';t=load_file(str(p))
        t['features_q24_fp32']=t['features_q24_fp32'].astype('float64');save_file(t,str(p))
        m=self._manifest();m['features_safetensors_sha256']=_hash_bytes(p.read_bytes());self._put(m)
        with self.assertRaises(Invalid):self._check()

    def test_reject_nonfinite_feature_even_resigned(self):
        p=self.path/'features.safetensors';t=load_file(str(p))
        t['features_q24_fp32'][0,0]=float('nan');save_file(t,str(p))
        m=self._manifest();m['features_safetensors_sha256']=_hash_bytes(p.read_bytes());self._put(m)
        with self.assertRaises(Invalid):self._check()

    def test_reject_symlinked_checkpoint(self):
        p=self.path/'heads.safetensors'
        renamed=self.path/'shadow-store';p.rename(renamed);p.symlink_to(renamed.name)
        with self.assertRaises(Invalid):self._check()

    def test_reject_reordered_input_cases(self):
        m=self._manifest();m['case_ids_in_original_fit_then_blind_order'].reverse()
        self._put(m)
        with self.assertRaises(Invalid):self._check()

    def test_reject_modified_report_probabilities_even_recommitted(self):
        original=self.report['control']['trained_head']['predictions']
        original[0]['positive_probability']=min(0.99999,original[0]['positive_probability']+.2)
        m=self._manifest();m['physical_prediction_report_sha256']=sha(canonical(self.report));self._put(m)
        with self.assertRaisesRegex(Invalid,'disagrees'):
            self._check()

    def test_reject_prediction_missing(self):
        self.report['control']['trained_head']['predictions'].pop()
        with self.assertRaises(Invalid):self._check()

    def test_reject_false_finaluse_or_source_signature(self):
        m=self._manifest();m['physical_origin_independently_signed']=True
        self._put(m)
        with self.assertRaises(Invalid):self._check()

    def test_reject_false_held_eval_labels_in_archive(self):
        m=self._manifest();m['original_human_held_labels_included']=True
        self._put(m)
        with self.assertRaises(Invalid):self._check()

    def test_report_pins_unmodified_head_tensors(self):
        m=self._manifest();self.assertEqual(m['schema'],SCHEMA)
        self.assertEqual(m['four_head_tensor_sha256']['evidence_frozen'],
                         m['four_head_tensor_sha256']['question_frozen'])
        self.assertNotEqual(m['four_head_tensor_sha256']['evidence_trained'],
                            m['four_head_tensor_sha256']['evidence_frozen'])

    def test_actual_pytorch_train_then_export_from_research_run(self):
        import torch  # Load before narrow source-module injection to avoid native registry issues.
        rows=self.fit['cases']+self.blind['cases']
        fake=fake_vectors(rows,256)
        tokens={r['case_id']:45 for r in rows}
        durations={r['case_id']:0.01 for r in rows}
        imp=types.ModuleType('e1_public_triplet_real_cpu')
        imp.encode_pretrained=lambda *args: (fake,tokens,{r['case_id']:'a'*64 for r in rows},
                                               {'local_model_api_requests':len(rows),
                                                'load_ms':1.,'encode_ms_by_case':durations})
        name='e1_public_triplet_real_cpu';missing=object();original=sys.modules.get(name,missing)
        sys.modules[name]=imp
        try:
            from types import SimpleNamespace
            capture={'heads':{}}
            args=SimpleNamespace(compact_checkout='pinned',gemma_checkout='pinned',gemma_manifest='pinned')
            report=run(self.fit,self.blind,'embeddinggemma_2_text',args,replay_capture=capture)
        finally:
            if original is missing:sys.modules.pop(name,None)
            else:sys.modules[name]=original
        out=Path(self.tmp.name)/'nested-original.replay'
        export_original_replay(out,self.fit,self.blind,report,'embeddinggemma_2_text',
                               capture['features'],capture['heads'])
        o=independent_numeric_replay(out,self.fit,self.blind,report,model='embeddinggemma_2_text')
        self.assertEqual(o['replayed_original_and_question_head_predictions'],192)
        self.assertFalse(o['independent_task_quality_proven'])


if __name__=='__main__':
    unittest.main()
