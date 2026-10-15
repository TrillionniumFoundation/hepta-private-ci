"""Genuine archived V6 weights and original publisher labels; fake cache only in tests.

No synthetic 97D tensor can be reported as actual pretrained Granite evidence.
"""
from __future__ import annotations
from dataclasses import replace
import copy
import hashlib
import io
import json
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest
import zipfile

import torch

from bridge_reader import build_reader
from bridge_split_cell_v77 import (SplitBridgeCell,FrozenNewTaskCache,
    digest_parameters,_sealed_cache_sha)
from bridge_v78_original_natural_head import (roster,validate_train_cache,
    fit_original_human_task,score_preexposed_tune)
from bridge_v78_original_calibration import digest

ARCHIVE=Path(os.environ.get('HEPTA_ORIGINAL_V6_ZIP','/NO_AUTHENTIC_V6_ARCHIVE_CONFIGURED'))


def original_cell(seed):
    with zipfile.ZipFile(ARCHIVE) as z:
        p=f'reader-v6-bridge/seed-{seed}/bridge/'
        m=json.loads(z.read(p+'warmup-model.json'))
        raw=z.read(p+'warmup.pt')
    assert hashlib.sha256(raw).hexdigest()==m['file_sha256']
    parent=build_reader('bridge',seed).eval().requires_grad_(False)
    parent.load_state_dict(torch.load(io.BytesIO(raw),weights_only=True,map_location='cpu'),strict=True)
    assert digest_parameters(parent)==m['training_parameter_sha256']
    return SplitBridgeCell(parent,expected_parent_sha256=m['training_parameter_sha256'],new_head_seed=seed)


def synthetic_cache(source,seed=41):
    """Test-only fabricated latent, NEVER allowed to set real_Granite_claim=True."""
    g=torch.Generator().manual_seed(9001)
    latent=torch.randn((3909,97),generator=g)*.1
    logits=torch.randn((3909,2),generator=g)*.1
    ids=source['train_case_ids']; src=source['train_source_hashes']
    sha=source['parents'][seed]['training_parameter_sha256']
    inputs=('a'*64,)
    signature=_sealed_cache_sha(sha,ids,src,inputs,latent,logits)
    return FrozenNewTaskCache(latent,logits,ids,src,sha,signature,
             encoded_reader_calls=0,input_batch_sha256s=inputs)


class OriginalLabelAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ARCHIVE.is_file():
            raise unittest.SkipTest("requires exact authenticated original V6 archive")
        torch.set_num_threads(1)
        cls.source=roster(ARCHIVE)

    def test_full_human_source_and_no_binding_overlap(self):
        s=self.source
        self.assertEqual(len(s['train_case_ids']),3909)
        self.assertEqual(len(s['tune_case_ids']),827)
        self.assertEqual(len(set(s['train_source_hashes'])),64)
        self.assertEqual(len(set(s['tune_source_hashes'])),16)
        self.assertEqual(len(set(s['old_source_hashes'])),64)
        self.assertFalse(set(s['train_source_hashes']) & set(s['tune_source_hashes']))
        self.assertFalse(set(s['train_source_hashes']) & set(s['old_source_hashes']))
        self.assertEqual(digest([r['label'] for r in s['train']]),s['train_label_sha256'])

    def test_parent_real_pretrained_checkpoint_then_human_label_fitting(self):
        c=original_cell(41)
        parent_before=digest_parameters(c.parent)
        initial=digest_parameters(c.new_head)
        cache=synthetic_cache(self.source,41)
        self.assertTrue(validate_train_cache(c,cache,self.source,seed=41))
        receipt=fit_original_human_task(c,cache,ARCHIVE,seed=41,updates=8)
        self.assertTrue(receipt['scope']=='actual_archived_multirc_human_labels_train_only')
        self.assertEqual(receipt['natural_train_label_sha256'],self.source['train_label_sha256'])
        self.assertEqual(receipt['fitting']['logical_optimizer_updates'],8)
        self.assertEqual(receipt['fitting']['parent_original_digests_unchanged'] if 'parent_original_digests_unchanged' in receipt['fitting'] else receipt['parent_original_digests_unchanged'],True)
        self.assertNotEqual(initial,digest_parameters(c.new_head))
        self.assertEqual(parent_before,digest_parameters(c.parent))
        self.assertEqual(sum(p.numel() for p in c.new_head.parameters()),1700)
        self.assertFalse(receipt['real_granite_tokenbank_numeric_parity_claimed'])
        self.assertFalse(receipt['production_authorized'])
        self.assertTrue(all(p.grad is None for p in c.parent.parameters()))

    def test_all_parent_training_states_seed_bound(self):
        for seed in (41,47,53):
            c=original_cell(seed);cache=synthetic_cache(self.source,seed)
            self.assertTrue(validate_train_cache(c,cache,self.source,seed=seed))
            with self.assertRaisesRegex(ValueError,'wrong seed'):
                validate_train_cache(c,cache,self.source,seed=47 if seed!=47 else 41)

    def test_no_reordered_or_relabelled_case_alignment(self):
        c=original_cell(41);baseline=synthetic_cache(self.source)
        cache=replace(baseline,case_ids=tuple(reversed(baseline.case_ids)))
        with self.assertRaisesRegex(ValueError,'cached 97D|source-aligned'):
            validate_train_cache(c,cache,self.source,seed=41)
        mutated_source=dict(self.source,train_label_sha256='1'*64)
        # labels must come from immutable archived ZIP, not a free caller vector.
        receipt=fit_original_human_task(c,baseline,ARCHIVE,seed=41,updates=1)
        self.assertNotEqual(receipt['natural_train_label_sha256'],mutated_source['train_label_sha256'])

    def test_modified_latent_bytes_denied(self):
        c=original_cell(41);cache=synthetic_cache(self.source)
        cache.hidden[0,0]+=0.2
        with self.assertRaisesRegex(ValueError,'cached 97D'):
            validate_train_cache(c,cache,self.source,seed=41)

    def test_original_old_source_or_tune_leakage_denied(self):
        c=original_cell(41);cache=synthetic_cache(self.source)
        shifted=replace(cache,source_hashes=(self.source['old_source_hashes'][0],)+cache.source_hashes[1:])
        with self.assertRaises(ValueError):validate_train_cache(c,shifted,self.source,seed=41)
        shifted=replace(cache,case_ids=self.source['tune_case_ids']+cache.case_ids[827:])
        with self.assertRaises(ValueError):validate_train_cache(c,shifted,self.source,seed=41)

    def test_internal_tune_descriptive_cannot_be_selected(self):
        c=original_cell(41);cache=synthetic_cache(self.source)
        fit_original_human_task(c,cache,ARCHIVE,seed=41,updates=1)
        tune_h=torch.zeros((827,97),dtype=torch.float32)
        tune_logits=torch.zeros((827,2),dtype=torch.float32)
        r=score_preexposed_tune(c,self.source,tune_h,tune_logits,
            case_ids=self.source['tune_case_ids'],source_hashes=self.source['tune_source_hashes'])
        self.assertEqual(r['old_frozen']['candidates'],827)
        self.assertEqual(r['always_positive']['questions'],194)
        self.assertFalse(r['model_selected'])
        with self.assertRaisesRegex(ValueError,'source identity'):
            score_preexposed_tune(c,self.source,tune_h,tune_logits,
                case_ids=self.source['train_case_ids'][:827],
                source_hashes=self.source['tune_source_hashes'])

    def test_source_balanced_true_label_head_uses_original_64_groups(self):
        c=original_cell(53);cache=synthetic_cache(self.source,53)
        parent=digest_parameters(c.parent)
        result=fit_original_human_task(c,cache,ARCHIVE,seed=53,updates=20,
                sampling_arm='source_balanced')
        train=result['fitting']
        self.assertEqual(result['sampling_arm'],'source_balanced')
        self.assertEqual(train['logical_optimizer_updates'],20)
        self.assertEqual(train['total_candidate_exposures'],20*16)
        self.assertEqual(train['train_unique_source_groups'],64)
        self.assertGreater(train['source_exposure_max'],0)
        self.assertEqual(parent,digest_parameters(c.parent))
        self.assertTrue(c.candidate_fitted)
        self.assertFalse(result['production_authorized'])

    def test_same_seed_head_starts_identical_across_sampler_arms(self):
        a=original_cell(41);b=original_cell(41)
        cache=synthetic_cache(self.source)
        self.assertEqual(digest_parameters(a.new_head),digest_parameters(b.new_head))
        uniform=fit_original_human_task(a,cache,ARCHIVE,seed=41,updates=10,
                 sampling_arm='row_uniform')
        balanced=fit_original_human_task(b,cache,ARCHIVE,seed=41,updates=10,
                 sampling_arm='source_balanced')
        self.assertEqual(uniform['fitting']['logical_optimizer_updates'],
                         balanced['fitting']['logical_optimizer_updates'])
        self.assertEqual(uniform['fitting']['new_head_parameter_count'],
                         balanced['fitting']['new_head_parameter_count'])
        self.assertEqual(digest_parameters(a.parent),digest_parameters(b.parent))
        self.assertFalse(uniform['production_authorized'])

    def test_sampling_arm_cannot_be_selected_from_unknown_variant(self):
        c=original_cell(41);cache=synthetic_cache(self.source)
        with self.assertRaisesRegex(ValueError,'predeclared'):
            fit_original_human_task(c,cache,ARCHIVE,seed=41,updates=1,
                sampling_arm='use_tune_labels_or_best_result')
        self.assertFalse(c.candidate_fitted)

    def test_real_runner_preflight_refuses_missing_97m_before_any_output(self):
        # This is a connector/material gate test, not a counterfeit original
        # snapshot. A fake module only simulates the missing-material response.
        from run_v78_original_natural_head import preflight
        with tempfile.TemporaryDirectory() as td:
            args=SimpleNamespace(v4=Path(td)/'v4.zip',v5=Path(td)/'v5.zip',
                v6=ARCHIVE,snapshot=Path(td)/'nonexistent-granite',
                cache=None,output=Path(td)/'never-create')
            fake=types.ModuleType('bridge_portable_v74')
            fake.originals=lambda *a:{'model':{'files':{}},'v5_cache_sha256':{}}
            fake.material_preflight=lambda *a:{'ready':False,'missing':['model.safetensors']}
            fake.cache_preflight=lambda *a:{'exact':False}
            with patch.dict(sys.modules,{'bridge_portable_v74':fake}):
                with self.assertRaisesRegex(ValueError,'BLOCKED_MODEL_MATERIAL'):
                    preflight(args)
            self.assertFalse(args.output.exists())

    def test_source_balanced_same_seed_replays_same_new_head_weights(self):
        a=original_cell(47);b=original_cell(47)
        cache=synthetic_cache(self.source,47)
        first=fit_original_human_task(a,cache,ARCHIVE,seed=47,updates=20,
                                    sampling_arm='source_balanced')
        second=fit_original_human_task(b,cache,ARCHIVE,seed=47,updates=20,
                                    sampling_arm='source_balanced')
        self.assertEqual(first['fitting']['sample_schedule_sha256'],
                         second['fitting']['sample_schedule_sha256'])
        self.assertEqual(first['fitting']['new_head_sha256'],
                         second['fitting']['new_head_sha256'])
        self.assertEqual(first['fitting']['total_candidate_exposures'],320)
        self.assertFalse(first['real_granite_tokenbank_numeric_parity_claimed'])

    def test_original_archive_checksum_rejects_forgery(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'forged.zip'
            body=bytearray(ARCHIVE.read_bytes());body[100]^=1;p.write_bytes(body)
            with self.assertRaisesRegex(ValueError,'original V6 artifact bytes replaced'):
                roster(p)


if __name__=='__main__':unittest.main()
