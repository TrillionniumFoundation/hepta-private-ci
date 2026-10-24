"""Budget selection must depend on measured cost, not solution labels."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_cpu_exchange import (
    BASE_BUDGETS,
    CANDIDATES,
    calibrate,
    cohorts,
    evaluate,
    one,
    run,
)
from system2_verified_search import verify


class CostExchangeTests(unittest.TestCase):
    def test_predeclared_nonoverlapping_ids(self):
        old, fresh = cohorts()
        self.assertEqual((len(old), len(fresh)), (204, 48))
        self.assertFalse(set(old) & set(fresh))
        self.assertTrue(all(CANDIDATES[b][0] == b for b in BASE_BUDGETS))

    def test_independent_proofs_from_both_named_policies(self):
        for n in ((1, 3, 4, 6), (2, 3, 4, 5), (4, 4, 4, 4)):
            for budget in BASE_BUDGETS:
                a = one(n, budget, "reference")
                b = one(n, budget, "prefilter")
                self.assertEqual(a["found"], b["found"])
                self.assertEqual(a["proof"], b["proof"])
                self.assertEqual(
                    a["work"]["generated_successors"], b["work"]["generated_successors"]
                )
                if b["found"]:
                    self.assertTrue(verify(n, 24, b["proof"]))

    def test_unregistered_budgets_rejected(self):
        for limit, profile in (
            (-1, "reference"),
            (0, "reference"),
            (200, "unknown"),
            (False, "reference"),
            (3, "prefilter"),
        ):
            with self.assertRaises(ValueError):
                one((1, 2, 3, 4), limit, profile)

    def test_calibration_uses_cost_not_labels(self):
        tasks = ((1, 2, 3, 4), (1, 1, 1, 1))

        def fake(label):
            def call(_n, cap, profile):
                amount = 100 * cap if profile == "reference" else 40 * cap
                return {
                    "cpu_ns": amount,
                    "found": label,
                    "work": {"generated_successors": cap},
                }

            return call

        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            a.mkdir()
            b.mkdir()
            with patch("system2_cpu_exchange.one", side_effect=fake(False)):
                left = calibrate(tasks, a)
            with patch("system2_cpu_exchange.one", side_effect=fake(True)):
                right = calibrate(tasks, b)
            self.assertEqual(left, right)
            self.assertEqual(
                {k: v["successor_limit"] for k, v in left.items()},
                {"256": 512, "512": 1024, "1024": 2048},
            )

    def test_freeze_before_evaluation_and_pair_census(self):
        tasks = ((1, 2, 3, 4), (1, 1, 1, 1))
        frozen = {str(b): {"successor_limit": 2 * b} for b in BASE_BUDGETS}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows, contrasts, seal = evaluate(tasks, frozen, root)
            self.assertEqual(len(rows), 2 * 3 * 2 * 5)
            self.assertEqual(len(contrasts), 3)
            data = (root / "evaluation.jsonl").read_bytes()
            self.assertEqual(seal, hashlib.sha256(data).hexdigest())
            self.assertEqual(
                json.loads((root / "evaluation-seal.json").read_text())["rows"],
                len(rows),
            )
            self.assertTrue(
                all(not x["losses"] for item in contrasts for x in item["rounds"])
            )

    def test_failures_are_recorded_in_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            with patch(
                "system2_cpu_exchange.one", side_effect=RuntimeError("injected")
            ):
                with self.assertRaises(RuntimeError):
                    calibrate(((1, 2, 3, 4),), root)
            self.assertEqual(
                len((root / "calibration-starts.jsonl").read_text().splitlines()), 1
            )
            failure = json.loads((root / "calibration.jsonl").read_text())
            self.assertEqual(failure["status"], "failed")
            self.assertTrue(failure["unknown_cost"])

    def test_incomplete_evaluation_does_not_fake_success(self):
        tasks = ((1, 2, 3, 4),)
        frozen = {str(b): {"successor_limit": 2 * b} for b in BASE_BUDGETS}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "system2_cpu_exchange.one", side_effect=RuntimeError("injected")
            ):
                with self.assertRaises(RuntimeError):
                    evaluate(tasks, frozen, root)
            result = json.loads((root / "evaluation.jsonl").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["unknown_cost"])
            self.assertFalse((root / "evaluation-seal.json").exists())

    def test_complete_runner_freezes_calibration_before_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "study"
            train = ((1, 1, 1, 1),)
            evals = ((1, 2, 3, 4),)

            # Intercepting the first evaluation attempt proves the entire
            # calibration decision file already exists on disk.
            def guarded(n, cap, profile):
                if n == evals[0] and not (output / "calibration-choice.json").is_file():
                    raise AssertionError("evaluation preceded frozen selection")
                generated = min(cap, 10)
                return dict(
                    cpu_ns=(100 * cap if profile == "reference" else 40 * cap),
                    wall_ns=100 * cap,
                    found=False,
                    proof=None,
                    work={"generated_successors": generated},
                    verification_skips=0,
                )

            with (
                patch("system2_cpu_exchange.cohorts", return_value=(train, evals)),
                patch("system2_cpu_exchange.one", side_effect=guarded),
            ):
                receipt = run(output, source_commit="a" * 40)
            self.assertEqual((receipt["recorded"], receipt["failed"]), (30, 0))
            self.assertEqual(receipt["calibration_planned"], 54)
            self.assertFalse(receipt["production_accepted"])
            self.assertTrue((output / "evaluation-seal.json").is_file())
            self.assertEqual(
                len((output / "evaluation.jsonl").read_text().splitlines()), 30
            )

    def test_failed_runner_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "study"
            with (
                patch(
                    "system2_cpu_exchange.cohorts",
                    return_value=(((1, 1, 1, 1),), ((1, 2, 3, 4),)),
                ),
                patch("system2_cpu_exchange.one", side_effect=RuntimeError("injected")),
            ):
                with self.assertRaises(RuntimeError):
                    run(output, source_commit="a" * 40)
            self.assertTrue((output / "run-failure.json").is_file())
            self.assertFalse((output / "summary.json").is_file())

    def test_exact_identity_precondition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            with self.assertRaises(ValueError):
                run(root, source_commit="not-a-commit")
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
