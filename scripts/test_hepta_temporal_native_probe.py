"""Keep actual training and build failures visible in the interface probe."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED
from hepta_cells.component_types import digest
from hepta_cells.temporal import TemporalKernel, TrainingAttemptError
from hepta_cells.temporal_native_probe import _variant, run


class NativeProbeAccountingTests(unittest.TestCase):
    def test_source_freeze_failure_retains_plan_and_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "probe"
            with patch(
                "hepta_cells.temporal_native_probe.freeze",
                side_effect=ValueError("source changed"),
            ):
                with self.assertRaisesRegex(ValueError, "source changed"):
                    run(Path(temp), output)
            failure = json.loads((output / "FAILURE.json").read_text())
            self.assertEqual(failure["rows"], [])
            self.assertIsNone(failure["research_result"])
            self.assertGreater(failure["wall_ns"], 0)
            self.assertTrue((output / "PLAN.json").is_file())

    def test_second_training_failure_preserves_first_measured_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            family = root / "common"
            (family / "native").mkdir(parents=True)
            (family / "inputs.json").write_text("{}")
            parts = {
                name: digest(["disclosed-accounting-fixture", name])
                for name in REQUIRED
            }
            parts.update({name: None for name in OPTIONAL})
            common = {
                "models": {
                    name: {"bundle": Bundle(name, 1, parts).record()}
                    for name in ("MEM", "PRED")
                }
            }
            train = TemporalKernel.train_candidate

            def fail_second(kernel, episodes, actions, allowed, **kwargs):
                if kernel.cell_id == "PRED":
                    allowed = allowed[:, :1]
                return train(kernel, episodes, actions, allowed, **kwargs)

            output = root / "gru"
            with patch.object(TemporalKernel, "train_candidate", new=fail_second):
                with self.assertRaises(TrainingAttemptError):
                    _variant(common, family, output, "gru")
            first = json.loads((output / "MEM-TRAINING_RECEIPT.json").read_text())
            failed = json.loads((output / "PRED-TRAINING_FAILURE.json").read_text())[
                "receipt"
            ]
            self.assertEqual(first["validated_updates"], 8)
            self.assertEqual(failed["status"], "failed")
            self.assertGreater(failed["wall_seconds"], 0)
            self.assertEqual(failed["validated_updates"], 0)
            self.assertTrue((output / "MEM.npz").is_file())
            self.assertFalse((output / "candidate.json").exists())


if __name__ == "__main__":
    unittest.main()
