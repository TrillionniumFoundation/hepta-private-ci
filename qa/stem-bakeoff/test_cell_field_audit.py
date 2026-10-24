"""Independent audit regressions for byte identity and analytic score derivatives."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cell_field_audit import _probability_and_gradient, sha, verify_seal


class CellFieldAuditTests(unittest.TestCase):
    def test_seal_rejects_byte_change_and_unlisted_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = b"complete measured predictions\n"
            path = root / "prediction.bin"
            path.write_bytes(original)
            seal = {"files": {"prediction.bin": {"sha256": sha(original), "bytes": len(original)}},
                    "final_labels_opened": False}
            (root / "pre_evaluation_seal.json").write_text(json.dumps(seal))
            self.assertEqual(verify_seal(root), seal)
            path.write_bytes(original.replace(b"measured", b"altered!"))
            with self.assertRaisesRegex(ValueError, "changed"):
                verify_seal(root)
            path.write_bytes(original)
            (root / "unlisted.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "inventory"):
                verify_seal(root)

    def test_independent_probe_gradient_matches_finite_differences(self):
        rng = np.random.default_rng(1907)
        features = rng.normal(size=(12, 3))
        labels = np.repeat(np.arange(4), 3)
        for mode, size in (("linear", 16), ("gated", 22)):
            theta = rng.normal(scale=0.15, size=size)
            probability, loss, analytic = _probability_and_gradient(theta, mode, features, labels)
            self.assertTrue(np.isfinite(loss))
            np.testing.assert_allclose(probability.sum(axis=1), 1, atol=1e-14, rtol=0)
            numerical = []
            for i in range(size):
                plus, minus = theta.copy(), theta.copy()
                plus[i] += 1e-6
                minus[i] -= 1e-6
                numerical.append((_probability_and_gradient(plus, mode, features, labels)[1]
                                  - _probability_and_gradient(minus, mode, features, labels)[1]) / 2e-6)
            np.testing.assert_allclose(analytic, numerical, atol=4e-9, rtol=4e-8)


if __name__ == "__main__":
    unittest.main()
