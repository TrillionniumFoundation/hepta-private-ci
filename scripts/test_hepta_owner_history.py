"""Retained row loss cannot restart completed or unresolved owner operations."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from hepta_cells.component_types import Budget, CellError, Partition, Qualification
from hepta_cells.deterministic import NumericAlgorithm
from hepta_cells.lifecycle import CellOwner


class OwnerHistoryTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get("HEPTA_OWNER_HISTORY_ARTIFACT_ROOT")
        self.temp = None if retained else tempfile.TemporaryDirectory()
        self.root = (
            Path(retained) / self._testMethodName if retained else Path(self.temp.name)
        )
        self.root.mkdir(parents=True, exist_ok=not bool(retained))
        self.path = self.root / "owner.sqlite"
        self.partition = Partition("principal", "agent", "cell", "run")
        self.component = NumericAlgorithm("dot", "a" * 64)
        self.payload = {"left": [2], "right": [3]}

    def tearDown(self):
        if self.temp is not None:
            self.temp.cleanup()

    def fixture(self):
        owner = CellOwner(self.path)
        owner.create(self.partition, self.component)
        owner.step(self.partition, self.component, "completed", self.payload)
        owner.close()

    def edit(self, sql, arguments=()):
        db = sqlite3.connect(self.path)
        try:
            db.execute(sql, arguments)
            db.commit()
        finally:
            db.close()

    def reject_unchanged(self):
        def snapshot():
            return {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.iterdir()
                if p.is_file()
            }

        before = snapshot()
        with self.assertRaisesRegex(CellError, "owner history"):
            CellOwner(self.path)
        self.assertEqual(snapshot(), before)

    def test_deleted_committed_intent_cannot_reexecute_or_recharge(self):
        self.fixture()
        self.edit("DELETE FROM intents WHERE request='completed'")
        self.reject_unchanged()

    def test_deleted_intent_and_attempt_rows_still_fail_sequence_conservation(self):
        self.fixture()
        self.edit("DELETE FROM attempts")
        self.edit("DELETE FROM intents")
        self.reject_unchanged()

    def test_deleted_pending_intent_after_actual_child_exit_is_rejected(self):
        owner = CellOwner(self.path)
        owner.create(self.partition, self.component)
        owner.close()
        code = """
import os,sys
from hepta_cells.component_types import Partition
from hepta_cells.deterministic import NumericAlgorithm
from hepta_cells.lifecycle import CellOwner
class Crash(NumericAlgorithm):
    def step(self,*args): os._exit(47)
CellOwner(sys.argv[1]).step(Partition('principal','agent','cell','run'),Crash('dot','a'*64),'pending',{'left':[2],'right':[3]})
"""
        process = subprocess.run(
            [sys.executable, "-c", code, str(self.path)], capture_output=True, text=True
        )
        self.assertEqual((process.returncode, process.stderr), (47, ""))
        self.edit("DELETE FROM intents")
        self.reject_unchanged()
        (self.root / "process.json").write_text(
            json.dumps(
                dict(
                    exit=process.returncode,
                    stdout=process.stdout,
                    stderr=process.stderr,
                )
            )
            + "\n"
        )

    def test_deleted_current_or_intermediate_epoch_is_rejected(self):
        for generation in (0, 1, 2):
            with self.subTest(generation=generation):
                self.path = self.root / (str(generation) + ".sqlite")
                self.fixture()
                owner = CellOwner(self.path)
                owner.reset(
                    self.partition, self.component, self.component.identity.digest
                )
                owner.reset(
                    self.partition, self.component, self.component.identity.digest
                )
                owner.close()
                self.edit("DELETE FROM history WHERE generation=?", (generation,))
                self.reject_unchanged()

    def test_missing_initial_or_transition_checkpoint_is_rejected(self):
        for generation in (0, 1):
            with self.subTest(generation=generation):
                self.path = self.root / (str(generation) + ".sqlite")
                self.fixture()
                owner = CellOwner(self.path)
                owner.reset(
                    self.partition, self.component, self.component.identity.digest
                )
                removed = [
                    row[0]
                    for row in owner.db.execute(
                        "SELECT digest,snapshot FROM checkpoints"
                    )
                    if json.loads(row[1])["epoch"] == generation
                ]
                owner.close()
                for checksum in removed:
                    self.edit("DELETE FROM checkpoints WHERE digest=?", (checksum,))
                self.reject_unchanged()

    def test_changed_identity_fingerprint_receipt_or_current_state_is_rejected(self):
        changes = (
            ("identity", "UPDATE history SET identity=?", ("f" * 64,)),
            ("fingerprint", "UPDATE intents SET fingerprint=?", ("f" * 64,)),
            ("state", "UPDATE cells SET state=?", ('{"calls":9}',)),
            ("remaining", "UPDATE cells SET remaining=remaining+1", ()),
        )
        for name, sql, arguments in changes:
            with self.subTest(change=name):
                self.path = self.root / (name + ".sqlite")
                self.fixture()
                self.edit(sql, arguments)
                self.reject_unchanged()
        self.path = self.root / "receipt.sqlite"
        self.fixture()
        db = sqlite3.connect(self.path)
        receipt = json.loads(db.execute("SELECT receipt FROM intents").fetchone()[0])
        db.close()
        receipt["work_units"] += 1
        self.edit("UPDATE intents SET receipt=?", (json.dumps(receipt),))
        self.reject_unchanged()

    def test_restore_adopt_rollback_and_original_replay_remain_legal(self):
        owner = CellOwner(self.path, qualify=lambda qualification: True)
        owner.create(self.partition, self.component)
        original = owner.step(self.partition, self.component, "completed", self.payload)
        reset = owner.reset(
            self.partition, self.component, self.component.identity.digest
        )
        owner.step(self.partition, self.component, "later", self.payload)
        owner.restore(
            self.partition,
            self.component,
            reset["digest"],
            self.component.identity.digest,
        )
        target = NumericAlgorithm("dot", "b" * 64)
        owner.adopt(
            self.partition,
            target,
            Qualification(
                self.component.identity.digest, target.identity.digest, "c" * 64
            ),
        )
        owner.rollback(self.partition, self.component, target.identity.digest)
        before = owner.checkpoint(self.partition)
        owner.close()
        owner = CellOwner(self.path)
        self.assertEqual(owner.checkpoint(self.partition), before)
        self.assertEqual(
            owner.step(self.partition, self.component, "completed", self.payload),
            original,
        )
        owner.close()

    def test_committed_overbudget_result_keeps_its_actual_work_charge(self):
        owner = CellOwner(self.path)
        owner.create(self.partition, self.component, budget=Budget(max_work_units=1))
        receipt = owner.step(
            self.partition, self.component, "overrun", {"left": [1, 2], "right": [3, 4]}
        )
        self.assertEqual(
            (receipt["status"], receipt["state_applied"]), ("budget_exceeded", False)
        )
        before = owner.checkpoint(self.partition)
        owner.close()
        owner = CellOwner(self.path)
        self.assertEqual(owner.checkpoint(self.partition), before)
        self.assertEqual(owner.status(self.partition)["remaining_work_units"], 999998)
        owner.close()


if __name__ == "__main__":
    unittest.main()
