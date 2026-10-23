import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from independent import run
from independent.accounting import BudgetExceeded, WorkLedger


class FrozenRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.root = self.repo / "qualification/joint-generation"
        self.independent = self.root / "independent"
        self.independent.mkdir(parents=True)
        self.plan = self.independent / "plan.json"
        self.plan.write_text(json.dumps({"fixture": True}))
        (self.root / "model.py").write_text("BOUND = 1\n")
        for argv in (["git", "init", "-q"], ["git", "add", "."],
                     ["git", "-c", "user.name=Qualification fixture", "-c",
                      "user.email=fixture@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(argv, cwd=self.repo, check=True, capture_output=True)
        self.marker = self.independent / "efficient-r2-test-opened.json"
        for name, value in (("ROOT", self.root), ("PLAN", self.plan), ("MARKER", self.marker)):
            manager = patch.object(run, name, value)
            manager.start()
            self.addCleanup(manager.stop)

    def test_committed_protocol_freezes_then_source_changes_reject(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        value = run.check_freeze(receipt)
        self.assertFalse(value["test_opened"])
        self.assertEqual(value["sources"], {"model.py": run.sha(self.root / "model.py")})
        (self.root / "model.py").write_text("BOUND = 2\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            run.check_freeze(receipt)
        self.assertFalse(self.marker.exists())

    def test_uncommitted_protocol_is_not_accepted_as_frozen(self):
        self.plan.write_text(json.dumps({"fixture": False}))
        with self.assertRaisesRegex(ValueError, "commit all protocol"):
            run.freeze(self.independent / "uncommitted.json")
        self.assertFalse((self.independent / "uncommitted.json").exists())

    def test_experiment_opening_blocks_new_freeze_and_training_preflight(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        self.marker.write_text("{}")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.freeze(self.independent / "another-freeze.json")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.check_freeze(receipt)
        self.assertFalse((self.independent / "another-freeze.json").exists())

    def test_freeze_receipt_cannot_be_overwritten(self):
        receipt = self.independent / "frozen.json"
        run.freeze(receipt)
        before = receipt.read_bytes()
        with self.assertRaises(FileExistsError):
            run.freeze(receipt)
        self.assertEqual(receipt.read_bytes(), before)


class CandidateSchedulingTests(unittest.TestCase):
    def test_rotating_rounds_exclude_other_arms_cpu_and_preserve_returns(self):
        now, observed = [0.0], []

        def candidates(name, effort):
            active = run.ActiveCPU(lambda: now[0])
            for index in range(3):
                active.resume()
                now[0] += effort
                active.pause()
                observed.append((name, index))
                yield {"system": name, "round": index}
            return {"active_cpu": active.total, "name": name}

        tasks = {name: candidates(name, effort) for name, effort in (("S", 1), ("A", 2), ("N", 3))}
        retained = []
        completed = run.run_candidate_rounds(tasks, ("S", "A", "N"), 3,
            on_candidate=lambda system, index, row: retained.append(row))
        self.assertEqual(observed, [("S", 0), ("A", 0), ("N", 0),
            ("A", 1), ("N", 1), ("S", 1), ("N", 2), ("S", 2), ("A", 2)])
        self.assertEqual(completed, {"S": {"active_cpu": 3.0, "name": "S"},
            "A": {"active_cpu": 6.0, "name": "A"}, "N": {"active_cpu": 9.0, "name": "N"}})
        self.assertEqual(len(retained), 9)

    def test_generator_exception_flushes_active_cpu_without_charging_idle(self):
        now, progress = [0.0], {}

        def failing(*args, **kwargs):
            active = run.ActiveCPU(lambda: now[0])
            active.resume()
            progress.update(_activity=active, cost={})
            now[0] += 2
            active.pause()
            yield {"name": "first"}
            active.resume()
            now[0] += 3
            raise RuntimeError("kernel failed")

        with patch.object(run, "_train_system_candidates", failing):
            task = run.train_system("S", {}, None, None, {}, {}, {}, {"cpu_seconds": 1}, progress=progress)
            self.assertEqual(next(task), {"name": "first"})
            now[0] += 1000  # Other arm executes while this arm is yielded.
            with self.assertRaisesRegex(RuntimeError, "kernel failed"):
                next(task)
        self.assertEqual(progress["cost"], {"cpu_seconds": 6.0, "active_candidate_cpu_seconds": 5.0})
        self.assertIsNone(progress["_activity"].started)

    def test_over_cap_stops_before_candidate_work_and_keeps_partial_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            shared = WorkLedger("shared")
            shared.record("base_pretrain", units=7, content_updates=1)
            progress = {}
            task = run.train_system("S", {"operator_units_per_system": 100,
                "cpu_seconds_per_system": 10}, path, shared, {}, {}, {},
                {"cpu_seconds": 10.5}, progress=progress)
            with patch.object(run, "plain_copy", side_effect=AssertionError("no later computation")):
                with self.assertRaises(BudgetExceeded):
                    next(task)
            receipt = json.loads((path / "S-partial-arm.json").read_text())
            self.assertEqual(receipt["ledger"]["consumed_units"], 7)
            self.assertEqual(receipt["completed_candidates"], [])
            self.assertGreater(receipt["cost"]["cpu_seconds"], 10)
            self.assertEqual(receipt["phase"], "candidate_initialization")
            self.assertIsNone(progress["_activity"].started)

    def test_tail_failure_still_charges_actual_phase_and_keeps_original_error(self):
        now, cost, progress = [0.0], {"cpu_seconds": 4.0}, {}
        with patch.object(run, "cpu_clock", lambda: now[0]):
            with self.assertRaisesRegex(RuntimeError, "critic failed"):
                with run.active_tail_phase(cost, progress, "critic_fit", {"seed": 11}, "critic_cpu_seconds"):
                    now[0] += 2.5
                    raise RuntimeError("critic failed")
        self.assertEqual(cost, {"cpu_seconds": 6.5, "critic_cpu_seconds": 2.5})
        self.assertEqual(progress, {"phase": "critic_fit", "current": {"seed": 11}})

    def test_over_cap_archive_error_preserves_budget_failure(self):
        with patch.object(run, "write_json", side_effect=OSError("archive unavailable")):
            with self.assertRaisesRegex(BudgetExceeded, "actual CPU 11.000000000s") as caught:
                run.guard_cpu_budget("S", {"cpu_seconds_per_system": 10}, Path("/unused"),
                                     WorkLedger("S"), {"cpu_seconds": 11}, [], "candidate")
        self.assertIn("partial-arm persistence", caught.exception.__notes__[0])

    def test_failure_archiving_errors_preserve_the_original_kernel_error(self):
        original = RuntimeError("original kernel failure")
        plan = {"systems": ["S"], "model_seeds": [1], "learning_rates": [0.1],
                "cpu_seconds_per_system": 100}
        common = {"calibrations": {1: {"cpu_ns": {"full": 1}}}}
        frozen = {"plan": plan, "source_commit": "fixture"}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            with patch.object(run, "check_freeze", return_value=frozen), \
                    patch.object(run, "prepare_shared", return_value=(WorkLedger("shared"), {}, {}, {}, common)), \
                    patch.object(run, "run_candidate_rounds", side_effect=original), \
                    patch.object(run, "write_json", side_effect=OSError("archive unavailable")), \
                    patch.object(run, "sha", return_value="fixture"):
                with self.assertRaises(RuntimeError) as caught:
                    run.train(Path(directory) / "freeze.json", out)
        self.assertIs(caught.exception, original)
        self.assertEqual(len(original.__notes__), 3)
        self.assertTrue(any("partial-build" in note for note in original.__notes__))
        self.assertTrue(any("failure persistence" in note for note in original.__notes__))
        self.assertTrue(any("telemetry" in note for note in original.__notes__))

    def test_static_selected_validation_does_not_prepare_random_routing(self):
        row = {"system": "anchor", "model_file": "unused.npz", "seed": 1,
               "mode": "full", "reference_full_cpu_ns": 1}
        with patch.object(run.JointModel, "load", return_value=object()), \
                patch.object(run, "controller_for", return_value=None), \
                patch("independent.evaluation.measure", return_value={"static": True}), \
                patch.object(run, "charge_measure"), \
                patch.object(run, "FrozenGenerator", side_effect=AssertionError("unused random baseline")):
            measured = run.validate_selected([row], {}, {}, Path("/unused"), {"labels": ()}, None)
        self.assertEqual(measured, {1: {"static": True}})
        self.assertNotIn("random_full_probability", row)

    def test_early_or_extra_candidates_are_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, "stopped before"):
            run.run_candidate_rounds({"S": iter(())}, ("S",), 1)
        with self.assertRaisesRegex(ValueError, "exceeded"):
            run.run_candidate_rounds({"S": iter(({}, {}))}, ("S",), 1)


if __name__ == "__main__":
    unittest.main()
