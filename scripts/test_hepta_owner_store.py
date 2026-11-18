"""Reject damaged owner history without mutating it or repeating an effect."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from hepta_cells.component_types import CellError, OwnerLimits, Partition
from hepta_cells.deterministic import NumericAlgorithm, ToolCell
from hepta_cells.lifecycle import CellOwner
from hepta_cells.receiver_handoff import ReceiverLease, ReceiverLedger, ReceiverPort
from hepta_cells import owner_store


class OwnerStoreTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get("HEPTA_OWNER_TEST_ARTIFACT_ROOT")
        self.temp = None if retained else tempfile.TemporaryDirectory()
        self.root = (
            Path(retained) / self._testMethodName if retained else Path(self.temp.name)
        )
        self.root.mkdir(parents=True, exist_ok=not bool(retained))
        self.path = self.root / "owner.sqlite"
        self.partition = Partition("principal", "agent", "cell", "run")
        self.component = NumericAlgorithm("dot", "a" * 64)

    def tearDown(self):
        if self.temp is not None:
            self.temp.cleanup()

    def create(self):
        owner = CellOwner(self.path)
        owner.create(self.partition, self.component)
        owner.close()

    def snapshot(self):
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.root.iterdir()
            if path.is_file()
        }

    def reject_unchanged(self, **kwargs):
        before = self.snapshot()
        with self.assertRaises(CellError):
            CellOwner(self.path, **kwargs)
        self.assertEqual(self.snapshot(), before)

    def edit(self, sql):
        db = sqlite3.connect(self.path)
        try:
            db.executescript(sql)
            db.commit()
        finally:
            db.close()

    def test_missing_intents_after_committed_effect_cannot_change_owner_state(self):
        lease = ReceiverLease(self.partition.digest, "old", 0, "b" * 64)
        ledger = ReceiverLedger.create(self.root / "receiver.sqlite", "7" * 64)
        self.addCleanup(ledger.close)
        tool = ToolCell(
            "append_record", "c" * 64, ReceiverPort(ledger, lease), "d" * 64
        )
        ledger.provision(lease, tool.identity.digest, tool.tool_digest)
        owner = CellOwner(self.path)
        owner.create(self.partition, tool)
        receipt = owner.step(self.partition, tool, "effect", {"record": {"value": 7}})
        checkpoint = owner.checkpoint(self.partition)
        owner.close()
        owner = CellOwner(self.path)
        self.assertEqual(
            owner.step(self.partition, tool, "effect", {"record": {"value": 7}}),
            receipt,
        )
        self.assertEqual(owner.checkpoint(self.partition), checkpoint)
        owner.close()
        self.edit("DROP TABLE intents")
        self.reject_unchanged()
        self.assertEqual(
            ledger.db.execute("SELECT count(*) FROM effects").fetchone()[0], 1
        )
        (self.root / "original-receipt.json").write_text(json.dumps(receipt) + "\n")

    def test_every_missing_table_is_rejected_without_recreation(self):
        self.create()
        db = sqlite3.connect(self.path)
        tables = [
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        db.close()
        original = self.path.read_bytes()
        for table in tables:
            with self.subTest(table=table):
                self.path = self.root / (table + ".sqlite")
                self.path.write_bytes(original)
                self.edit("DROP TABLE " + table)
                self.reject_unchanged()

    def test_matching_columns_without_original_uniqueness_are_rejected(self):
        self.create()
        self.edit(
            "DROP TABLE intents; CREATE TABLE intents(partition TEXT NOT NULL, request TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, generation INTEGER NOT NULL, status TEXT NOT NULL, reserved INTEGER NOT NULL, identity TEXT NOT NULL, view TEXT NOT NULL, budget TEXT NOT NULL, receipt TEXT)"
        )
        self.reject_unchanged()

    def test_missing_or_invalid_policy_cannot_reset_budgets(self):
        for name, change in (
            ("missing", "DELETE FROM owner_settings"),
            ("invalid", "UPDATE owner_settings SET limits='{}'"),
        ):
            with self.subTest(case=name):
                self.path = self.root / (name + ".sqlite")
                self.create()
                self.edit(change)
                self.reject_unchanged()

    def test_zero_byte_and_orphan_sidecars_never_become_new_stores(self):
        self.path.touch()
        self.reject_unchanged()
        self.path = self.root / "orphan.sqlite"
        Path(str(self.path) + "-wal").write_bytes(b"retained")
        self.reject_unchanged()
        self.assertFalse(self.path.exists())

    def test_policy_mismatch_does_not_modify_the_store(self):
        self.create()
        self.reject_unchanged(limits=OwnerLimits(max_cells=1))

    def test_failed_initializer_is_retained_and_never_recreated(self):
        with patch.object(owner_store, "_SCHEMA", owner_store._SCHEMA + "INVALID SQL;"):
            with self.assertRaises(CellError):
                CellOwner(self.path)
        self.assertTrue(self.path.exists())
        self.reject_unchanged()

    def test_live_wal_commit_is_used_by_cold_open_and_receipt_replay(self):
        owner = CellOwner(self.path)
        self.addCleanup(owner.close)
        owner.create(self.partition, self.component)
        receipt = owner.step(
            self.partition, self.component, "done", {"left": [2], "right": [3]}
        )
        self.assertGreater(Path(str(self.path) + "-wal").stat().st_size, 0)
        recovered = CellOwner(self.path)
        self.addCleanup(recovered.close)
        self.assertEqual(
            recovered.step(
                self.partition, self.component, "done", {"left": [2], "right": [3]}
            ),
            receipt,
        )

    def test_actual_hot_rollback_journal_is_preserved_for_explicit_recovery(self):
        self.create()
        self.edit("PRAGMA journal_mode=DELETE")
        code = """
import os,sqlite3,sys
db=sqlite3.connect(sys.argv[1],isolation_level=None)
db.execute('PRAGMA synchronous=FULL')
db.execute('PRAGMA cache_size=1')
db.execute('BEGIN IMMEDIATE')
db.execute('UPDATE cells SET state=?', ('x'*200000,))
os._exit(49)
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.path)], capture_output=True
        )
        self.assertEqual((result.returncode, result.stderr), (49, b""))
        journal = Path(str(self.path) + "-journal")
        self.assertGreater(journal.stat().st_size, 512)
        self.assertEqual(journal.read_bytes()[:8].hex(), "d9d505f920a163d7")
        self.reject_unchanged()

    def test_source_change_during_snapshot_requires_a_new_open(self):
        self.create()
        copy = owner_store.shutil.copyfileobj
        changed = False

        def copy_and_change(incoming, outgoing):
            nonlocal changed
            copy(incoming, outgoing)
            if not changed:
                changed = True
                self.edit("UPDATE owner_settings SET limits='{}'")

        with patch.object(owner_store.shutil, "copyfileobj", copy_and_change):
            with self.assertRaisesRegex(CellError, "changed while validating"):
                CellOwner(self.path)
        self.assertTrue(changed)
        self.reject_unchanged()

    def test_concurrent_initializers_keep_one_retained_policy(self):
        code = """
import sys
from hepta_cells.component_types import CellError,OwnerLimits
from hepta_cells.lifecycle import CellOwner
try:
    owner=CellOwner(sys.argv[1],limits=OwnerLimits(max_cells=int(sys.argv[2])))
    print(owner.limits.max_cells)
    owner.close()
except CellError:
    print('rejected')
"""
        children = [
            subprocess.Popen(
                [sys.executable, "-c", code, str(self.path), str(i)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for i in (1, 2, 3, 4)
        ]
        results = []
        for child in children:
            out, err = child.communicate(timeout=20)
            self.assertEqual((child.returncode, err), (0, ""))
            results.append(out.strip())
        winners = [result for result in results if result != "rejected"]
        self.assertEqual(len(winners), 1)
        recovered = CellOwner(self.path)
        self.assertEqual(recovered.limits.max_cells, int(winners[0]))
        recovered.close()
        (self.root / "processes.json").write_text(json.dumps(results) + "\n")


if __name__ == "__main__":
    unittest.main()
