"""Late worker failure does not erase an arm or its original receipt."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ndu_real_materials.common import binding, write_json
from .run_candidate_selection import recover_attempts
from . import run_candidate_selection as runner


class WorkerFailureTests(unittest.TestCase):
    def test_report_flag_uses_fixed_independent_generator(self):
        from types import SimpleNamespace

        def generate(*args):
            raise AssertionError("CLI must hand off, not score before collection")

        fake = SimpleNamespace(generate=generate)
        with (
            patch(
                "sys.argv",
                [
                    "selection",
                    "--request",
                    "request.json",
                    "--output",
                    "new-output",
                    "--independent-report",
                ],
            ),
            patch.dict(
                "sys.modules", {"ndu_real_runtime.candidate_selection_report": fake}
            ),
            patch.object(runner, "run", return_value={"status": "Completed"}) as called,
        ):
            runner.main()
        self.assertIs(called.call_args.kwargs["report_generator"], generate)

    def test_unresolved_cli_does_not_report_a_successful_experiment(self):
        with (
            patch(
                "sys.argv",
                [
                    "selection",
                    "--request",
                    "unread-request.json",
                    "--output",
                    "unused-output",
                ],
            ),
            patch.object(runner, "run", return_value={"status": "Unresolved"}),
        ):
            with self.assertRaises(SystemExit) as stopped:
                runner.main()
        self.assertEqual(stopped.exception.code, 1)

    def test_missing_or_unusable_terminal_status_preserves_unknown_roster(self):
        for status in (None, [], "InventedTerminal"):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                (root / "attempts").mkdir()
                path = root / "attempts/pair-frozen_neural.json"
                value = {"original_operation_id": "pair-frozen_neural"}
                if status is not None:
                    value["status"] = status
                write_json(path, value)
                rows = recover_attempts(
                    root,
                    [{"expected": {"original_operation_id": "pair-frozen_neural"}}],
                    RuntimeError("late worker error"),
                )
                self.assertEqual([r["status"] for r in rows], ["Unknown"])
                self.assertEqual(rows[0]["retained_attempt"], binding(path, root))
                self.assertEqual(
                    rows[0]["comparison_invariant_failure"], "retained_attempt"
                )

    def test_completed_arm_is_preserved_when_later_arm_has_no_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "attempts").mkdir()
            first = {
                "original_operation_id": "pair-frozen_neural",
                "status": "Completed",
                "wall_seconds": 0.25,
                "cpu_seconds": 0.1,
            }
            write_json(root / "attempts/pair-frozen_neural.json", first)
            pair = [
                {"expected": {"original_operation_id": "pair-" + mode}}
                for mode in ("frozen_neural", "public_rule")
            ]
            rows = recover_attempts(root, pair, RuntimeError("late worker death"))
            self.assertEqual(rows[0], first)
            self.assertEqual(rows[1]["status"], "Unknown")
            self.assertEqual(
                [r["original_operation_id"] for r in rows],
                [j["expected"]["original_operation_id"] for j in pair],
            )
            self.assertFalse((root / "attempts/pair-public_rule.json").exists())

    def test_corrupt_attempt_retains_bytes_and_unknown_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "attempts").mkdir()
            path = root / "attempts/pair-frozen_neural.json"
            path.write_bytes(b"{corrupted original receipt")
            original = path.read_bytes()
            rows = recover_attempts(
                root,
                [{"expected": {"original_operation_id": "pair-frozen_neural"}}],
                RuntimeError("worker died"),
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "Unknown")
            self.assertEqual(rows[0]["retained_attempt"], binding(path, root))
            self.assertEqual(
                rows[0]["comparison_invariant_failure"], "retained_attempt"
            )
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
