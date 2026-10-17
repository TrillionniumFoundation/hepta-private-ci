"""Fail-closed V33 fold-preprocessing research source tests; synthetic only."""
from __future__ import annotations
import unittest
import numpy as np
from pathlib import Path
import v33_fold_disjoint_training as v33
import v33_independent_numpy_review as audit

class FoldIsolation(unittest.TestCase):
    def setUp(self):
        self.x=np.random.default_rng(333).standard_normal((64,384)).astype('<f4')
        self.fit=list(range(48))
        self.held=list(range(48,64))

    def test_fit48_parity(self):
        a,h=v33.fold_normalize(self.x,self.fit,self.held)
        b,g=audit.pure_stats(self.x,self.fit,self.held)
        self.assertEqual(h,g)
        np.testing.assert_array_equal(a,b)

    def test_held_features_do_not_affect_fit_statistics(self):
        a,h=v33.fold_normalize(self.x,self.fit,self.held)
        shifted=self.x.copy()
        shifted[self.held]+=99
        b,g=v33.fold_normalize(shifted,self.fit,self.held)
        self.assertEqual(h,g)
        np.testing.assert_array_equal(a[self.fit],b[self.fit])
        self.assertFalse(np.array_equal(a[self.held],b[self.held]))

    def test_held_group_in_fit_denied(self):
        with self.assertRaises(ValueError):
            v33.fold_normalize(self.x,self.fit[:-1]+[48],self.held)
        with self.assertRaises(ValueError):
            v33.fold_normalize(self.x,self.fit,self.held[:-1]+[47])
        with self.assertRaises(ValueError):
            v33.fold_normalize(self.x,self.fit[:-1]+[0],self.held)

    def test_invalid_or_missing_material_denied(self):
        bad=self.x.copy()
        bad[4,4]=np.nan
        with self.assertRaises(ValueError):v33.fold_normalize(bad,self.fit,self.held)
        with self.assertRaises(ValueError):v33.fold_normalize(self.x.astype('float64'),self.fit,self.held)
        with self.assertRaises(ValueError):v33.original(Path('/definitely-missing-v33-original-stage'))

    def test_no_external_future_or_new_training_owner(self):
        self.assertEqual(v33.SEEDS,(41,47,53))
        self.assertEqual(v33.POLICY,audit.POLICY)
        self.assertEqual(v33.prior.STEPS,40)
        self.assertNotIn('import torch',Path(audit.__file__).read_text())

if __name__=='__main__':unittest.main()
