"""Creation races and non-mutating rejection of damaged receiver stores."""

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

from hepta_cells.component_types import CellError
from hepta_cells import receiver_store
from hepta_cells.receiver_store import create_receiver, open_receiver


class StoreTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get("HEPTA_RECEIVER_TEST_ARTIFACT_ROOT")
        self.temp = None if retained else tempfile.TemporaryDirectory()
        self.root = (
            Path(retained) / ("store_" + self._testMethodName)
            if retained
            else Path(self.temp.name)
        )
        self.root.mkdir(parents=True, exist_ok=not bool(retained))
        self.path = self.root / "receiver.sqlite"
        self.identity = "7" * 64

    def tearDown(self):
        if self.temp is not None:
            self.temp.cleanup()

    def snapshot(self):
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.iterdir()
            if p.is_file()
        }

    def reject_unchanged(self, identity=None):
        before = self.snapshot()
        with self.assertRaises(CellError):
            open_receiver(self.path, identity or self.identity)
        self.assertEqual(self.snapshot(), before)

    def edit(self, sql):
        db = sqlite3.connect(self.path)
        try:
            db.executescript(sql)
            db.commit()
        finally:
            db.close()

    def test_explicit_create_legal_cold_open_and_identity_mismatch(self):
        create_receiver(self.path, self.identity)
        db = open_receiver(self.path, self.identity)
        db.execute(
            "INSERT INTO authority VALUES(?,?,?,?,?,?,?)",
            ("1" * 64, "owner", 0, "2" * 64, "3" * 64, "4" * 64, "active"),
        )
        db.close()
        self.reject_unchanged("8" * 64)
        reopened = open_receiver(self.path, self.identity)
        self.assertEqual(
            reopened.execute("SELECT count(*) FROM authority").fetchone()[0], 1
        )
        reopened.close()
        before = self.snapshot()
        with self.assertRaises(FileExistsError):
            create_receiver(self.path, self.identity)
        self.assertEqual(self.snapshot(), before)

    def test_missing_and_zero_byte_stores_are_never_initialized_on_open(self):
        self.reject_unchanged()
        self.assertFalse(self.path.exists())
        self.path.touch()
        self.reject_unchanged()
        with self.assertRaises(FileExistsError):
            create_receiver(self.path, self.identity)
        self.assertEqual(self.path.stat().st_size, 0)

    def test_each_missing_table_is_rejected_without_repair(self):
        for table in ("effects", "authority", "transfers", "metadata"):
            with self.subTest(table=table):
                self.path = self.root / (table + ".sqlite")
                create_receiver(self.path, self.identity)
                self.edit("DROP TABLE " + table)
                self.reject_unchanged()

    def test_missing_or_changed_metadata_is_rejected(self):
        for name, sql in [
            ("missing", "DELETE FROM metadata"),
            ("version", "UPDATE metadata SET version='other'"),
            ("hash", "UPDATE metadata SET schema_sha256='broken'"),
        ]:
            with self.subTest(case=name):
                self.path = self.root / (name + ".sqlite")
                create_receiver(self.path, self.identity)
                self.edit(sql)
                self.reject_unchanged()

    def test_same_columns_without_required_constraints_are_rejected(self):
        variants = [
            "partition TEXT, request TEXT, operation TEXT, invocation TEXT, record TEXT, receipt TEXT",
            "partition TEXT NOT NULL, request TEXT NOT NULL, operation TEXT NOT NULL, invocation TEXT NOT NULL, record TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(partition,request)",
            "partition TEXT NOT NULL, request TEXT, operation TEXT NOT NULL, invocation TEXT NOT NULL, record TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(partition,request), UNIQUE(partition,operation)",
        ]
        for number, columns in enumerate(variants):
            with self.subTest(variant=number):
                self.path = self.root / (str(number) + ".sqlite")
                create_receiver(self.path, self.identity)
                self.edit("DROP TABLE effects; CREATE TABLE effects(" + columns + ")")
                self.reject_unchanged()

    def test_failed_initializer_leaves_an_unopenable_retained_path(self):
        with patch.object(
            receiver_store, "_SCHEMA", receiver_store._SCHEMA + "INVALID SQL;"
        ):
            with self.assertRaises(sqlite3.Error):
                create_receiver(self.path, self.identity)
        self.assertTrue(self.path.exists())
        self.reject_unchanged()
        with self.assertRaises(FileExistsError):
            create_receiver(self.path, self.identity)

    def test_concurrent_initializers_have_one_winner(self):
        code = """
import sys
from hepta_cells.receiver_store import create_receiver
try:
    create_receiver(sys.argv[1], '7' * 64)
    print('created')
except FileExistsError:
    print('exists')
"""
        children = [
            subprocess.Popen(
                [sys.executable, "-c", code, str(self.path)],
                env=dict(os.environ, PYTHONPATH=str(Path(__file__).parent)),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(4)
        ]
        results = []
        for child in children:
            out, err = child.communicate(timeout=20)
            results.append(
                {
                    "pid": child.pid,
                    "exit": child.returncode,
                    "stdout": out,
                    "stderr": err,
                }
            )
            self.assertEqual((child.returncode, err), (0, ""))
        (self.root / "processes.json").write_text(json.dumps(results, indent=2) + "\n")
        self.assertEqual(
            sorted(r["stdout"].strip() for r in results), ["created"] + ["exists"] * 3
        )
        open_receiver(self.path, self.identity).close()

    def test_wal_format_is_rejected_before_sqlite_can_touch_sidecars(self):
        create_receiver(self.path, self.identity)
        self.edit("PRAGMA journal_mode=WAL;")
        self.reject_unchanged()


if __name__ == "__main__":
    unittest.main()
