"""Only synthetic control-gate tests; never proof of pretrained model execution."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import public_e0_shadow as e0
from stem_projection import LowRankProjectionQ24, Q
import native_bridge


class E0ShadowContractTests(unittest.TestCase):
    def test_width_and_final_coordinate_survive_existing_projection(self):
        proj = e0.make_diagnostic_projection(
            LowRankProjectionQ24, encoder="a" * 64,
            preprocessor="b" * 64, runtime="c" * 64, normalizer="d" * 64)
        self.assertEqual((proj.input_width, proj.output_width, proj.rank), (768, 256, 2))
        base = proj.project_float32((0.0,) * 768)
        changed = proj.project_float32((0.0,) * 767 + (0.25,))
        self.assertEqual(len(changed), 256)
        self.assertNotEqual(base[1], changed[1])
        self.assertGreater(len(proj.digest), 0)
        self.assertTrue(all(isinstance(x, int) and -8 * Q <= x <= 8 * Q for x in changed))

    def test_diagnostic_q24_readout_is_real_integer_math_not_lm(self):
        proj = e0.make_diagnostic_projection(
            LowRankProjectionQ24, encoder="a" * 64,
            preprocessor="b" * 64, runtime="c" * 64, normalizer="d" * 64)
        actual = proj.project_float32((0.25,)*768)
        self.assertEqual(e0.control_readout(native_bridge, actual),
                         [actual[0] / Q, actual[1] / Q])
        with self.assertRaisesRegex(ValueError, "wrong real HF feature width"):
            e0.feature_hash([0.0] * 512)

    def test_feature_byte_digest_is_sensitive_to_last_coordinate(self):
        one = [0.0] * 768
        two = one.copy()
        two[-1] = 0.25
        self.assertNotEqual(e0.feature_hash(one), e0.feature_hash(two))
        self.assertEqual(e0.feature_hash(one), e0.feature_hash(one))

    def test_fake_checkout_rejected_before_any_network_or_model_loading(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test",
                            "-c", "user.email=test@example.org", "commit",
                            "--allow-empty", "-qm", "fixture"], check=True)
            with self.assertRaisesRegex(ValueError, "source checkout SHA/tree mismatch"):
                e0.source_checkout(root, e0.HF_SOURCE_COMMIT, e0.HF_SOURCE_TREE)

    def test_existing_directory_is_not_eligible_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "attempt"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                e0.run(hf_checkout=root, projection_checkout=root, output=output)


if __name__ == "__main__":
    unittest.main()
