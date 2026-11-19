"""Meaningful inference and saved-prediction integrity regressions."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from .conditional_analysis import paired_statistics, validate_predictions


class ConditionalAnalysisTests(unittest.TestCase):
    def test_exact_signflip_includes_both_tails_and_zero_effect(self):
        same=paired_statistics(np.ones(8)*.01)
        self.assertEqual(same["exact_two_sided_sign_flip"]["p_value"],2/256)
        reverse=paired_statistics(-np.ones(8)*.01)
        self.assertEqual(same["exact_two_sided_sign_flip"],reverse["exact_two_sided_sign_flip"])
        self.assertAlmostEqual(reverse["mean"],-.01)
        null=paired_statistics([.01,-.01]*4)
        self.assertEqual(null["exact_two_sided_sign_flip"]["p_value"],1)
        self.assertLess(null["nominal_paired_t_95"]["lower"],0)
        self.assertGreater(null["nominal_paired_t_95"]["upper"],0)

    def test_eight_paired_seeds_are_required(self):
        for values in ([.1]*7,[.1]*9,[np.nan]*8):
            with self.assertRaises(ValueError):
                paired_statistics(values)

    def test_coordinate_reordering_is_valid_but_tampered_labels_or_duplicates_fail(self):
        expected=np.array([[-100,0],[-100,1]],dtype=np.int64)
        arrays=dict(logits=np.array([[0.,2.],[3.,0.]],np.float32),
                    predictions=np.array([1,0]),labels=np.array([1,0]),
                    supervised=expected!=-100,sample_indices=np.array([1,0]),step_indices=np.array([1,1]))
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"predictions.npz"
            np.savez_compressed(path,**arrays)
            metrics,aligned=validate_predictions(path,expected,2)
            self.assertEqual(metrics["accuracy"],1)
            np.testing.assert_array_equal(aligned["coordinates"],[1,3])
            arrays["labels"]=np.array([0,0])
            np.savez_compressed(path,**arrays)
            with self.assertRaises(ValueError):
                validate_predictions(path,expected,2)
            arrays["labels"]=np.array([1,0])
            arrays["sample_indices"]=np.array([1,1])
            np.savez_compressed(path,**arrays)
            with self.assertRaises(ValueError):
                validate_predictions(path,expected,2)


if __name__=="__main__":
    unittest.main(verbosity=2)
