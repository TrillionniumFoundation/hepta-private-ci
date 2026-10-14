"""Actual stock Transformers architecture, trained synthetic conditional Reader.

Requires the separate installed-HF CI profile; never counted in source suite.
"""
import tempfile
import unittest
from pathlib import Path

from hf_profile_checks import InstalledHFTests
from public_conditional_quality_probe import execute,score


class GenuineStockConditionalQualityTest(unittest.TestCase):
    def setUp(self):
        fixture=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        fixture.setUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.model_snapshot=fixture.root

    def test_actual_stock_encoder_trains_and_scores_four_reader_controls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            marker=execute(self.model_snapshot,root/'run',seed=7347,
                           train_groups=2,eval_groups=1,steps=8)
            result=score(root/'run',expected_seal_id=marker['seal_id'],output=root/'scores')
            self.assertEqual(len(result['results']),4)
            self.assertEqual(result['results']['conditioned']['total'],8)
            self.assertFalse(result['real_world_qa_established'])
            self.assertFalse(result['statistical_superiority_established'])


if __name__=='__main__':
    unittest.main()
