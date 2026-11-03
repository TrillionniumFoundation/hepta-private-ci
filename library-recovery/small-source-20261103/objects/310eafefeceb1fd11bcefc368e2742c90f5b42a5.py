"""Offline adversarial constraints for V33; never claim synthetic tensors are original."""
from __future__ import annotations

from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest
import numpy as np

import v32_original_cell_learning as old
import v33_fold_disjoint_training as study
import v33_independent_numpy_review as reviewer


class FoldOnly(unittest.TestCase):
    def setUp(self):
        self.raw=np.random.default_rng(20261017).standard_normal((64,384)).astype('<f4')
        self.fit=list(range(48));self.held=list(range(48,64))

    def test_strict_disjoint_training_fold(self):
        feature,digest=study.fold_normalize(self.raw,self.fit,self.held)
        self.assertEqual(feature.shape,(64,384))
        self.assertEqual(len(digest),64)
        self.assertEqual(digest,reviewer.pure_stats(self.raw,self.fit,self.held)[1])

    def test_held_group_change_cannot_retrain_preprocessor(self):
        a,sha_a=study.fold_normalize(self.raw,self.fit,self.held)
        altered=self.raw.copy();altered[self.held]*=103.0
        b,sha_b=study.fold_normalize(altered,self.fit,self.held)
        self.assertEqual(sha_a,sha_b)
        np.testing.assert_array_equal(a[self.fit],b[self.fit])
        self.assertFalse(np.array_equal(a[self.held],b[self.held]))

    def test_global_64_input_preprocessing_has_different_statistics(self):
        shifted=self.raw.copy();shifted[self.held]+=700
        _,fold=study.fold_normalize(shifted,self.fit,self.held)
        mean=shifted.mean(0).astype('<f4')
        std=np.maximum(shifted.std(0),np.float32(.1)).astype('<f4')
        self.assertNotEqual(fold,study.prior.sha(mean.tobytes()+std.tobytes()))

    def test_any_held_input_in_normalizer_rejected(self):
        cases=[(self.fit[:-1]+[48],self.held),
               (self.fit,self.held[:-1]+[47]),
               (self.fit[:-1],self.held),
               (self.fit,self.held+[42]),
               (self.fit[:-1]+[0],self.held),
               (self.fit,self.held[:-1]+[64])]
        for train,held in cases:
            with self.subTest(train=train[-3:],held=held[-3:]),self.assertRaises(ValueError):
                study.fold_normalize(self.raw,train,held)

    def test_boolean_and_nonfinite_raw_rejected(self):
        with self.assertRaises(ValueError):study.fold_normalize(self.raw.astype('<f8'),self.fit,self.held)
        raw=self.raw.copy();raw[2,1]=np.nan
        with self.assertRaises(ValueError):study.fold_normalize(raw,self.fit,self.held)

    def test_fold_producer_and_numpy_reviewer_separate(self):
        self.assertNotIn('import torch',Path(reviewer.__file__).read_text())
        self.assertNotIn('import v33_fold_disjoint_training',Path(reviewer.__file__).read_text())
        self.assertEqual(study.SEEDS,(41,47,53))
        self.assertEqual(study.prior.STEPS,40)
        self.assertEqual(study.POLICY,reviewer.POLICY)

    def test_outcome_gates_do_not_claim_future(self):
        self.assertEqual(study.SCHEMA,reviewer.SCHEMA)
        self.assertEqual(study.POLICY,'NORMALIZER_48_FIT_ONLY_NO_WITHHELD_FEATURES')

    def test_missing_original_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises((ValueError,FileNotFoundError)):old.stage(Path(t)/'not-original.zip',Path(t)/'stage')

    def test_reviewer_rejects_conflicting_snapshot(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t);(path/'train-source.json').write_bytes(b'{}')
            (path/'train-features.safetensors').write_bytes(b'fake')
            with self.assertRaises(ValueError):reviewer.review(path,path/'missing.json',path/'none.json')

    def test_workflow_source_and_original_are_separate(self):
        flow=(Path(__file__).resolve().parents[2]/'.github/workflows/hepta-stem-v33-fold-disjoint.yml').read_text()
        self.assertIn("github.event_name == 'push'",flow)
        self.assertIn('11890616195',flow)
        self.assertIn(old.ARCHIVE_SHA,flow)
        self.assertIn('v32_original_cell_learning.py stage',flow)
        self.assertIn('v33_fold_disjoint_training.py',flow)
        self.assertIn('v33_independent_numpy_review.py',flow)
        self.assertIn('DENY_ALL',flow)
        self.assertIn('git rev-parse HEAD',flow)
        self.assertNotIn('|| true',flow)
        self.assertLess(flow.index('sha256sum -c -'),flow.index('v32_original_cell_learning.py stage'))


if __name__=='__main__':unittest.main()
