"""Storage recovery is constrained by original commitments, not a new score."""

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from .recover import accept_checkpoint, _without_timers


class RecoveryTests(unittest.TestCase):
    def test_original_commitment_is_required_and_content_address_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.npz"
            source.write_bytes(b"frozen checkpoint bytes")
            digest = sha256(source.read_bytes()).hexdigest()
            target = accept_checkpoint(source, digest, root)
            self.assertEqual(target.name, digest + ".npz")
            self.assertEqual(accept_checkpoint(source, digest, root), target)
            source.write_bytes(b"different candidate with a better score")
            with self.assertRaisesRegex(ValueError, "original frozen SHA"):
                accept_checkpoint(source, digest, root)
            self.assertEqual(target.read_bytes(), b"frozen checkpoint bytes")
            source.write_bytes(b"frozen checkpoint bytes")
            target.write_bytes(b"damaged adopted content")
            with self.assertRaisesRegex(ValueError, "immutable checkpoint path"):
                accept_checkpoint(source, digest, root)

    def test_replay_excludes_measurement_timing_but_never_scientific_values(self):
        first = {
            "net_utility": 0.1,
            "mean_time": 7.0,
            "inference_wall_seconds": 1.0,
            "forecast_scores": {"joint_nll": 2.3},
        }
        later = {**first, "inference_wall_seconds": 5.0}
        self.assertEqual(_without_timers(first), _without_timers(later))
        later["mean_time"] = 8.0
        self.assertNotEqual(_without_timers(first), _without_timers(later))


if __name__ == "__main__":
    unittest.main()
