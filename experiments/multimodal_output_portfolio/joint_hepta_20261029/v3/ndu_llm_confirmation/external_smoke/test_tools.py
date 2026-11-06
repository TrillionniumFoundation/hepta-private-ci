import sqlite3
import unittest

from .tools import bank, dispatch, public_task, source_read, sql_query


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
