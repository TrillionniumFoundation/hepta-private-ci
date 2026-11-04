"""V34 synthetic fault tests; no pretrained originality/utility claim from tests."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from safetensors.numpy import save as save_numpy

import v34_old_only_learning as p
import v34_independent_numpy_review as n


def synthetic_capsules(root: Path):
    # These are deliberate mock identities, NEVER real original mmBERT features.
    rng=np.random.default_rng(20261017)
    ids=[f'{i+1:064x}' for i in range(32)]
    members=[]
    for fid in range(4):
        select=[i for i in range(32) if i%4!=fid]
        rows=[{'case_id':ids[i], 'group':f'{100+i:064x}', 'cell':0,
               'split':'train','label':i%4} for i in select]
        raw=save_numpy({'features':rng.normal(size=(24,384)).astype('<f4')})
        doc={'schema':p.SCHEMA+'.old-source','fold':fid,
             'original_source_sha256':p.base.STAGED_SOURCE_SHA,
             'original_feature_sha256':p.base.STAGED_TRAIN_FEATURE_SHA,
             'train_count':24,'feature_width':384,'source_cell':0,
             'original_cell1_count_visible_to_model':0,
             'original_held_count_visible_to_model':0,
             'features_sha256':p.base.sha(raw),'old_rows':rows,
             'future_windows':0,'production_authorized':False}
        a,b=p.capsule_paths(root,fid)
        a.write_bytes(raw);b.write_bytes(p.base.canonical(doc))
        members.append({'fold':fid,'features_sha256':p.base.sha(raw),
                        'metadata_sha256':p.base.sha(b.read_bytes())})
    (root/'capsule-index.json').write_bytes(p.base.canonical({
        'schema':p.SCHEMA+'.capsule-index',
        'source_sha256':p.base.STAGED_SOURCE_SHA,'folds':members,
        'model_visible_new_cell_features':False,
        'model_visible_hold_features':False,'production_authorized':False}))


class OldOnlyContracts(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root=Path(self.work.name)
        self.capsules=self.root/'capsules';self.capsules.mkdir()
        synthetic_capsules(self.capsules)

    def modify(self,func,filename='old-fold-0.json'):
        path=self.capsules/filename
        data=json.loads(path.read_bytes());func(data)
        path.write_bytes(p.base.canonical(data))
        with self.assertRaises((ValueError,KeyError,TypeError)):
            p.load_capsules(self.capsules)

    def test_only_24_cell0_features_enter_stage1(self):
        groups=p.load_capsules(self.capsules)
        self.assertEqual(len(groups),4)
        self.assertEqual(sum(a[1].shape[0] for a in groups),96)
        self.assertTrue(all(len(a[0]['old_rows'])==24 for a in groups))
        self.assertTrue(all(a[2].shape==(384,) for a in groups))

    def test_strict_old_only_scaler_rejects_new_batch(self):
        ok=p.load_capsules(self.capsules)[0][1]
        _,_,digest=p.old_scaler(ok)
        self.assertEqual(len(digest),64)
        for bad in (np.ones((48,384),dtype='<f4'),ok.astype('<f8'),
                    np.full((24,384),np.nan,dtype='<f4')):
            with self.subTest(shape=bad.shape),self.assertRaises(ValueError):p.old_scaler(bad)

    def test_new_unlabeled_features_cannot_change_old_scaler(self):
        old=p.load_capsules(self.capsules)[0][1]
        future=np.random.default_rng(12).normal(size=(24,384)).astype('<f4')
        self.assertEqual(p.old_scaler(old)[2],p.old_scaler(old.copy())[2])
        self.assertNotEqual(p.old_scaler(old)[2],p.old_scaler(future)[2])

    def test_extra_new_cell_feature_file_denied(self):
        (self.capsules/'cell1-hidden.safetensors').write_bytes(b'fake')
        with self.assertRaisesRegex(ValueError,'extra original-feature'):
            p.load_capsules(self.capsules)

    def test_new_cell_label_record_denied(self):
        self.modify(lambda z:z['old_rows'][0].update(cell=1))

    def test_new_cell_unlabeled_counter_in_metadata_denied(self):
        self.modify(lambda z:z.update(original_cell1_count_visible_to_model=24))

    def test_stage1_held_feature_visibility_denied(self):
        self.modify(lambda z:z.update(original_held_count_visible_to_model=8))

    def test_wrong_old_source_identity_denied(self):
        self.modify(lambda z:z.update(original_source_sha256='f'*64))

    def test_false_future_or_grant_denied(self):
        self.modify(lambda z:z.update(future_windows=2))
        self.modify(lambda z:z.update(production_authorized=True))

    def test_extra_capsule_index_field_denied(self):
        self.modify(lambda z:z.update(model_visible_new_cell_features=True), 'capsule-index.json')

    def test_capsule_sha_tamper_denied(self):
        path=self.capsules/'old-fold-0.safetensors'
        payload=bytearray(path.read_bytes());payload[-1]^=1;path.write_bytes(payload)
        with self.assertRaises(ValueError):p.load_capsules(self.capsules)

    def test_symlink_supplement_denied(self):
        (self.capsules/'extra').symlink_to(self.capsules/'capsule-index.json')
        with self.assertRaises(ValueError):p.load_capsules(self.capsules)

    def test_old_only_genuine_torch_optimizer_synthetic(self):
        output=self.root/'stage1-checkpoints.json'
        obs=p.fit_old_only(self.capsules,output)
        self.assertEqual(obs['total_old_only_updates'],480)
        self.assertEqual(len(obs['records']),12)
        self.assertTrue(all(r['new_cell_feature_rows_seen']==0 for r in obs['records']))
        self.assertFalse(obs['production_authorized'])
        self.assertEqual(output.stat().st_mode & 0o777,0o600)
        with self.assertRaises(ValueError):p.fit_old_only(self.capsules,output)

    def test_reviewer_does_not_import_producer_or_torch(self):
        raw=Path(n.__file__).read_text()
        self.assertNotIn('import torch',raw)
        self.assertNotIn('import v34_old_only_learning',raw)
        self.assertEqual(p.SCHEMA,n.SCHEMA)
        self.assertEqual(p.STEPS,40)

    def test_workflow_old_source_deleted_before_physical_old_fit(self):
        flow=Path(__file__).resolve().parents[2]/'.github/workflows/hepta-stem-v34-old-cell-isolated.yml'
        raw=flow.read_text()
        self.assertIn('v34_old_only_learning.py project-old',raw)
        self.assertIn('v34_old_only_learning.py train-old',raw)
        self.assertIn('v34_old_only_learning.py adapt',raw)
        self.assertIn('v34_independent_numpy_review.py',raw)
        self.assertIn('11890616195',raw)
        self.assertIn(p.base.ARCHIVE_SHA,raw)
        self.assertIn('rm -rf "$RUNNER_TEMP/v34-original-train"',raw)
        self.assertIn('test ! -e "$RUNNER_TEMP/v34-original-train"',raw)
        self.assertIn('rm -f "$RUNNER_TEMP/v34-original-mmbert.zip"',raw)
        self.assertLess(raw.index('rm -rf "$RUNNER_TEMP/v34-original-train"'),
                        raw.index('v34_old_only_learning.py train-old'))
        self.assertLess(raw.index('v34_old_only_learning.py train-old'),
                        raw.index('v34_old_only_learning.py adapt'))
        self.assertIn('github.event_name == \'push\'',raw)
        self.assertNotIn('|| true',raw)

if __name__=='__main__':unittest.main()
