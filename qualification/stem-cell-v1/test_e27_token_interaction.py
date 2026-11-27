"""Synthetic-input mechanism tests only; no pretrained-model efficacy claims."""

import copy
from dataclasses import replace
from hashlib import sha256
import math
import unittest

import torch

from e27_token_interaction import (AUTHORITY, SCHEMA, TokenInteractionHead,
    validate_material, make_feature_bank, train_head, blind_predict)
from e27_reader_owner import (material_owner, execute, OriginalModernBERT,
    select_groups, strict_read, write_once)


def _raw(pid, split):
    rows = []
    for qid in range(2):
        for aid in range(3):
            rows.append({'paragraph': f'pub-{split}-evidence-{pid}',
                         'question':f'question {split} {pid} {qid}',
                         'answer':f'candidate {split} {pid} {qid} {aid}',
                         'label':int(aid==1),
                         'idx':{'paragraph':pid,'question':qid,'answer':aid}})
    return rows


def fixture_material():
    train = [x for i in range(48) for x in _raw(i,'train')]
    val = [x for i in range(8) for x in _raw(i,'validation')]
    return material_owner(train,val)


class FakeSharedEncoder:
    """Actual torch computation on synthetic symbols, never pretrained weights."""
    def __init__(self):
        self.forward_calls = 0
        self.cpu_ns = 1
        self.wall_ns = 1
        self.total_tokens = 1
        self.truncated_sequences = 0
    def __call__(self,text,*,token_sequence):
        seed = int.from_bytes(sha256(text.encode()).digest()[:4],'big')
        g = torch.Generator().manual_seed(seed)
        self.forward_calls += 1
        self.cpu_ns += 500
        self.wall_ns += 600
        self.total_tokens += 8
        return torch.randn((5, 8),generator=g) if token_sequence else torch.randn((8,),generator=g)


class TokenHeadContract(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.train, self.held, self.gold, self.selection = fixture_material()

    def test_complete_synthetic_material_and_role_isolation(self):
        self.assertEqual((validate_material(self.train,mode='train')[2],
                          validate_material(self.held,mode='held')[2]),(288,48))
        self.assertEqual(self.selection['train_selected_passages'],48)
        self.assertEqual(self.selection['held_selected_passages'],8)
        self.assertEqual(len(self.gold['cases']),48)
        self.assertFalse(self.selection['prospective_future_family_or_time'])

    def test_train_source_selection_ignores_values_of_original_labels(self):
        source=[x for i in range(48) for x in _raw(i,'train')]
        before=select_groups(source,split='train',limit=48)
        for r in source:r['label']=1-r['label']
        after=select_groups(source,split='train',limit=48)
        self.assertEqual([(r['group_id'],[(q['question_id'],
            [x['candidate_id'] for x in q['candidates']]) for q in r['questions']]) for r in before[0]],
            [(r['group_id'],[(q['question_id'],
            [x['candidate_id'] for x in q['candidates']]) for q in r['questions']]) for r in after[0]])

    def test_held_label_injection_rejected(self):
        held=copy.deepcopy(self.held)
        held['groups'][0]['questions'][0]['candidates'][0]['label']=1
        with self.assertRaises(ValueError): validate_material(held,mode='held')

    def test_train_constant_label_without_mixed_question_rejected(self):
        tr=copy.deepcopy(self.train)
        for group in tr['groups']:
            for q in group['questions']:
                for c in q['candidates']: c['label']=1
        with self.assertRaises(ValueError):validate_material(tr,mode='train')

    def test_duplicate_original_source_or_answer_rejected(self):
        held=copy.deepcopy(self.held)
        held['groups'][1]['group_id']=held['groups'][0]['group_id']
        with self.assertRaises(ValueError): validate_material(held,mode='held')
        held=copy.deepcopy(self.held)
        c=held['groups'][0]['questions'][0]['candidates']
        c[1]['candidate_id']=c[0]['candidate_id']
        with self.assertRaises(ValueError): validate_material(held,mode='held')

    def test_trainable_parameter_count_is_small_and_matched(self):
        m=TokenInteractionHead(768)
        self.assertLess(sum(p.numel() for p in m.parameters()), 50_000)
        self.assertGreater(sum(p.numel() for p in m.parameters()), 30_000)
        self.assertTrue(all(p.requires_grad for p in m.parameters()))

    def test_question_answer_token_interaction_is_not_inert(self):
        torch.manual_seed(19)
        model=TokenInteractionHead(8)
        e=torch.randn(5,8);q=torch.randn(8);a1=torch.randn(8);a2=torch.randn(8)
        y1=model(e,q,a1);y2=model(e,q,a2)
        self.assertGreater(abs((y1-y2).item()),1e-10)
        self.assertEqual(float(model(e,q,a1,answer_visible=False).detach()),
                         float(model(e,q,a2,answer_visible=False).detach()))

    def test_physical_synthetic_torch_training_with_same_parameter_budget(self):
        fake=FakeSharedEncoder()
        bank,calls=make_feature_bank(self.train,embedder=fake)
        self.assertEqual((len(bank),calls),(288,48+96+288))
        aware,a=train_head(bank,answer_visible=True)
        muted,b=train_head(bank,answer_visible=False)
        self.assertEqual((a['optimizer_steps'],b['optimizer_steps']), (64,64))
        self.assertEqual(a['parameter_count'],b['parameter_count'])
        self.assertTrue(a['fit_cpu_ns'] > 0 and b['fit_cpu_ns'] > 0)
        self.assertTrue(torch.isfinite(next(aware.parameters())).all())
        self.assertTrue(torch.isfinite(next(muted.parameters())).all())

    def test_blind_pretrained_claim_is_always_false_for_fake_encoder(self):
        out=execute(self.train,self.held,embedder=FakeSharedEncoder())
        self.assertEqual(len(out['predictions']),48)
        self.assertEqual(out['train_shared_encoder_calls'],48+96+288)
        self.assertEqual(out['held_shared_encoder_calls'],8+16+48)
        self.assertFalse(out['real_pretrained_encoder'])
        self.assertEqual(out['authority'],AUTHORITY)
        self.assertFalse(out['task_gain_established'])

    def test_held_truth_cannot_be_used_by_predictor(self):
        bank,_=make_feature_bank(self.held,embedder=FakeSharedEncoder())
        fake=TokenInteractionHead(8)
        predictions=blind_predict(bank,fake,fake)
        self.assertEqual(len(predictions),48)
        with self.assertRaises(ValueError):
            blind_predict((replace(bank[0],label=1),)+bank[1:],fake,fake)

    def test_unapproved_pretrained_checkpoint_denied_before_import(self):
        with self.assertRaises(ValueError): OriginalModernBERT('/tmp/nonexistent-public-model')

    def test_strict_duplicate_key_and_create_only(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'candidate.json'
            write_once(p,{'x':1})
            with self.assertRaises(FileExistsError):write_once(p,{'x':2})
            p.write_text('{"x":1,"x":2}')
            with self.assertRaises(ValueError):strict_read(p)


if __name__=='__main__':unittest.main()
