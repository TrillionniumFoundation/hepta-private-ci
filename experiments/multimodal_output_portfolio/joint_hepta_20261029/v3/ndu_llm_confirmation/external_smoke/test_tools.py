import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from . import tools
from .tools import ROOT, bank, dispatch, public_task, source_bytes, source_read, sql_query


class ActualTools(unittest.TestCase):
    def test_public_interface_omits_answer_and_oracle(self):
        for task in bank()["tasks"]:
            visible = public_task(task)
            self.assertEqual(set(visible), {"task_id", "family", "source_cluster",
                                           "question", "answer_format"})

    def test_mutation_and_file_attachment_denied(self):
        for query in ("DELETE FROM Artist", "ATTACH ':memory:' AS other",
                      "PRAGMA user_version=99", "SELECT load_extension('missing')"):
            with self.assertRaises(sqlite3.DatabaseError):
                sql_query(query)
        self.assertEqual(sql_query("SELECT COUNT(*) AS count FROM Artist")["rows"], [[275]])

    def test_rows_and_execution_are_bounded(self):
        manifest = json.loads((ROOT / "sources.json").read_text())
        row = next(row for row in manifest["files"] if row["local_file"] == "chinook.sql")
        stored = (ROOT / "sources" / row["storage_file"]).read_bytes()
        decoded = gzip.decompress(stored)
        self.assertEqual(int.from_bytes(stored[4:8], "little"), 0)
        self.assertEqual(hashlib.sha256(stored).hexdigest(), row["storage_sha256"])
        self.assertEqual(hashlib.sha256(decoded).hexdigest(), row["sha256"])
        self.assertEqual(len(decoded), row["bytes"])
        raw = ROOT / "sources" / row["local_file"]
        if raw.exists():
            self.assertEqual(decoded, raw.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sources").mkdir()
            (root / "sources.json").write_text(json.dumps(manifest))
            (root / "sources" / row["storage_file"]).write_bytes(stored)
            self.assertFalse((root / "sources" / row["local_file"]).exists())
            with patch.object(tools, "ROOT", root):
                self.assertEqual(source_bytes("chinook.sql"), decoded)
        with self.assertRaises(ValueError):
            sql_query("SELECT Name FROM Track")
        with self.assertRaises(sqlite3.OperationalError):
            sql_query("WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM t) SELECT SUM(n) FROM t")

    def test_cross_family_and_source_path_rejected(self):
        task = next(task for task in bank()["tasks"] if task["family"] == "sqlite_query")
        with self.assertRaises(ValueError):
            dispatch("source", public_task(task), {"needle": "def"})
        with self.assertRaises(ValueError):
            source_read({"path": "../tasks.json"})
        with self.assertRaises(ValueError):
            source_read({"start_line": True, "line_count": 1})

    def test_large_single_value_is_rejected_before_result_capture(self):
        with self.assertRaises(sqlite3.DataError):
            sql_query("SELECT zeroblob(1000000000)")


if __name__ == "__main__":
    unittest.main()
