"""Canonical count equivalence and bounded VM work for the owner write path."""

import sqlite3
import unittest

from test_cognitive_read_sqlite_integrity import connection, memory, migrate, source


class WitnessCountTests(unittest.TestCase):
    def assert_counts(self, db):
        self.assertEqual(
            db.execute(
                "SELECT * FROM lane_c_scope_witness_expected ORDER BY 1, 2, 3"
            ).fetchall(),
            db.execute(
                "SELECT * FROM lane_c_scope_witness_current_expected ORDER BY 1, 2, 3"
            ).fetchall(),
        )
        self.assertEqual(
            db.execute("SELECT * FROM lane_c_scope_witness_audit").fetchall(), []
        )
        self.assertEqual(
            db.execute("SELECT * FROM lane_c_head_validity_audit").fetchall(), []
        )

    def test_upgrade_and_mixed_scopes_match_independent_canonical_counts(self):
        with connection(last=20) as db:
            source(db, "s")
            memory(db, "m")
            db.execute("INSERT INTO memory_heads VALUES ('m', 1)")
            db.execute("INSERT INTO memory_citations VALUES ('m', 1, 0, 's', 1)")
            before = db.execute("SELECT * FROM lane_c_scope_witness").fetchall()
            migrate(db, first=21)
            self.assertEqual(
                db.execute("SELECT * FROM lane_c_scope_witness").fetchall(), before
            )
            self.assert_counts(db)
            for i, workspace in enumerate(["a" * 64, "f" * 64]):
                source(db, f"s{i}", workspace)
                db.execute(
                    """INSERT INTO memory_revisions
                    SELECT ?, 1, owner_agent_id, 'workspace_private', ?, content,
                           content_sha256, verification, lifecycle, tombstone_reason,
                           valid_from_unix_seconds, valid_to_unix_seconds, NULL,
                           recorded_at_unix_seconds
                    FROM memory_revisions WHERE memory_id = 'm' AND revision = 1""",
                    (f"m{i}", workspace),
                )
                db.execute("INSERT INTO memory_heads VALUES (?, 1)", (f"m{i}",))
                db.execute(
                    "INSERT INTO memory_citations VALUES (?, 1, 0, ?, 1)",
                    (f"m{i}", f"s{i}"),
                )
                self.assert_counts(db)
            memory(db, "m", 2)
            db.execute("UPDATE memory_heads SET revision=2 WHERE memory_id='m'")
            db.execute("DELETE FROM memory_heads WHERE memory_id='m0'")
            self.assert_counts(db)

    def test_orphan_child_insert_is_rejected_even_without_foreign_keys(self):
        with connection() as db:
            source(db, "s")
            memory(db, "m")
            db.commit()
            db.execute("PRAGMA foreign_keys=OFF")
            for sql in [
                "INSERT INTO memory_citations VALUES ('absent', 1, 0, 's', 1)",
                "INSERT INTO memory_heads VALUES ('absent', 1)",
                "INSERT INTO kg_revision_fact_sets VALUES ('absent', 1, 'fixture', '"
                + "0" * 64
                + "', 's', 1, 0, 0, 100)",
            ]:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
            self.assert_counts(db)

    def test_direct_counter_forgery_and_empty_scope_are_rejected(self):
        with connection() as db:
            source(db, "s")
            memory(db, "m")
            for column in [
                "memory_revision_count",
                "source_count",
                "citation_count",
                "tombstone_count",
                "knowledge_fact_count",
                "head_count",
            ]:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        f"UPDATE lane_c_scope_witness SET {column}={column}+1, state_revision=state_revision+1"
                    )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO lane_c_scope_witness VALUES ('unknown', 'agent_private', '', 1, 0, 0, 0, 0, 0, 0)"
                )
            self.assert_counts(db)

    def test_deep_history_keeps_all_guards_without_quadratic_vm_work(self):
        with connection() as db:
            source(db, "s")
            memory(db, "m")
            db.execute("INSERT INTO memory_heads VALUES ('m', 1)")
            db.execute("INSERT INTO memory_citations VALUES ('m', 1, 0, 's', 1)")
            steps = 0

            def progress():
                nonlocal steps
                steps += 1000
                return int(steps > 50_000_000)

            db.set_progress_handler(progress, 1000)
            db.execute("""WITH RECURSIVE seq(n) AS
                (SELECT 2 UNION ALL SELECT n+1 FROM seq WHERE n<17000)
                INSERT INTO memory_revisions
                SELECT r.memory_id, seq.n, r.owner_agent_id, r.scope_kind,
                    r.workspace_sha256, r.content, r.content_sha256, r.verification,
                    r.lifecycle, r.tombstone_reason, r.valid_from_unix_seconds,
                    r.valid_to_unix_seconds, seq.n-1, r.recorded_at_unix_seconds
                FROM seq CROSS JOIN memory_revisions r
                WHERE r.memory_id='m' AND r.revision=1""")
            db.execute("""INSERT INTO memory_citations
                SELECT r.memory_id, r.revision, c.ordinal, c.source_id, c.source_revision
                FROM memory_revisions r JOIN memory_citations c
                  ON c.memory_id=r.memory_id AND c.memory_revision=1
                WHERE r.memory_id='m' AND r.revision>1""")
            db.execute("UPDATE memory_heads SET revision=17000 WHERE memory_id='m'")
            db.set_progress_handler(None, 0)
            self.assertLess(steps, 50_000_000)
            self.assert_counts(db)


if __name__ == "__main__":
    unittest.main()
