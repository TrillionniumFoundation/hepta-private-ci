"""End-to-end executable fixtures; no result here is a real task benefit."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hepta_cells.bundle import Bundle
from hepta_cells.stem_contract import TimedTemporalComponent
from hepta_cells.stem_temporal_study import run
from test_hepta_stem_study_support import fixture


class StemTemporalStudyTests(unittest.TestCase):
    def execute(self, root, value, name):
        path = root / f"{name}.json"
        path.write_text(json.dumps(value))
        return run(path, root / name, widths=(2,), updates=2)

    def test_actual_fit_owner_next_use_and_cold_process_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.execute(root, fixture(), "fixture")
            self.assertEqual(result["failed_attempts"], [])
            self.assertEqual(
                set(result["arms"]),
                {
                    "constant-zero",
                    "train-prevalence",
                    "semantic-linear",
                    "gru-2",
                    "cfc-2",
                },
            )
            self.assertTrue(result["cold_recovery"]["matches_pre_restart"])
            self.assertNotEqual(result["cold_recovery"]["pid"], os.getpid())
            self.assertFalse(result["ordinary_daemon_complete_loop"])
            self.assertEqual(result["fresh_confirmation"], 0)
            selected = result["selection"]["selected_for_research_next_use"]
            self.assertEqual(result["arms"][selected]["C"]["source_groups"], 2)
            changed = fixture()
            for row in changed["records"]:
                if row["source_group"] in ("fixture-5", "fixture-6"):
                    row["target"] = 1 - row["target"]
            other = self.execute(root, changed, "changed-c-fixture")
            self.assertEqual(
                result["selection"]["B_scores"], other["selection"]["B_scores"]
            )
            self.assertEqual(
                selected, other["selection"]["selected_for_research_next_use"]
            )
            with self.assertRaises(FileExistsError):
                run(root / "fixture.json", root / "fixture", widths=(2,), updates=2)

    def test_completed_training_survives_checkpoint_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(
                TimedTemporalComponent,
                "checkpoint",
                side_effect=OSError("fixture disk failure"),
            ):
                result = self.execute(root, fixture(), "failed-save-fixture")
            self.assertEqual(
                {f["arm"] for f in result["failed_attempts"]}, {"gru-2", "cfc-2"}
            )
            for arm in ("gru-2", "cfc-2"):
                receipt = json.loads(
                    (root / "failed-save-fixture" / arm / "TRAINING.json").read_text()
                )
                self.assertEqual(receipt["validated_updates"], 2)
                self.assertEqual(receipt["status"], "completed_candidate_only")
            self.assertEqual(result["selection"]["promotion"], "NoUpdate")

    def test_successful_fit_receipts_precede_failed_bundle_construction(self):
        original = Bundle.successor

        def reject_temporal(bundle, artifact_id, *args):
            if artifact_id.startswith("retained-candidate-"):
                raise ValueError("injected post-fit binding failure")
            return original(bundle, artifact_id, *args)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(Bundle, "successor", new=reject_temporal):
                result = self.execute(root, fixture(), "failed-binding-fixture")
            self.assertEqual(
                {r["stage"] for r in result["failed_attempts"]}, {"binding"}
            )
            for arm in ("gru-2", "cfc-2"):
                path = root / "failed-binding-fixture" / arm
                self.assertTrue(
                    json.loads((path / "STARTED.json").read_text())[
                        "actual_cost_unknown_until_settled"
                    ]
                )
                receipt = json.loads((path / "TRAINING.json").read_text())
                self.assertEqual(
                    (receipt["status"], receipt["validated_updates"]),
                    ("completed_candidate_only", 2),
                )


if __name__ == "__main__":
    unittest.main()
