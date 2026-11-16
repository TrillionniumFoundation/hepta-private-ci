"""Actual GRU migration, cold inference and interrupted execution reconciliation."""

import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED
from hepta_cells.component_types import digest
from hepta_cells.lifecycle import (
    CellError,
    CellOwner,
    Partition,
    PendingExecution,
    Qualification,
    ReadbackResult,
    RequestConflict,
    StepResult,
)
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent


class OwnerControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.partition = Partition("fixture", "agent", "predictor", "run")
        self.kernel = TemporalKernel("predictor", TemporalConfig(3, 1, 2, hidden_dim=4))
        parts = {name: digest(["fixture", name]) for name in REQUIRED}
        parts.update({name: None for name in OPTIONAL})
        parts.update(
            base=self.kernel.kernel_sha256,
            heads=self.kernel.heads_sha256,
            composition=self.kernel.config.sha256,
        )
        self.source = TemporalComponent(self.kernel, Bundle("parent", 1, parts), "run")
        candidate = copy.deepcopy(self.kernel)
        candidate._model.params["by"][0] += 0.25
        self.evaluation = digest("fixture-only-qualified-head-change")
        bundle = self.source.bundle.successor(
            "candidate",
            {**parts, "heads": candidate.heads_sha256},
            digest("fixture-data"),
            digest("fixture-head-edit"),
            self.evaluation,
        )
        self.target = TemporalComponent(candidate, bundle, "run")
        self.qualification = Qualification(
            self.source.identity.digest, self.target.identity.digest, self.evaluation
        )
        self.owner = CellOwner(
            self.root / "owner.sqlite", qualify=lambda q: q == self.qualification
        )
        self.owner.create(self.partition, self.source)
        self.payload = {
            "operation": "observe",
            "cursor": 0,
            "observation": [1.0, -1.0, 0.5],
        }

    def tearDown(self):
        self.owner.close()
        self.temp.cleanup()

    def migrate(self, checkpoint, operation="upgrade"):
        return self.owner.migrate(
            self.partition,
            self.source,
            self.target,
            self.qualification,
            operation_id=operation,
            checkpoint_id=checkpoint["digest"],
        )

    def run_child(self, program, spec):
        path = self.root / "request.json"
        path.write_text(json.dumps(spec))
        result = subprocess.run(
            [sys.executable, "-c", program, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent)},
        )
        return result

    def test_readout_migration_retains_actual_state_and_cold_inference(self):
        original = self.owner.step(
            self.partition, self.source, "observed", self.payload
        )
        before = self.owner.checkpoint(self.partition)
        self.assertNotEqual(
            before["state"]["hidden"], self.source.initial_state()["hidden"]
        )
        result = self.migrate(before)
        self.assertEqual(self.migrate(before), result)
        after = result["target_checkpoint"]
        expected_state = {
            **before["state"],
            "weights_sha256": self.target.kernel.weights_sha256,
        }
        self.assertEqual(after["state"], expected_state)
        self.assertEqual(
            (after["epoch"], after["sequence"], after["remaining_work_units"]),
            (
                before["epoch"] + 1,
                before["sequence"] + 1,
                before["remaining_work_units"],
            ),
        )
        with self.assertRaises(CellError):
            self.owner.step(self.partition, self.source, "stale-version", self.payload)
        self.assertEqual(
            self.owner.step(self.partition, self.source, "observed", self.payload),
            original,
        )
        with self.assertRaises(RequestConflict):
            self.migrate(after)
        predicted = self.owner.step(
            self.partition,
            self.target,
            "prediction",
            {"operation": "predict", "action": [0.0]},
        )
        model_hash = self.target.kernel.checkpoint(
            self.root / "model.npz", expected_state
        )
        spec = dict(
            root=str(self.root),
            model_hash=model_hash,
            config=asdict(self.kernel.config),
            bundle=asdict(self.target.bundle),
            partition=asdict(self.partition),
        )
        child = self.run_child(
            """
import json, os, sys
from pathlib import Path
from hepta_cells.bundle import Bundle
from hepta_cells.lifecycle import CellOwner, Partition
from hepta_cells.temporal import TemporalKernel, TemporalConfig
from hepta_cells.temporal_component import TemporalComponent
s = json.loads(Path(sys.argv[1]).read_text()); root = Path(s["root"])
k, state = TemporalKernel.restore_checkpoint(root / "model.npz", expected_sha256=s["model_hash"], cell_id="predictor", config=TemporalConfig(**s["config"]))
c = TemporalComponent(k, Bundle(**s["bundle"]), "run")
o = CellOwner(root / "owner.sqlite"); p = Partition(**s["partition"])
assert o.checkpoint(p)["state"] == state
r = o.step(p, c, "cold-new-prediction", {"operation":"predict", "action":[0.0]})
o.close(); print(json.dumps({"pid": os.getpid(), "receipt": r}))
""",
            spec,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        observed = json.loads(child.stdout)
        self.assertNotEqual(observed["pid"], os.getpid())
        self.assertEqual(
            observed["receipt"]["output"]["logits"], predicted["output"]["logits"]
        )
        self.assertEqual(observed["receipt"]["sequence"], predicted["sequence"] + 1)

    def test_cancel_after_actual_gru_exit_stays_unknown_until_exact_readback(self):
        checkpoint = self.owner.checkpoint(self.partition)
        spec = dict(
            root=str(self.root),
            config=asdict(self.kernel.config),
            bundle=asdict(self.source.bundle),
            partition=asdict(self.partition),
            payload=self.payload,
        )
        child = self.run_child(
            """
import json, os, sys, time
from dataclasses import asdict
from pathlib import Path
from hepta_cells.bundle import Bundle
from hepta_cells.lifecycle import CellOwner, Partition
from hepta_cells.temporal import TemporalKernel, TemporalConfig
from hepta_cells.temporal_component import TemporalComponent
s = json.loads(Path(sys.argv[1]).read_text()); root = Path(s["root"])
k = TemporalKernel("predictor", TemporalConfig(**s["config"]))
c = TemporalComponent(k, Bundle(**s["bundle"]), "run"); original = c.step
def interrupted(payload, state, context):
    start = time.perf_counter_ns(); r = original(payload, state, context)
    observed = {"result": asdict(r), "elapsed_ns": time.perf_counter_ns()-start}
    with (root / "actual-readback.json").open("x") as f:
        json.dump(observed, f); f.flush(); os.fsync(f.fileno())
    os._exit(17)
c.step = interrupted
o = CellOwner(root / "owner.sqlite"); o.step(Partition(**s["partition"]), c, "interrupted", s["payload"])
""",
            spec,
        )
        self.assertEqual(child.returncode, 17, child.stderr)
        pending = self.owner.status(self.partition)
        cancelled = self.owner.request_cancel(
            self.partition, self.source, "interrupted"
        )
        self.assertEqual(
            (cancelled["outcome"], cancelled["receipt"]), ("unknown", None)
        )
        self.assertEqual(self.owner.status(self.partition), pending)
        with self.assertRaises(PendingExecution):
            self.migrate(checkpoint)
        with self.assertRaises(PendingExecution):
            self.owner.step(self.partition, self.source, "interrupted", self.payload)
        self.owner.close()
        self.owner = CellOwner(
            self.root / "owner.sqlite", qualify=lambda q: q == self.qualification
        )
        self.assertEqual(
            self.owner.cancellation_status(self.partition, "interrupted"), cancelled
        )
        with self.assertRaises(PendingExecution):
            self.owner.reconcile(
                self.partition, self.source, "interrupted", lambda _: None
            )
        raw = json.loads((self.root / "actual-readback.json").read_text())
        with patch.object(
            self.source, "step", side_effect=AssertionError("must not replay")
        ):
            receipt = self.owner.reconcile(
                self.partition,
                self.source,
                "interrupted",
                lambda _: ReadbackResult(
                    StepResult(**raw["result"]), raw["elapsed_ns"]
                ),
            )
        self.assertEqual(receipt["output"]["cursor"], 1)
        settled = self.owner.cancellation_status(self.partition, "interrupted")
        self.assertEqual((settled["outcome"], settled["receipt"]), ("settled", receipt))
        self.assertEqual(
            self.owner.request_cancel(self.partition, self.source, "interrupted"),
            settled,
        )
        self.assertEqual(
            self.migrate(self.owner.checkpoint(self.partition))["target_checkpoint"][
                "state"
            ]["cursor"],
            1,
        )

    def test_stale_checkpoint_or_changed_dynamics_cannot_publish_partial_migration(
        self,
    ):
        stale = self.owner.checkpoint(self.partition)
        self.owner.step(self.partition, self.source, "observed", self.payload)
        before = self.owner.checkpoint(self.partition)
        with self.assertRaises(CellError):
            self.migrate(stale)
        with self.assertRaises(CellError):
            self.owner.request_cancel(self.partition, self.source, "never-admitted")
        for change in ("kernel", "schema"):
            with self.subTest(change=change):
                original = self.target
                changed_kernel = copy.deepcopy(original.kernel)
                components = dict(original.bundle.components)
                if change == "kernel":
                    recurrent = next(
                        k
                        for k in changed_kernel._model.params
                        if k not in ("Wh", "bh", "Wy", "by")
                    )
                    changed_kernel._model.params[recurrent].flat[0] += 0.1
                    components["base"] = changed_kernel.kernel_sha256
                else:
                    components["state_semantics"] = digest("changed-schema")
                bundle = self.source.bundle.successor(
                    "invalid",
                    components,
                    digest("data"),
                    digest("rule"),
                    self.evaluation,
                )
                self.target = TemporalComponent(changed_kernel, bundle, "run")
                self.qualification = Qualification(
                    self.source.identity.digest,
                    self.target.identity.digest,
                    self.evaluation,
                )
                with self.assertRaises(ValueError):
                    self.migrate(before, change)
                self.assertEqual(self.owner.checkpoint(self.partition), before)
                self.target = original

    def test_failed_migration_journal_write_rolls_back_the_entire_cutover(self):
        self.owner.step(self.partition, self.source, "observed", self.payload)
        before = self.owner.checkpoint(self.partition)
        self.owner.db.execute(
            "CREATE TRIGGER reject_migration BEFORE INSERT ON migrations "
            "BEGIN SELECT RAISE(ABORT, 'fixture journal failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.migrate(before)
        self.assertEqual(self.owner.checkpoint(self.partition), before)
        self.assertEqual(
            self.owner.db.execute("SELECT count(*) FROM migrations").fetchone()[0], 0
        )
        self.owner.db.execute("DROP TRIGGER reject_migration")
        migrated = self.migrate(before)
        self.assertEqual(migrated["target_checkpoint"]["epoch"], before["epoch"] + 1)


if __name__ == "__main__":
    unittest.main()
