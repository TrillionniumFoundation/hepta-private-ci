"""Required genuine miniature ModernBERT test; no pretrained-ability claim."""
import unittest
import torch
from hf_profile_checks import InstalledHFTests
from public_conditional_probe import run


class InstalledConditionalEvidenceTests(unittest.TestCase):
    def setUp(self):
        stock=InstalledHFTests(methodName='test_full_stock_architecture_roundtrip_and_physical_tie')
        stock.setUp()
        self.addCleanup(stock.tmp.cleanup)
        self.snapshot=stock.root

    def test_distinct_questions_share_actual_evidence_encoder_once(self):
        result=run(self.snapshot)
        self.assertEqual(result['questions'],3)
        self.assertEqual(result['evidence_encoder_forward_calls'],1)
        self.assertEqual(result['repeated_encoder_forward_calls'],3)
        self.assertEqual(result['original_max_logit_difference'],0.)
        self.assertIsInstance(result['ablation_max_logit_change'],float)
        self.assertFalse(result['reader_heads_trained'])
        self.assertFalse(result['real_world_evidence_sufficiency_established'])


if __name__=='__main__':
    torch.set_num_threads(1)
    unittest.main()
