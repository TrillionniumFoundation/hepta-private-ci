"""Observed pretrained split mechanics; NEVER interpret as a real-world gain."""
import os
from pathlib import Path
import tempfile
import unittest

from associative_minilm_split_trial import run
from associative_minilm_offline import REGISTERED_ENCODER_IDENTITY

ENCODER = os.environ.get("HEPTA_ASSOC_ENCODER_DIR")


class AdmissionTests(unittest.TestCase):
    def test_bad_budget_rejected_before_model_read_or_output_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"new"
            with self.assertRaisesRegex(ValueError,"bounded matched-split"):
                run("missing",p,rank=3)
            self.assertFalse(p.exists())

    @unittest.skipUnless(ENCODER and Path(ENCODER).is_dir(),
                         "original staged MiniLM weights unavailable")
    def test_actual_weights_and_equal_parameter_split(self):
        with tempfile.TemporaryDirectory() as d:
            report=run(ENCODER,Path(d)/"split",pre_steps=24,post_steps=24,dimension=24)
            self.assertEqual(report["schema"],"hepta.associative-minilm-type-split-lesion.v1")
            self.assertEqual(report["encoder_identity"],REGISTERED_ENCODER_IDENTITY)
            self.assertEqual(report["parameters"]["shared"],report["parameters"]["split_total"])
            self.assertEqual(report["budget"]["estimated_shared_post_parameter_touches"],
                             report["budget"]["estimated_split_post_parameter_touches"])
            self.assertEqual(report["budget"]["shared_post_updates"],24)
            self.assertEqual(report["budget"]["split_post_updates"],48)
            self.assertEqual(len(report["cases"]),6)
            self.assertTrue(report["parent_unchanged"])
            self.assertTrue(report["revoked_ancestor_blocks_both_children"])
            self.assertTrue(report["source_root_inheritance_preserved"])
            self.assertFalse(report["superiority_claim"])
            self.assertFalse(report["production_qualified"])
            self.assertFalse(report["strong_indexed_rag_executed"])
            self.assertFalse(report["transformers_reference_parity_verified"])
            self.assertEqual(report["source_family_count_effective"],1)
            self.assertEqual(set(report["mean_latent_mse"]),{
                "split_correct", "split_swapped", "shared_continued",
                "parent_before_continuation", "cached_source_vector_nn",
            })
            self.assertTrue((Path(d)/"split"/"split-report.json").is_file())


if __name__ == "__main__":
    unittest.main()
