"""Synthetic FTS5 and pin tests; no task labels train or tune retrieval."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from stem_lexical_audit import K, lexical_rank, native_qa


class ImmutableLexicalTests(unittest.TestCase):
    def make_db(self):
        db = sqlite3.connect(":memory:")
        db.execute(
            "CREATE VIRTUAL TABLE lexical USING fts5(content, tokenize='unicode61')"
        )
        for i, text in enumerate(
            (
                "Caroline visited the sports team.",
                "Caroline attended the support group.",
                "Winter picnic at the river.",
            ),
            1,
        ):
            db.execute("INSERT INTO lexical(rowid,content) VALUES(?,?)", (i, text))
        return db

    def test_same_quoted_fts5_or_query_retrieval_is_deterministic(self):
        db = self.make_db()
        try:
            found = lexical_rank(db, "Who attended a support group?")
            self.assertIn(2, found)
            self.assertEqual(found, lexical_rank(db, "Who attended a support group?"))
            self.assertEqual(len(set(found)), len(found))
            self.assertTrue(all(type(i) is int for i in found))
        finally:
            db.close()

    def test_unmatched_empty_and_repeated_words_not_given_fake_labels(self):
        db = self.make_db()
        try:
            self.assertEqual(lexical_rank(db, "???"), [])
            self.assertEqual(lexical_rank(db, "quixoticnoanswerword"), [])
            self.assertEqual(
                lexical_rank(db, "support support support"), lexical_rank(db, "support")
            )
        finally:
            db.close()

    def test_question_words_parameterized_not_sql_or_fts_injection(self):
        db = self.make_db()
        try:
            row = lexical_rank(db, "support') OR DROP TABLE lexical --")
            self.assertIsInstance(row, list)
            self.assertEqual(
                db.execute("SELECT count(*) FROM lexical").fetchone()[0], 3
            )
        finally:
            db.close()

    def test_requested_depth_and_native_status_are_explicit(self):
        self.assertEqual(K, (8, 16, 32, 64))
        db = self.make_db()
        try:
            self.assertEqual(lexical_rank(db, "Caroline", maximum=1).__len__(), 1)
            self.assertGreaterEqual(len(lexical_rank(db, "Caroline")), 2)
        finally:
            db.close()

    def test_modified_or_unrelated_native_json_fails_external_pin(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "locomo.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "sample_id": "forged",
                            "qa": [{"question": "forgery", "evidence": []}],
                        }
                    ]
                )
            )
            with self.assertRaisesRegex(ValueError, "LoCoMo source bytes"):
                native_qa(path)


if __name__ == "__main__":
    unittest.main()
