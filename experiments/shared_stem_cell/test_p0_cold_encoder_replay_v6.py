"""Synthetic CPU data integrity tests for real-checkpoint cold Encoder protocol.

No test in this module loads public pretrained weights or establishes efficacy.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

import numpy as np
from safetensors.numpy import load_file,save_file

from p0_multirc_semantic_execute import fit_head
from p0_question_only_head import fit_question_only
from p0_multirc_semantic_material import Invalid,canonical
from p0_physical_replay_v5 import (export_original_replay,independent_numeric_replay,
                                    _hash_bytes)
from p0_cold_encoder_replay_v6 import (checked_probe,review_cold_vectors,
                                       real_cold_run,SCHEMA,PAIRS_PER_SPLIT,
                                       MAX_Q24_DELTA)
from test_p0_multirc_semantic import setup,mocked_report
from test_p0_question_only_matched import fake_vectors


class ColdEncoderCausalIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,cls.fit,cls.blind,_=setup()
        cls.model='embeddinggemma_2_text'
        rows=cls.fit['cases']+cls.blind['cases']
        raw=fake_vectors(rows,256)
        # Model runner actually returns Q24 values, backed by FP32 tensors.
        # Pure synthetic float64 features would induce a spurious one-unit drift
        # during replay and must not be called exact physical Q24 equality.
        cls.features={k:[float(np.float32(round(v*(2**24))/(2**24))) for v in row]
                      for k,row in raw.items()}
        heads={}
        trained=fit_head(cls.fit['cases'],cls.blind['cases'],cls.features,256,replay_heads=heads)
        prior=fit_question_only(cls.fit,cls.blind,cls.features,256,trained,replay_heads=heads)
        report=mocked_report(cls.model,cls.fit,cls.blind)
        report['training']=trained;report['control']=trained['controls']
        report['matched_question_only_control']=prior
        profile=report['complete_source_profiles']
        profile['physical_token_counts_by_case']={r['case_id']:47 for r in rows}
        profile['physical_encoder_api_requests']=len(rows)
        cls.report=report
        cls.heads=heads
        cls.selected=checked_probe(cls.fit,cls.blind)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)/'original.replay'
        self.report=copy.deepcopy(self.report)
        export_original_replay(self.directory,self.fit,self.blind,self.report,
                               self.model,self.features,self.heads)
        self.recode={r['case_id']:list(self.features[r['case_id']]) for r in self.selected}
        self.tok={r['case_id']:47 for r in self.selected}
        self.hashes={r['case_id']:'a'*64 for r in self.selected}
        self.physical={'load_ms':16.,'local_model_api_requests':len(self.selected),
                       'encode_ms_by_case':{r['case_id']:0.1 for r in self.selected},
                       'physical_transformer_forward_count_attested':False}

    def judge(self):
        return review_cold_vectors(self.fit,self.blind,self.report,self.model,
                                   self.directory,self.selected,self.recode,self.tok,
                                   self.hashes,self.physical)

    def test_all_splits_original_and_prior_source_distinct(self):
        self.assertEqual(len(self.selected),12)
        for part in ('train','calibration','test'):
            rows=[r for r in self.selected if r['split']==part]
            self.assertEqual(len(rows),4)
            self.assertEqual(len({r['source_group'] for r in rows}),PAIRS_PER_SPLIT)
            self.assertEqual({r['condition'] for r in rows},{'original','no_evidence'})
        self.assertTrue(all('label' not in r for r in self.selected if r['split']=='test'))

    def test_real_torch_sgd_then_independent_cold_q24_parity_on_synthetic_vectors(self):
        r=self.judge()
        self.assertEqual(r['schema'],SCHEMA)
        self.assertEqual(r['cold_probed_case_count'],12)
        self.assertEqual(r['max_q24_disagreement'],0)
        self.assertFalse(r['actual_original_model_source_independently_signed'])
        self.assertFalse(r['production_promotion_permitted'])

    def test_reject_reordered_or_fabricated_probe_even_if_features_match(self):
        swapped=list(reversed(self.selected))
        with self.assertRaisesRegex(Invalid,'selector'):
            review_cold_vectors(self.fit,self.blind,self.report,self.model,
                    self.directory,swapped,self.recode,self.tok,self.hashes,self.physical)
        forged=copy.deepcopy(self.selected)
        forged[0]['original_question_text']='injected alternate question'
        with self.assertRaisesRegex(Invalid,'selector'):
            review_cold_vectors(self.fit,self.blind,self.report,self.model,
                    self.directory,forged,self.recode,self.tok,self.hashes,self.physical)

    def test_cold_ci_never_downloads_held_labels_and_gates_scoring(self):
        text=(Path(__file__).resolve().parents[2] / 
               '.github/workflows/hepta-p0-multirc-semantic-four.yml').read_text()
        cold=text.split('  independent-cold-pretrained-encoder:',1)[1].split('  independent-human-score:',1)[0]
        self.assertNotIn('owner-only-human-labels',cold)
        self.assertIn('p0_cold_encoder_replay_v6.py',cold)
        self.assertIn('independent-pretrained-replay',cold)
        self.assertIn('e05f939f65fb76f6bdbf7470eef7e63b77284dcd',cold)
        self.assertIn('f8d168a7689eb3624d97c44751791badd069e521',cold)
        self.assertIn('independent-cold-pretrained-encoder]',text)

    def test_registered_selection_is_repeatable(self):
        self.assertEqual([r['case_id'] for r in self.selected],
                         [r['case_id'] for r in checked_probe(self.fit,self.blind)])

    def test_cold_change_beyond_two_q24_steps_fails(self):
        self.recode[self.selected[0]['case_id']][0] += 5/(2**24)
        with self.assertRaisesRegex(Invalid,'disagrees'):
            self.judge()

    def test_registered_tolerance_boundary(self):
        # Within declared tolerance must remain visible, not counted as exact.
        self.recode[self.selected[0]['case_id']][0] += 1/(2**24)
        r=self.judge()
        self.assertEqual(r['max_q24_disagreement'],1)
        self.assertEqual(r['registered_max_q24_difference'],MAX_Q24_DELTA)

    def test_missing_original_model_call_fails(self):
        self.physical['local_model_api_requests']-=1
        with self.assertRaises(Invalid):self.judge()

    def test_wrong_token_from_same_source_fails(self):
        self.tok[self.selected[0]['case_id']]+=1
        with self.assertRaisesRegex(Invalid,'tokenizer'):
            self.judge()

    def test_missing_cold_encoder_timing_fails(self):
        self.physical['encode_ms_by_case'].pop(self.selected[0]['case_id'])
        with self.assertRaises(Invalid):self.judge()

    def test_wrong_model_alias_fails_even_with_same_width(self):
        with self.assertRaises(Invalid):
            review_cold_vectors(self.fit,self.blind,self.report,'mmbert_small',
                                self.directory,self.selected,self.recode,self.tok,
                                self.hashes,self.physical)

    def test_random_input_or_missing_cold_feature_fails(self):
        self.recode.pop(self.selected[0]['case_id'])
        with self.assertRaises(Invalid):self.judge()

    def test_cold_invocation_cannot_claim_signed_publisher_proof(self):
        self.physical['physical_transformer_forward_count_attested']=True
        with self.assertRaises(Invalid):self.judge()

    def test_original_saved_training_feature_tamper_resigned_passes_v5_but_fails_v6(self):
        # V5 replay tests held predictions, not training features. Independent
        # pretrained re-forward catches a changed TRAIN feature even if its
        # safetensors digest is updated consistently with the altered bytes.
        target=next(r for r in self.selected if r['split']=='train')
        index=[r['case_id'] for r in self.fit['cases']+self.blind['cases']].index(target['case_id'])
        path=self.directory/'features.safetensors'
        data=load_file(str(path));data['features_q24_fp32'][index,0]+=1e-4
        save_file(data,str(path))
        c=self.directory/'COMMITTED.json';m=json.loads(c.read_text())
        m['features_safetensors_sha256']=_hash_bytes(path.read_bytes())
        c.write_bytes(canonical(m)+b'\n')
        independent_numeric_replay(self.directory,self.fit,self.blind,self.report,model=self.model)
        with self.assertRaisesRegex(Invalid,'disagrees'):self.judge()

    def test_wrong_original_model_source_receipt_fails(self):
        self.report['model_revision']='f'*40
        with self.assertRaises(Invalid):self.judge()

    def test_producer_report_missing_token_inventory_fails(self):
        self.report['complete_source_profiles']['physical_token_counts_by_case']={}
        with self.assertRaises(Invalid):self.judge()

    def test_fake_main_loader_not_autoselected(self):
        # Test-only module substitution is narrowly scoped. The production CLI
        # hard-wires the reviewed e1_public_triplet_real_cpu loader and has no
        # model-ID fallback, placeholder probabilities or target-answer access.
        fake=types.ModuleType('e1_public_triplet_real_cpu')
        calls=[]
        def pretend(selected,model,*rest):
            calls.append((model,len(selected)))
            return self.recode,self.tok,self.hashes,self.physical
        fake.encode_pretrained=pretend
        name='e1_public_triplet_real_cpu';missing=object();old=sys.modules.get(name,missing)
        sys.modules[name]=fake
        try:
            out=real_cold_run(self.fit,self.blind,self.report,self.model,
                              self.directory,'pinned','pinned','pinned')
        finally:
            if old is missing:sys.modules.pop(name,None)
            else:sys.modules[name]=old
        self.assertEqual(calls,[(self.model,12)])
        self.assertEqual(out['exact_feature_match_cases'],12)
        self.assertFalse(out['physical_gpu_worker_attestation'])

    def test_mmbert_full_checkpoint_bytes_must_match_original(self):
        from p0_multirc_semantic_review import REVISIONS
        # Pure verifier is exercised on complete same-width non-Gemma report.
        model='mmbert_small';width=384
        rows=self.fit['cases']+self.blind['cases']
        x=fake_vectors(rows,width)
        tensors={}
        train=fit_head(self.fit['cases'],self.blind['cases'],x,width,replay_heads=tensors)
        prior=fit_question_only(self.fit,self.blind,x,width,train,replay_heads=tensors)
        report=mocked_report(model,self.fit,self.blind)
        report.update(training=train,control=train['controls'],matched_question_only_control=prior)
        report['complete_source_profiles']['physical_token_counts_by_case']={r['case_id']:45 for r in rows}
        report['complete_source_profiles']['physical_encoder_api_requests']=len(rows)
        report['complete_source_profiles']['source_checkpoint_sha256']='d'*64
        d=Path(self.tmp.name)/'mmbert.replay'
        export_original_replay(d,self.fit,self.blind,report,model,x,tensors)
        ids=[r['case_id'] for r in self.selected]
        obs={'load_ms':1.,'local_model_api_requests':12,
             'encode_ms_by_case':{i:0.2 for i in ids},
             'physical_transformer_forward_count_attested':False,
             'mmbert_all_serialized_weights_byte_verified':True,
             'mmbert_whole_pretrained_checkpoint_sha256':'e'*64}
        with self.assertRaisesRegex(Invalid,'mmBERT'):
            review_cold_vectors(self.fit,self.blind,report,model,d,self.selected,
                                {i:x[i] for i in ids},{i:45 for i in ids},
                                {i:'a'*64 for i in ids},obs)

if __name__=='__main__':unittest.main()
