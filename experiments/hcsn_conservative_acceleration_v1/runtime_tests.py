"""Fresh-interpreter checkpoint verification for both numerical backends.

Actual pinned-native execution is a separate mandatory runtime command when its
binary is provided; these tests do not replace it with a Python simulation.
"""

from pathlib import Path
import tempfile
import unittest

import torch

from .runtime import _check_manifest, stream_check


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_both_backends_restore_complete_probability_state(self):
        config = dict(name="distribution_free_dual", input_dim=4, output_dim=3,
                      width=8, depth=2, seed=71)
        with tempfile.TemporaryDirectory(prefix="hcsn-runtime-test-") as temporary:
            for backend in ("reference", "accelerated"):
                path = Path(temporary) / backend
                result = stream_check(path, backend, config=config, length=24, cut=7)
                self.assertTrue(result["suffix_logits_bitwise_equal"])
                self.assertTrue(result["suffix_state_bitwise_equal"])
                self.assertTrue(all(mass>0 for mass in result["midpoint_refractory_mass"]))
                # Byte corruption must be rejected before any deserialization.
                checkpoint = path / "mid_state.npz"
                data = checkpoint.read_bytes()
                checkpoint.write_bytes(data[:-1]+bytes([data[-1]^1]))
                with self.assertRaisesRegex(ValueError, "Resume input changed"):
                    _check_manifest(path)


if __name__ == "__main__":
    unittest.main()
