"""Fail-closed evidence checks and actual SQLite termination regression tests."""

import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

import diagnose
import run


class PrematureStop:
    hidden = 12

    def choose(self, feature, state):
        return 2, state


class DiagnosticTests(unittest.TestCase):
    def test_readable_incomplete_stop_repairs_with_real_sqlite(self):
        task = next(
            task for task in run.tasks("confirm") if task["fault"] == "lost_reply"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, _ = run.episode(
                task, "B4_gru", PrematureStop(), root / "original", False
            )
            guarded = diagnose.guarded_episode(
                run, task, "B4_gru", PrematureStop(), root / "guarded"
            )
            reference = diagnose.guarded_episode(
                run, task, "B1_macro", None, root / "reference"
            )
        self.assertFalse(original["complete"])
        self.assertEqual(
            [
                guarded[k]
                for k in (
                    "complete",
                    "claimed_success",
                    "duplicate_effects",
                    "primitive_calls",
                )
            ],
            [
                reference[k]
                for k in (
                    "complete",
                    "claimed_success",
                    "duplicate_effects",
                    "primitive_calls",
                )
            ],
        )
        self.assertTrue(guarded["complete"] and guarded["guard_overrides"] > 0)
        self.assertEqual(reference["guard_overrides"], 0)

    def test_unreadable_effect_still_cannot_claim_success(self):
        task = next(
            task
            for task in run.tasks("confirm")
            if task["fault"] == "opaque_after_apply"
        )
        with tempfile.TemporaryDirectory() as folder:
            row = diagnose.guarded_episode(
                run, task, "B4_gru", PrematureStop(), Path(folder) / "trial"
            )
        self.assertFalse(row["complete"] or row["claimed_success"])
        self.assertEqual(row["duplicate_effects"], 0)
        self.assertLess(row["primitive_calls"], 6 * len(task["goals"]) + 6)

    def test_partial_duplicate_or_relabeled_panels_rejected(self):
        tasks = [{"id": "a"}, {"id": "b"}]
        rows = [
            {"training_seed": 1, "arm": "gru", "task_id": task["id"]} for task in tasks
        ]
        self.assertEqual(len(diagnose.index_panel(rows, tasks, [1], ["gru"])), 2)
        for malformed in (
            rows[:1],
            rows + rows[:1],
            [rows[0], rows[1] | {"training_seed": 2}],
        ):
            with self.assertRaisesRegex(ValueError, "panel"):
                diagnose.index_panel(malformed, tasks, [1], ["gru"])

    def test_digest_and_replay_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "artifact"
            path.write_bytes(b"original")
            digest = hashlib.sha256(b"original").hexdigest()
            self.assertEqual(diagnose.checked_bytes(path, digest), b"original")
            path.write_bytes(b"altered")
            with self.assertRaisesRegex(ValueError, "digest"):
                diagnose.checked_bytes(path, digest)
            with self.assertRaises(FileNotFoundError):
                diagnose.checked_bytes(path.parent / "absent", digest)
        row = dict.fromkeys(diagnose.MATCH, 0)
        with self.assertRaisesRegex(ValueError, "replay"):
            diagnose.verify_replay(row | {"primitive_calls": 1}, row)

    def test_nonfinite_policy_input_rejected(self):
        with self.assertRaisesRegex(ValueError, "feature"):
            diagnose.guard_stop("stop", [np.nan] * 10)


if __name__ == "__main__":
    unittest.main()
