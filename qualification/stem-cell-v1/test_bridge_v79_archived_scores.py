"""Genuine original V6/V7 source binding and source-only feature adversarial tests."""
import copy
from pathlib import Path
import os
import tempfile
import unittest
import numpy as np

from bridge_v79_archived_scores import (SEEDS, V6_SHA, V7_SHA, file_bytes, load_sources,
    original_logits,score,encode,make_features)
from bridge_v79_score_cell_train import ARMS,UPDATES,BATCH,GatedNewHead,sampling,parameter_sha,head_identity

V6=Path(os.environ.get('HEPTA_V6_ORIGINAL_ARCHIVE','/nonexistent/needs-hepta-V6-evidence.zip'))
V7=Path(os.environ.get('HEPTA_V7_ORIGINAL_ARCHIVE','/nonexistent/needs-hepta-V7-evidence.zip'))

class GenuineSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not V6.exists() or not V7.exists():
            raise unittest.SkipTest('exact SHA-pinned original V6/V7 archives not provisioned')
        cls.original=load_sources(V6,V7)

    def test_real_original_three_seed_inputs_are_exact(self):
        x=self.original
        self.assertEqual((len(x['train']),len(x['tune'])),(3909,827))
        self.assertEqual((len(x['train_source_groups']),len(x['tune_source_groups'])),(64,16))
        self.assertEqual(set(x['reports']),set(SEEDS))
        self.assertEqual(V6_SHA,x['archive_sha256']['v6'])
        self.assertEqual(V7_SHA,x['archive_sha256']['v7'])
        for seed in SEEDS:
            self.assertEqual(len(x['reports'][seed]['train_p']),3909)
            self.assertEqual(len(x['reports'][seed]['tune_p']),827)
            self.assertNotEqual(x['reports'][seed]['model_sha256'],x['reports'][seed]['train_panel_sha256'])

    def test_source_only_features_ignore_labels_evidence_ids_and_scope(self):
        x=self.original['train'][0]
        y=copy.deepcopy(x)
        y['label']=1-y['label']
        y['source_hash']='e'*64
        y['answer_id']='injected'
        y['question_id']='injected'
        y['evidence_sentence_indices']=[99]
        f=encode(x,.42)
        self.assertTrue(np.array_equal(f,encode(y,.42)))
        self.assertEqual(f.shape,(97,))
        y['candidate']+=' malicious additional candidate tokens'
        self.assertFalse(np.array_equal(f,encode(y,.42)))

    def test_score_ablation_exact_and_old_baseline(self):
        x=self.original
        for seed in SEEDS:
            s=x['reports'][seed]
            features=make_features(x['train'][:8],s['train_p'][:8],mode='score_only')
            self.assertTrue(np.equal(features[:,3:],0).all())
            self.assertGreater(float(np.abs(make_features(x['train'][:8],s['train_p'][:8],mode='score_text')[:,3:]).max()),0.)
            baseline=score(x['tune'],[int(p>.5) for p in s['tune_p']])
            self.assertEqual((baseline['source_groups'],baseline['questions']),(16,194))
        self.assertEqual(original_logits([.2,.5,.9]).shape,(3,2))

    def test_source_balanced_sampler_chooses_16_original_paragraphs_per_step(self):
        x=self.original['train']
        for seed in SEEDS:
            self.assertEqual(sampling(x,seed=seed,kind='source'),sampling(x,seed=seed,kind='source'))
            for ix in sampling(x,seed=seed,kind='source'):
                self.assertEqual(len(ix),BATCH)
                self.assertEqual(len({x[j]['source_hash'] for j in ix}),BATCH)
        self.assertEqual(len(sampling(x,seed=41,kind='row')),UPDATES)

    def test_original_wrong_source_bytes_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            temp=Path(td)
            path=temp/'fake-v7.zip'
            content=file_bytes(V7,'v7')
            path.write_bytes(content[:-1]+bytes([content[-1]^1]))
            with self.assertRaisesRegex(ValueError,'SHA256'):
                load_sources(V6,path)
            link=temp/'symbolic-source.zip'
            link.symlink_to(V6)
            with self.assertRaisesRegex(ValueError,'symlink'):
                file_bytes(link,'v6')

    def test_exact_gated_head_1700_and_bitwise_zero_residual(self):
        import torch
        h=GatedNewHead(49)
        self.assertEqual(sum(p.numel() for p in h.parameters()),1700)
        self.assertEqual(len(head_identity(h)),6)
        x=torch.randn(12,97)
        a=torch.randn(12,2)
        self.assertTrue(torch.equal(a,h(x,a)))
        self.assertEqual(len(parameter_sha(h)),64)
        self.assertEqual(tuple(ARMS),('score_only_row','score_only_source','score_text_row','score_text_source'))

    def test_no_alternate_granite_97d_identity_claims(self):
        self.assertFalse(self.original['original_granite_encoder_loaded'])
        self.assertTrue(self.original['labels_are_original_human'])
        with self.assertRaises(ValueError):
            make_features(self.original['tune'][:1],[.5],mode='hidden_original')

if __name__=='__main__':unittest.main()
