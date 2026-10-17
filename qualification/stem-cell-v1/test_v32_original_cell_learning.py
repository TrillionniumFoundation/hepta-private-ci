"""Synthetic-only V32 mechanism/authority regression tests, NOT model efficacy."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from safetensors.numpy import save as save_numpy
import torch

import v32_original_cell_learning as m
import v32_independent_numpy_review as review


def sample():
    rng=np.random.default_rng(123)
    data=rng.normal(size=(64,384)).astype('<f4')
    rows=[{'case_id':f'ag-news:train:{i+1}', 'group':f'group:{i+1}',
           'cell':i%2,'split':'train','label':int(i%4)} for i in range(64)]
    blob=save_numpy({'features':data})
    meta={'schema':m.SCHEMA+'.train-only-source','archive_sha256':m.ARCHIVE_SHA,
          'original_producer_commit':m.ORIGINAL_PRODUCER,
          'original_full_feature_sha256':m.FEATURE_SHA,
          'original_v14_input_sha256':m.V14_INPUT_SHA,
          'original_data_sha256':m.DATA_SHA,
          'train_feature_sha256':m.sha(blob),'train_count':64,
          'train_cell_counts':[32,32],'rows':rows,
          'calibration_labels_exposed_to_trainer':False,
          'blind_labels_exposed_to_trainer':False,
          'independent_source_family_count':1,'independent_future_windows':0,
          'production_authorized':False}
    return meta,blob


class Contract(unittest.TestCase):
    def test_original_pretrained_source_is_immutable(self):
        self.assertEqual(m.ARCHIVE_SHA,review.ARCHIVE_SHA)
        self.assertEqual(m.FEATURE_SHA,review.FEATURE_SHA)
        self.assertEqual(m.V14_INPUT_SHA,review.V14_SHA)
        self.assertEqual(m.STAGED_SOURCE_SHA,review.STAGED_SOURCE_SHA)
        self.assertEqual(m.STAGED_TRAIN_FEATURE_SHA,review.STAGED_TRAIN_FEATURE_SHA)
        self.assertEqual((m.STEPS,m.FOLDS,m.WIDTH,m.BATCH),(40,4,384,16))

    def test_exact_fourfold_old_new_no_leak(self):
        rows,_=sample()
        # Fixture returns a typed meta that has exactly 32 in each source Cell.
        panels=m.split_folds(rows['rows'])
        self.assertEqual([len(x) for x in panels],[16]*4)
        self.assertEqual(sorted(sum(panels,[])),list(range(64)))
        self.assertTrue(all(sum(rows['rows'][i]['cell']==0 for i in group)==8 for group in panels))
        self.assertEqual(panels,review.folds(rows['rows']))

    def test_source_only_synthetic_data_cannot_masquerade_original(self):
        meta,blob=sample()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);m.write_only(p/'train-source.json',m.canonical(meta))
            m.write_only(p/'train-features.safetensors',blob)
            with self.assertRaises(ValueError):m.load_train(p)
            with self.assertRaises(ValueError):review.assess(p,p/'none',p/'none')

    def test_explicitly_patched_synthetic_source_tests_are_not_original_proof(self):
        meta,blob=sample()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);m.write_only(p/'train-source.json',m.canonical(meta))
            m.write_only(p/'train-features.safetensors',blob)
            with (patch.object(m,'STAGED_SOURCE_SHA',m.sha(m.canonical(meta))),
                  patch.object(m,'STAGED_TRAIN_FEATURE_SHA',m.sha(blob))):
                x,rows,_=m.load_train(p)
                self.assertEqual(x.shape,(64,384))
                self.assertTrue(np.isfinite(x).all())
                self.assertEqual(len(rows),64)

    def test_source_requires_no_forged_future_or_authority(self):
        meta,blob=sample()
        for key,invalid in [('independent_future_windows',1),('production_authorized',True),
                            ('blind_labels_exposed_to_trainer',True),
                            ('calibration_labels_exposed_to_trainer',True),
                            ('original_full_feature_sha256','0'*64)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as tmp:
                variant=deepcopy(meta);variant[key]=invalid
                p=Path(tmp);m.write_only(p/'train-source.json',m.canonical(variant))
                m.write_only(p/'train-features.safetensors',blob)
                with (patch.object(m,'STAGED_SOURCE_SHA',m.sha(m.canonical(variant))),
                      patch.object(m,'STAGED_TRAIN_FEATURE_SHA',m.sha(blob))):
                    with self.assertRaises(ValueError):m.load_train(p)

    def test_group_duplicate_and_label_bool_rejected(self):
        meta,blob=sample()
        for kind in ('duplicate','bool','split','cell'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                doc=deepcopy(meta)
                if kind=='duplicate':doc['rows'][1]['case_id']=doc['rows'][0]['case_id']
                elif kind=='bool':doc['rows'][1]['label']=True
                elif kind=='split':doc['rows'][1]['split']='holdout'
                else:doc['rows'][1]['cell']=3
                p=Path(tmp);m.write_only(p/'train-source.json',m.canonical(doc))
                m.write_only(p/'train-features.safetensors',blob)
                with (patch.object(m,'STAGED_SOURCE_SHA',m.sha(m.canonical(doc))),
                      patch.object(m,'STAGED_TRAIN_FEATURE_SHA',m.sha(blob))):
                    with self.assertRaises(ValueError):m.load_train(p)

    def test_actual_forty_sgd_steps_and_head_bytes(self):
        torch.set_num_threads(1)
        h=m.head()
        self.assertEqual(sum(x.numel() for x in h.parameters()),1540)
        x=torch.randn(24,384,generator=torch.Generator().manual_seed(20))
        y=torch.tensor([i%4 for i in range(24)])
        initial=h(x).detach().clone()
        spent=m.fit(h,x,y,seed=41,cell=0)
        self.assertEqual(spent['updates'],40)
        self.assertEqual(spent['source_examples_seen'],640)
        self.assertGreater(spent['optimizer_state_bytes_observed'],12320)
        self.assertFalse(torch.equal(initial,h(x).detach()))

    def test_split_and_blind_ensemble_share_exact_same_weights(self):
        old=m.head();new=deepcopy(old)
        with torch.no_grad():
            new.bias[:]=torch.tensor([0.,1.,2.,3.])
        x=torch.zeros(4,384)
        parts=m.forward_matrix((old,new,new,old),x,torch.tensor([0,1,0,1]))
        self.assertTrue(torch.equal(parts['nochange'],old(x)))
        self.assertTrue(torch.equal(parts['split'][0],old(x)[0]))
        self.assertTrue(torch.equal(parts['split'][1],new(x)[1]))
        self.assertTrue(torch.equal(parts['source_blind_ensemble'],(old(x)+new(x))/2))
        self.assertFalse(torch.equal(parts['split'],parts['source_blind_ensemble']))

    def test_untrusted_boolean_data_and_duplicate_keys(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):m.strict_json(raw)
            with self.subTest(raw=raw),self.assertRaises(ValueError):review.strict_json(raw)

    def test_create_only_file_and_symlink_veto(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'temp.json'
            m.write_only(path,b'{}')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):m.write_only(path,b'{"x":2}')
            link=root/'link.json';link.symlink_to(path)
            with self.assertRaises(ValueError):m.verified_file(link)
            with self.assertRaises(ValueError):m.write_only(link,b'{}')

    def test_workflow_requires_real_train_custody_and_no_promotion(self):
        path=Path(__file__).resolve().parents[2]/'.github/workflows/hepta-stem-v32-cell-learning.yml'
        flow=path.read_text()
        for word in (m.ARCHIVE_SHA,m.FEATURE_SHA,'11890616195','--archive','--source',
                     'training-material','unittest','python -O','DENY_ALL',
                     'Full original','never publish private','github.event_name == \'push\''):
            self.assertIn(word,flow)
        self.assertIn('rm -f "$RUNNER_TEMP/original-mmbert.zip"',flow)
        self.assertNotIn('trust_remote_code=True',flow)
        self.assertNotIn('|| true',flow)


if __name__=='__main__':unittest.main()
