"""Execute the E2E fixture's real read-only SQL against immutable-cut examples.

This checks the evidence query, not production schema admission or host trust.
The actual daemon E2E separately checks its source/receipt/digest assertions.
"""

from pathlib import Path
import re
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUST = ROOT / "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs"


class CompactProjectionEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture = RUST.read_text().split("async fn read_kg_sqlite_evidence(", 1)[1]
        self.query = re.search(
            r'"(WITH selected_generation AS \(.*?)",\n', fixture, re.S
        )[1]
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE kg_projection_generation_receipts (
                projection_scope TEXT, generation INTEGER, trigger_memory_id TEXT,
                trigger_memory_revision INTEGER, fact_set_sha256 TEXT,
                input_heads_sha256 TEXT, output_sha256 TEXT, entity_count INTEGER,
                relation_count INTEGER, node_count INTEGER, edge_count INTEGER);
            CREATE TABLE kg_projection_generation_semantics (
                projection_scope TEXT, generation INTEGER, generation_sha256 TEXT,
                publication_sha256 TEXT);
            CREATE TABLE kg_projection_generation_storage (
                projection_scope TEXT, generation INTEGER, storage_mode TEXT);
            CREATE TABLE kg_projection (projection_scope TEXT, generation INTEGER);
            CREATE TABLE memory_revisions (
                memory_id TEXT, revision INTEGER, verification TEXT, lifecycle TEXT);
            CREATE TABLE kg_revision_entities (memory_id TEXT, memory_revision INTEGER);
            CREATE TABLE kg_revision_relations (memory_id TEXT, memory_revision INTEGER);
        """)
        self.add(1, "a", 1, 2, 1, 2, 1)
        self.add(2, "b", 1, 3, 1, 5, 2)
        self.add(3, "a", 2, 1, 0, 4, 1)
        self.add(4, "b", 2, 0, 0, 1, 0, lifecycle="tombstoned")

    def add(
        self,
        generation,
        memory,
        revision,
        entities,
        relations,
        nodes,
        edges,
        *,
        scope="private",
        lifecycle="active",
    ):
        self.db.execute(
            "INSERT INTO kg_projection_generation_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                scope,
                generation,
                memory,
                revision,
                "facts",
                "heads",
                "output",
                entities,
                relations,
                nodes,
                edges,
            ),
        )
        self.db.execute(
            "INSERT INTO kg_projection_generation_semantics VALUES (?,?,?,?)",
            (scope, generation, "canonical", "publication"),
        )
        self.db.execute(
            "INSERT INTO kg_projection_generation_storage VALUES (?,?,?)",
            (scope, generation, "revision_facts_v1"),
        )
        self.db.execute(
            "INSERT INTO memory_revisions VALUES (?,?,?,?)",
            (memory, revision, "verified", lifecycle),
        )
        for table, count in [
            ("kg_revision_entities", entities),
            ("kg_revision_relations", relations),
        ]:
            self.db.executemany(
                f"INSERT INTO {table} VALUES (?,?)", [(memory, revision)] * count
            )

    def select(self, generation, memory, revision):
        self.db.execute("DELETE FROM kg_projection")
        self.db.execute(
            "INSERT INTO kg_projection VALUES ('private', ?)", (generation,)
        )
        return self.db.execute(self.query, (memory, revision)).fetchone()

    def test_complete_membership_tracks_correction_and_tombstone_history(self):
        for generation, memory, revision, expected in [
            (1, "a", 1, (2, 1)),
            (2, "b", 1, (5, 2)),
            (3, "a", 2, (4, 1)),
            (4, "b", 2, (1, 0)),
        ]:
            with self.subTest(generation=generation):
                row = self.select(generation, memory, revision)
                self.assertEqual(row[8:10], expected)
                self.assertEqual(row[10:12], expected)
        # Old facts are retained, never confused with the selected live membership.
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM kg_revision_entities").fetchone(),
            (6,),
        )

    def test_missing_fact_cannot_satisfy_unchanged_receipt(self):
        self.db.execute(
            "DELETE FROM kg_revision_entities WHERE memory_id='a' AND memory_revision=2"
        )
        row = self.select(3, "a", 2)
        self.assertNotEqual(row[8:10], row[10:12])

    def test_wrong_trigger_or_missing_storage_witness_has_no_evidence(self):
        self.assertIsNone(self.select(3, "a", 1))
        self.db.execute(
            "DELETE FROM kg_projection_generation_storage WHERE generation=3"
        )
        self.assertIsNone(self.select(3, "a", 2))

    def test_unknown_storage_mode_has_no_evidence(self):
        self.db.execute(
            "UPDATE kg_projection_generation_storage SET storage_mode='unknown' WHERE generation=3"
        )
        self.assertIsNone(self.select(3, "a", 2))

    def test_other_scope_and_future_revision_do_not_leak_into_cut(self):
        self.add(100, "c", 1, 7, 5, 7, 5, scope="other")
        row = self.select(2, "b", 1)
        self.assertEqual(row[8:10], (5, 2))
        self.assertEqual(row[10:12], (5, 2))

    def test_unverified_head_does_not_resurrect_verified_predecessor(self):
        self.db.execute(
            "UPDATE memory_revisions SET verification='provisional' WHERE memory_id='a' AND revision=2"
        )
        row = self.select(3, "a", 2)
        self.assertEqual(row[10:12], (3, 1))
        self.assertNotEqual(row[8:10], row[10:12])


if __name__ == "__main__":
    unittest.main()
