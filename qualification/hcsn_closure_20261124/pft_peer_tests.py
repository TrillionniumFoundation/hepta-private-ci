"""Integration tests for real ring communication and immutable cold reload."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from .pft_peer import canonical, envelope, run_ring, validate


class RingTests(unittest.TestCase):
    def test_independent_peers_and_cold_restart_match_known_objective(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shards, xs, ys = [], [], []
            rng = np.random.default_rng(817)
            for index, rows in enumerate((3, 7, 11)):
                x = rng.normal(size=(rows, 5)) + index
                y = rng.normal(size=(rows, 2))
                path = root / f"shard{index}.npz"
                np.savez_compressed(path, x=x, y=y)
                shards.append(path)
                xs.append(x)
                ys.append(y)
            x, y = np.vstack(xs), np.vstack(ys)
            expected = np.linalg.solve(x.T @ x + 0.2 * np.eye(5), x.T @ y)
            receipt = run_ring(shards, {"purpose": "integration-only"}, root / "ring")
            self.assertEqual(receipt["exits"], [0, 0, 0])
            self.assertEqual(len(set(receipt["peer_pids"])), 3)
            for index in range(3):
                with np.load(root / "ring" / f"peer{index}" / "candidate.npz") as z:
                    np.testing.assert_allclose(
                        z["weight"], expected, atol=1e-12, rtol=1e-12
                    )
            observations = root / "observations.npz"
            np.savez_compressed(observations, x=x)
            candidate = root / "ring" / "peer0" / "candidate.npz"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qualification.hcsn_closure_20261124.pft_peer",
                    "replay",
                    "--candidate",
                    str(candidate),
                    "--observations",
                    str(observations),
                    "--output",
                    str(root / "cold.json"),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            cold = json.loads((root / "cold.json").read_text())
            self.assertNotIn(cold["pid"], receipt["peer_pids"])
            np.testing.assert_allclose(cold["predictions"], x @ expected, atol=1e-12)
            self.assertEqual(cold["optimizer_steps"], 0)

    def test_stale_and_wrong_origin_packets_are_rejected(self):
        packet = envelope(0, np.eye(2), np.ones((2, 1)), 4, "frozen-v1")
        for expected, binding in ((1, "frozen-v1"), (0, "changed-v2")):
            with self.assertRaises(ValueError):
                validate(packet, expected, binding, 2, 1)
        altered = json.loads(canonical(packet))
        altered["body"]["gram"][0][0] += 1
        with self.assertRaises(ValueError):
            validate(altered, 0, "frozen-v1", 2, 1)


if __name__ == "__main__":
    unittest.main()
