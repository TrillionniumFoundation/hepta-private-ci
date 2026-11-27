"""Locked profile/preflight proofs using temporary repos and hand arrays only."""

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from independent import run
from independent.accounting import WorkLedger
from independent.experiments import bind_identity, resolve_experiment, validate_plan
from independent.inference import FrozenGenerator
from independent.learning import setup_work
from independent.refinement import add_work, observer_work, reserve_work, validation_work
from model import JointModel


class ExperimentIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-profile-unit-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.root = self.repo / "qualification/joint-generation"
        (self.root / "independent").mkdir(parents=True)
        (self.root / "core_confirmation").mkdir()
        (self.root / "model.py").write_text("BOUND = 1\n")
        self.r2 = resolve_experiment(root=self.root)
        self.core = resolve_experiment("core-c1", root=self.root)
        self.document = self.core.plan_path.parent / "PROTOCOL.md"
        self.document.write_text("Prospective hand fixture, no data execution.\n")
        self.core_plan = {"experiment_id": "core-c1", "systems": list(self.core.systems),
            "static_modes": ["full"], "control_reserve_units": 0,
            "control_reserve_cpu_seconds": 0.0, "protocol_path": "core_confirmation/PROTOCOL.md",
            "protocol_sha256": hashlib.sha256(self.document.read_bytes()).hexdigest()}
        self.r2.plan_path.write_text(json.dumps({"systems": list(self.r2.systems)}))
        self.core.plan_path.write_text(json.dumps(self.core_plan))
        for command in (["git", "init", "-q"], ["git", "add", "."],
            ["git", "-c", "user.name=Profile fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "fixture"]):
            subprocess.run(command, cwd=self.repo, check=True, capture_output=True)
        for key, value in (("ROOT", self.root), ("PLAN", self.r2.plan_path),
                           ("MARKER", self.r2.marker_path)):
            manager = patch.object(run, key, value)
            manager.start()
            self.addCleanup(manager.stop)

    def test_registry_rejects_arbitrary_identity_and_is_immutable(self):
        self.assertEqual(self.core.systems, self.r2.systems[:-1])
        self.assertNotEqual(self.core.marker_path, self.r2.marker_path)
        with self.assertRaises(FrozenInstanceError):
            self.core.marker_path = self.r2.marker_path
        for name in (self.core, None, "unknown", "../core-c1", str(self.core.marker_path)):
            with self.subTest(name=str(name)), self.assertRaises(ValueError):
                resolve_experiment(name, root=self.root)
        for changes in ({"systems": list(self.r2.systems)}, {"static_modes": ["full", "low"]},
                        {"controller": {}}, {"control_reserve_units": 1},
                        {"experiment_id": "efficient-r2"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_plan(self.core, {**self.core_plan, **changes})
        bind_identity(self.r2, {})
        with self.assertRaisesRegex(ValueError, "identity"):
            bind_identity(self.core, {})

    def test_r2_marker_cannot_be_reused_or_block_an_independent_core_freeze(self):
        self.r2.marker_path.write_text("retained r2 opening fixture")
        receipt = self.core.plan_path.parent / "frozen.json"
        with patch.object(run, "dataset", side_effect=AssertionError("no data")) as data:
            run.freeze(receipt, experiment="core-c1")
            frozen = run.check_freeze(receipt, experiment="core-c1")
            self.assertEqual(frozen["experiment_id"], "core-c1")
            self.assertEqual(frozen["sources"], {"model.py": run.sha(self.root / "model.py")})
            with self.assertRaisesRegex(ValueError, "identity"):
                run.check_freeze(receipt)
            with self.assertRaisesRegex(ValueError, "already opened"):
                run.freeze(self.root / "r2-freeze.json")
            data.assert_not_called()
        self.assertFalse(self.core.marker_path.exists())
        self.assertEqual(self.r2.marker_path.read_text(), "retained r2 opening fixture")

    def test_core_opening_blocks_new_output_and_cross_profile_receipts(self):
        r2_receipt, core_receipt = self.root / "r2.json", self.root / "core.json"
        run.freeze(r2_receipt)
        run.freeze(core_receipt, experiment="core-c1")
        with self.assertRaisesRegex(ValueError, "identity"):
            run.check_freeze(r2_receipt, experiment="core-c1")
        self.core.marker_path.write_text("retained core fixture")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.check_freeze(core_receipt, experiment="core-c1")
        with self.assertRaisesRegex(ValueError, "already opened"):
            run.freeze(self.root / "different-output.json", experiment="core-c1")
        run.check_freeze(r2_receipt)
        self.assertFalse((self.root / "different-output.json").exists())

    def test_protocol_bytes_and_committed_document_are_both_required(self):
        receipt = self.root / "frozen.json"
        run.freeze(receipt, experiment="core-c1")
        self.document.write_text("Changed prospective document.\n")
        with self.assertRaisesRegex(ValueError, "protocol document"):
            run.check_freeze(receipt, experiment="core-c1")
        self.core_plan["protocol_sha256"] = hashlib.sha256(self.document.read_bytes()).hexdigest()
        self.core.plan_path.write_text(json.dumps(self.core_plan))
        subprocess.run(["git", "add", "qualification/joint-generation/core_confirmation/plan.json"],
                       cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Profile fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-qm", "plan only"], cwd=self.repo, check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, "commit all protocol/source bytes"):
            run.freeze(self.root / "uncommitted-doc.json", experiment="core-c1")
        self.assertFalse((self.root / "uncommitted-doc.json").exists())

    def test_cli_forwards_only_locked_identity_without_running_an_experiment(self):
        for arguments in (("--experiment", "core-c1", "freeze", "--receipt", "receipt.json"),
                          ("freeze", "--experiment", "core-c1", "--receipt", "receipt.json")):
            with self.subTest(arguments=arguments), patch.object(sys, "argv", ["engine", *arguments]), \
                    patch.object(run, "freeze") as freeze:
                self.assertEqual(run.main(), 0)
                freeze.assert_called_once_with("receipt.json", experiment="core-c1")


class FullValidationTests(unittest.TestCase):
    def test_full_mode_executes_and_reserves_no_low_or_ensemble_work(self):
        model = JointModel(202, 12, 192, hidden=4, seed=71)
        manual = {"full": np.random.default_rng(27).uniform(0, 1, (4, 202)),
                  "labels": np.array([0, 1, 2, 3])}
        ledger = WorkLedger("full-validation-fixture")
        expected = add_work(FrozenGenerator(model, prepare_low=False).full_work(4),
                            observer_work(4), setup_work(model.dimensions, "additive"))
        before = model.digest()
        with patch.object(FrozenGenerator, "_prepare", side_effect=AssertionError("unused fold")), \
             patch.object(FrozenGenerator, "forward_low", side_effect=AssertionError("unused low")):
            metrics, predictions = run.batch_validation(model, manual, ledger, modes=["full"])
            reserved = reserve_work(model, "ndu", "full", train_rows=4, validation_rows=4,
                calibration_rows=4, calibration_repeats=3, plan={"static_modes": ["full"]})
        self.assertEqual(set(metrics), {"full"})
        self.assertEqual(set(predictions), {"full"})
        self.assertEqual(reserved["revalidation"], expected)
        self.assertEqual(ledger.consumed_units, ledger.estimate_kernel(**expected))
        self.assertEqual(ledger.totals["model_forward_rows"], 4)
        self.assertEqual(ledger.totals["observer_modes"], 1)
        self.assertEqual(model.digest(), before)
        self.assertLess(ledger.consumed_units,
                        ledger.estimate_kernel(**validation_work(model, 4)))
        for modes in ([], ["full", "full"], ["continuation"]):
            receipt = ledger.snapshot()
            with self.assertRaises(ValueError):
                run.batch_validation(model, manual, ledger, modes=modes)
            self.assertEqual(ledger.snapshot(), receipt)


if __name__ == "__main__":
    unittest.main()
