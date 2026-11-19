"""Real gradients and process recovery with synthetic, same-host custody."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from hepta_cells.component_types import CellError, PendingExecution, RequestConflict
from hepta_cells.semantic_training import SemanticTrainingOwner, encoded
import test_hepta_cells_semantic as semantic_support

digest = semantic_support.digest
from hepta_cells.semantic_component import SemanticComponent, semantic_bundle


def fixture(rank=None):
    support = semantic_support.SemanticTests()
    support.setUp()
    cell = support.cell(output_dim=2 if rank else 1, rank=rank)
    component = SemanticComponent(support.pool, cell, semantic_bundle(cell, "parent"))
    targets = np.stack(support.inputs)[:, :2] @ (
        np.array([[2.0, -2.0], [-1.0, 1.0]]) if rank else np.array([[2.0], [-1.0]])
    )
    return support, component, targets


@unittest.skipUnless(os.name == "posix", "POSIX directory-fsync owner")
class TrainingOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.results = self.root / "results"
        self.results.mkdir()
        self.database = self.root / "training.sqlite"
        self.support, self.component, self.targets = fixture()
        self.options = dict(
            artifact_id="candidate",
            evaluation_profile=digest("profile"),
            holdout_commitment=digest("unreleased-holdout"),
            steps=70,
            learning_rate=0.1,
        )

    def propose(self, owner, **overrides):
        return owner.propose(
            "operation",
            self.component,
            self.support.inputs,
            self.targets,
            **dict(self.options, **overrides),
        )

    def test_real_gradient_material_cost_and_active_service_preservation(self):
        owner = SemanticTrainingOwner(self.database, self.results, create=True)
        before = self.component.identity
        result = self.propose(owner)
        self.assertLess(
            result.candidate.loss_after, result.candidate.loss_before * 0.001
        )
        self.assertEqual(self.component.identity, before)
        np.testing.assert_array_equal(self.support.weights, self.support.original)
        calls = len(self.support.calls)
        expected = next(self.results.glob("*.json")).read_bytes()
        self.assertEqual(result.original_bytes, expected)
        owner.close()
        owner = SemanticTrainingOwner(self.database, self.results)
        self.addCleanup(owner.close)
        for restored in (
            self.propose(owner),
            owner.recover("operation", self.component),
        ):
            self.assertEqual(restored.original_bytes, expected)
            self.assertEqual(restored.component.bundle, result.component.bundle)
            for first, second in zip(
                restored.candidate.head.arrays, result.candidate.head.arrays
            ):
                np.testing.assert_array_equal(first, second)
        self.assertEqual(len(self.support.calls), calls)
        record = json.loads(expected)
        self.assertGreaterEqual(record["training_receipt"]["host_wall_seconds"], 0)
        self.assertIsNone(record["training_receipt"]["energy_joules"])
        frozen = json.loads(
            owner.db.execute("SELECT request FROM semantic_training").fetchone()[0]
        )
        self.assertEqual(
            frozen["holdout_commitment"], self.options["holdout_commitment"]
        )
        self.assertNotIn("holdout_labels", frozen)

    def test_context_changes_refuse_before_another_encoder_call(self):
        owner = SemanticTrainingOwner(self.database, self.results, create=True)
        self.addCleanup(owner.close)
        self.propose(owner)
        calls = len(self.support.calls)
        for changed in (
            dict(holdout_commitment=digest("changed")),
            dict(evaluation_profile=digest("changed")),
            dict(artifact_id="other"),
            dict(steps=71),
            dict(learning_rate=0.2),
        ):
            with self.assertRaises(RequestConflict):
                self.propose(owner, **changed)
        with self.assertRaises(RequestConflict):
            owner.propose(
                "operation",
                self.component,
                self.support.inputs,
                self.targets + 1,
                **self.options,
            )
        self.assertEqual(len(self.support.calls), calls)

    def test_failure_cost_survives_without_retraining(self):
        def fail(_):
            raise RuntimeError("declared encoder failure")

        self.support.backend._encode = fail
        owner = SemanticTrainingOwner(self.database, self.results, create=True)
        self.addCleanup(owner.close)
        from hepta_cells.semantic import SemanticTrainingError

        with self.assertRaises(SemanticTrainingError):
            self.propose(owner)
        row = owner.db.execute("SELECT * FROM semantic_training").fetchone()
        self.assertEqual(row["status"], "Pending")
        attempt = json.loads(row["attempt"])
        self.assertEqual(attempt["original_training_receipt"]["status"], "failed")
        with self.assertRaises(PendingExecution):
            self.propose(owner)
        with self.assertRaises(PendingExecution):
            owner.recover("operation", self.component)

    def child(self, crash):
        script = f"""
import os
from test_hepta_cells_semantic_training import fixture
from hepta_cells.semantic_training import SemanticTrainingOwner
from test_hepta_cells_semantic import digest
support, component, targets = fixture()
class Interrupted(SemanticTrainingOwner):
    def _complete(self, operation, raw):
        os._exit(37)
owner = Interrupted({str(self.database)!r}, {str(self.results)!r}, create=True)
if {crash!r} == "provider":
    support.backend._encode = lambda _: os._exit(38)
owner.propose("operation", component, support.inputs, targets,
              artifact_id="candidate", evaluation_profile=digest("profile"),
              holdout_commitment=digest("unreleased-holdout"), steps=70, learning_rate=0.1)
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).parent,
            capture_output=True,
            timeout=20,
        )

    def test_process_exit_after_export_recovers_original_without_training(self):
        child = self.child("after-export")
        self.assertEqual(child.returncode, 37, child.stderr.decode())
        owner = SemanticTrainingOwner(self.database, self.results)
        self.addCleanup(owner.close)
        self.assertEqual(
            owner.db.execute("SELECT status FROM semantic_training").fetchone()[0],
            "Pending",
        )
        with self.assertRaises(PendingExecution):
            self.propose(owner)
        result = owner.recover("operation", self.component)
        self.assertEqual(
            result.original_bytes, next(self.results.glob("*.json")).read_bytes()
        )
        self.assertEqual(self.support.calls, [])
        self.assertEqual(
            owner.db.execute("SELECT status FROM semantic_training").fetchone()[0],
            "Completed",
        )

    def test_process_exit_during_encoder_preserves_unknown_outcome(self):
        child = self.child("provider")
        self.assertEqual(child.returncode, 38, child.stderr.decode())
        owner = SemanticTrainingOwner(self.database, self.results)
        self.addCleanup(owner.close)
        with self.assertRaises(PendingExecution):
            owner.recover("operation", self.component)
        with self.assertRaises(PendingExecution):
            self.propose(owner)
        self.assertEqual(self.support.calls, [])

    def test_missing_database_and_corrupt_export_are_not_reinitialized(self):
        with self.assertRaises(sqlite3.OperationalError):
            SemanticTrainingOwner(self.database, self.results)
        child = self.child("after-export")
        self.assertEqual(child.returncode, 37, child.stderr.decode())
        path = next(self.results.glob("*.json"))
        record = json.loads(path.read_bytes())
        record["training_receipt"]["dataset_digest"] = digest("foreign")
        path.write_text(encoded(record))
        owner = SemanticTrainingOwner(self.database, self.results)
        self.addCleanup(owner.close)
        with self.assertRaises(CellError):
            owner.recover("operation", self.component)
        self.assertEqual(
            owner.db.execute("SELECT status FROM semantic_training").fetchone()[0],
            "Pending",
        )

    def test_pending_recovery_rejects_wrong_or_missing_original_receipt_metadata(self):
        child = self.child("after-export")
        self.assertEqual(child.returncode, 37, child.stderr.decode())
        path = next(self.results.glob("*.json"))
        original = path.read_bytes()
        owner = SemanticTrainingOwner(self.database, self.results)
        self.addCleanup(owner.close)
        for field in ("schema", "cell_id", "objective", "target_name"):
            for replacement in ("foreign", None):
                record = json.loads(original)
                if replacement is None:
                    record["training_receipt"].pop(field)
                else:
                    record["training_receipt"][field] = replacement
                path.write_text(encoded(record))
                with self.subTest(field=field, replacement=replacement):
                    with self.assertRaises(CellError):
                        owner.recover("operation", self.component)
                    self.assertEqual(
                        owner.db.execute(
                            "SELECT status FROM semantic_training"
                        ).fetchone()[0],
                        "Pending",
                    )
        path.write_bytes(original)
        self.assertEqual(
            owner.recover("operation", self.component).original_bytes, original
        )
        self.assertEqual(self.support.calls, [])

    def test_pending_recovery_requires_original_owner_cost_and_scope(self):
        child = self.child("after-export")
        self.assertEqual(child.returncode, 37, child.stderr.decode())
        path = next(self.results.glob("*.json"))
        original = path.read_bytes()
        owner = SemanticTrainingOwner(self.database, self.results)
        self.addCleanup(owner.close)
        changed = []
        record = json.loads(original)
        record.pop("owner_cost")
        changed.append(record)
        for field in ("scope", "host_wall_seconds", "process_cpu_seconds"):
            record = json.loads(original)
            record["owner_cost"].pop(field)
            changed.append(record)
        record = json.loads(original)
        record["owner_cost"]["scope"] = "foreign"
        changed.append(record)
        for field in ("host_wall_seconds", "process_cpu_seconds"):
            for value in (-1, None, True, "unknown", float("nan"), float("inf")):
                record = json.loads(original)
                record["owner_cost"][field] = value
                changed.append(record)
        for index, record in enumerate(changed):
            path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")))
            with self.subTest(case=index):
                with self.assertRaises(CellError):
                    owner.recover("operation", self.component)
                self.assertEqual(
                    owner.db.execute("SELECT status FROM semantic_training").fetchone()[
                        0
                    ],
                    "Pending",
                )
        path.write_bytes(original)
        self.assertEqual(
            owner.recover("operation", self.component).original_bytes, original
        )
        self.assertEqual(self.support.calls, [])

    def test_low_rank_head_restores_both_factors_and_completed_digest_is_checked(self):
        self.support, self.component, self.targets = fixture(rank=1)
        owner = SemanticTrainingOwner(self.database, self.results, create=True)
        self.addCleanup(owner.close)
        result = self.propose(owner)
        restored = owner.recover("operation", self.component)
        self.assertEqual(
            [a.shape for a in restored.candidate.head.arrays], [(2, 1), (2,), (1, 2)]
        )
        self.assertEqual(restored.original_bytes, result.original_bytes)
        owner.db.execute("UPDATE semantic_training SET result=?", (b"{}",))
        with self.assertRaises(CellError):
            owner.recover("operation", self.component)


if __name__ == "__main__":
    unittest.main()
