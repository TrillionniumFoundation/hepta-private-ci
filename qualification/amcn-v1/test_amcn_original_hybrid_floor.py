"""Strict source / original-model hybrid floor tests. No model training or gold leakage."""
from __future__ import annotations

import json
import os
from pathlib import Path
from hashlib import sha256
import tempfile
import unittest
from unittest.mock import patch

import torch
import amcn_original_hybrid_floor as hybrid
from amcn_original_numeric_probe import bert_probe, ENCODER_IDS, numeric_digest
from amcn_original_locomo_trial import sealed_write, open_pinned
from amcn_original_text_reader import file_sha


def original():
    value = os.getenv('HEPTA_AMCN_ORIGINAL_ROOT')
    if not value:
        raise unittest.SkipTest('real archived MiniLM/BERT weights not mounted')
    return Path(value)


def paired():
    value = os.getenv('HEPTA_AMCN_PAIR_ROOT')
    if not value:
        raise unittest.SkipTest('sealed six-question paired material not mounted')
    return Path(value)


class SourceSchemaControls(unittest.TestCase):
    def test_wordpiece_special_tokens_and_bound(self):
        vocab={'hello':44,'world':45,'!':46,'[CLS]':101,'[SEP]':102,'[UNK]':100}
        self.assertEqual(hybrid.bare_wordpiece('HELLO world!',vocab),[101,44,45,46,102])
        with self.assertRaisesRegex(ValueError,'context exceeds'):
            hybrid.bare_wordpiece('hello '*hybrid.MAX_SEQ,vocab)

    def test_gold_field_refused_before_loading_original_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);src=p/'source.json'
            sealed_write(src,{
                'schema':hybrid.PROFILE+'.source-only.v1',
                'original_dataset_sha256':hybrid.CORPUS_SHA256,
                'baseline_public_file_sha256':'x'*64,
                'baseline_public_payload_sha256':'y'*64,
                'full_source_corpus':{},'cases':[],
                'gold_fields_not_exported':True,'actual_future_calendar_windows':0,
                'production_accepted':False,
                'publisher_answer':'LEAK',})
            with patch.object(hybrid,'OriginalMiniLMBert') as physical:
                with self.assertRaisesRegex(ValueError,'forbidden extra fields'):
                    hybrid.rank_hybrid(src,file_sha(src),'missing',p/'public.json',p/'receipt.json')
                physical.assert_not_called()

    def test_question_sidecar_gold_refused_before_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);src=p/'source.json'
            sealed_write(src,{
                'schema':hybrid.PROFILE+'.source-only.v1',
                'original_dataset_sha256':hybrid.CORPUS_SHA256,
                'baseline_public_file_sha256':'x'*64,
                'baseline_public_payload_sha256':'y'*64,
                'full_source_corpus':{'f':[{'id':'e','root':'f','text':'hi'}]},
                'cases':[{'case_id':'q','family':'f','question':'hi',
                    'source_ids':['e'],'passages':['hi'],
                    'question_sha256':sha256(b'hi').hexdigest(),
                    'publisher_answer':'LEAK'}],
                'gold_fields_not_exported':True,'actual_future_calendar_windows':0,
                'production_accepted':False})
            with patch.object(hybrid,'OriginalMiniLMBert') as physical:
                with self.assertRaisesRegex(ValueError,'gold or changed original query'):
                    hybrid.rank_hybrid(src,file_sha(src),'missing',p/'public.json',p/'receipt.json')
                physical.assert_not_called()

    def test_full_source_extra_gold_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);src=p/'source.json'
            sealed_write(src,{
                'schema':hybrid.PROFILE+'.source-only.v1',
                'original_dataset_sha256':hybrid.CORPUS_SHA256,
                'baseline_public_file_sha256':'x'*64,
                'baseline_public_payload_sha256':'y'*64,
                'full_source_corpus':{'f':[{'id':'e','root':'f','text':'hi',
                    'gold_support':True}]},
                'cases':[],'gold_fields_not_exported':True,
                'actual_future_calendar_windows':0,'production_accepted':False})
            with patch.object(hybrid,'OriginalMiniLMBert') as physical:
                with self.assertRaisesRegex(ValueError,'gold-bearing'):
                    hybrid.rank_hybrid(src,file_sha(src),'missing',p/'public.json',p/'receipt.json')
                physical.assert_not_called()

    def test_wrong_sha_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.json';sealed_write(p,{'k':1})
            with self.assertRaisesRegex(ValueError,'external exact source SHA'):
                hybrid.rank_hybrid(p,'0'*64,'missing',p.with_name('new.json'),p.with_name('r.json'))

    def test_unknown_mixing_weight_refused_before_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);src=p/'source.json'
            sealed_write(src,{
                'schema':hybrid.PROFILE+'.source-only.v1',
                'original_dataset_sha256':hybrid.CORPUS_SHA256,
                'baseline_public_file_sha256':'x'*64,
                'baseline_public_payload_sha256':'y'*64,
                'full_source_corpus':{},'cases':[],
                'gold_fields_not_exported':True,
                'actual_future_calendar_windows':0,'production_accepted':False})
            with patch.object(hybrid,'OriginalMiniLMBert') as physical:
                with self.assertRaisesRegex(ValueError,'frozen prior'):
                    hybrid.rank_hybrid(src,file_sha(src),'missing',p/'new.json',p/'r.json',dense_weight=0.7)
                physical.assert_not_called()

    def test_create_only_cannot_replace_original_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);src=p/'source.json'
            sealed_write(src,{'k':1})
            with self.assertRaisesRegex(ValueError,'create-only'):
                sealed_write(src,{'k':2})


class PhysicalOriginalMiniLM(unittest.TestCase):
    def test_original_numeric_cls_matches_independent_prior(self):
        directory=original()/'encoder'
        torch.set_num_threads(2)
        model=hybrid.OriginalMiniLMBert(directory)
        with torch.inference_mode():
            ids=torch.tensor([ENCODER_IDS])
            x=model._bert_forward(ids,torch.ones_like(ids,dtype=torch.bool))
        independent=bert_probe(directory/'model.safetensors')
        self.assertEqual(numeric_digest(x[0,0]),independent['cls_sha256'])
        self.assertEqual(x.shape,(1,len(ENCODER_IDS),384))

    def test_original_model_tamper_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'model.safetensors').write_bytes(b'fake')
            (p/'tokenizer.json').write_bytes(b'fake')
            (p/'vocab.txt').write_text('bad')
            with self.assertRaisesRegex(ValueError,'original MiniLM'):
                hybrid.OriginalMiniLMBert(p)


class RealPairedOriginalAnswers(unittest.TestCase):
    def test_complete_original_six_questions_negative(self):
        loc=paired()
        name=['old_public','old_answers','hybrid_public','hybrid_answers','withheld','hybrid_receipt']
        paths=[loc/f'{k}.json' for k in name]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('optional exact original six-arm files not mounted')
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'score.json'
            res=hybrid.score_paired(*(v for p in paths for v in (p,file_sha(p))),output)
            self.assertEqual(res['questions'],6)
            self.assertEqual(res['independent_source_families_upper_bound'],2)
            self.assertEqual(res['original_support_covered_at_k'],3)
            self.assertEqual(res['hybrid_support_covered_at_k'],3)
            self.assertEqual(res['original_literal_match'],0)
            self.assertEqual(res['hybrid_literal_match'],0)
            self.assertFalse(res['exact_total_input_compute_budget_matched'])
            self.assertIsNone(res['independent_semantic_success'])
            self.assertFalse(res['production_accepted'])

    def test_changed_model_origin_refused_even_with_consistent_answer_sha(self):
        loc=paired()
        paths=[loc/f'{k}.json' for k in ['old_public','old_answers','hybrid_public','hybrid_answers','withheld','hybrid_receipt']]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest('optional original six-arm source files not mounted')
        with tempfile.TemporaryDirectory() as tmp:
            fixed=list(paths)
            data=json.loads(fixed[3].read_bytes());data['original_reader_model_sha256']='0'*64
            fixed[3]=Path(tmp)/'forged-hybrid.json';sealed_write(fixed[3],data)
            with self.assertRaisesRegex(ValueError,'different Reader/model'):
                hybrid.score_paired(*(v for p in fixed for v in (p,file_sha(p))),Path(tmp)/'score.json')

if __name__=='__main__':unittest.main()
