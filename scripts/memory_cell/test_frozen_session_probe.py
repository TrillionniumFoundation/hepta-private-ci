"""Execution-order integration with a deliberately non-pretrained reader."""

from pathlib import Path
import tempfile
import unittest

from frozen_session_probe import probe
from test_frozen_memory_session import Reader


class FrozenProbeTests(unittest.TestCase):
    def test_probe_uses_model_for_all_conditions_and_replay_never_regenerates(self):
        reader = Reader()
        with tempfile.TemporaryDirectory() as root:
            result = probe(reader, Path(root) / "output", source_commit="a" * 40)
        self.assertEqual(reader.calls, 4)
        self.assertEqual(result["model_calls"], 4)
        self.assertEqual(
            [
                len(r["result"]["record"]["receipt"]["delivered_evidence"])
                for r in result["results"]
            ],
            [1, 2, 1, 2],
        )
        self.assertTrue(all(r["withheld_replay_rejected"] for r in result["results"]))
        self.assertFalse(result["production_accepted"])
        self.assertEqual(result["prospective_windows"], 0)
        self.assertEqual(result["independent_snapshots"], 0)


if __name__ == "__main__":
    unittest.main()
