"""Independent SQLite fixtures for the product compact-generation witness."""

import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs"


def product_query():
    source = SOURCE.read_text()
    start = (
        source.index(
            '"WITH target AS (', source.index("async fn read_kg_sqlite_evidence(")
        )
        + 1
    )
    end = source.index('",\n    )\n    .bind(memory_id)', start)
    return source[start:end]


class ProductWitnessTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
          CREATE TABLE kg_projection(projection_scope TEXT, generation INTEGER);
          CREATE TABLE kg_projection_generation_receipts(
            projection_scope TEXT, generation INTEGER, trigger_memory_id TEXT,
            trigger_memory_revision INTEGER, fact_set_sha256 TEXT,
            input_heads_sha256 TEXT, output_sha256 TEXT, entity_count INTEGER,
            relation_count INTEGER, node_count INTEGER, edge_count INTEGER);
          CREATE TABLE kg_projection_generation_semantics(
            projection_scope TEXT, generation INTEGER, generation_sha256 TEXT,
            publication_sha256 TEXT);
          CREATE TABLE kg_projection_generation_storage(
            projection_scope TEXT, generation INTEGER, storage_mode TEXT);
          CREATE TABLE memory_revisions(memory_id TEXT, revision INTEGER,
            verification TEXT, lifecycle TEXT);
          CREATE TABLE kg_revision_entities(memory_id TEXT, memory_revision INTEGER);
          CREATE TABLE kg_revision_relations(memory_id TEXT, memory_revision INTEGER);
          INSERT INTO kg_projection VALUES('scope', 1);
        """)
        # Deliberately no legacy kg_nodes/kg_edges tables.
        cases = [
            (1, "a", 1, "active", 2, 1, 2, 1),
            (2, "b", 1, "active", 1, 0, 3, 1),
            (3, "a", 2, "active", 1, 0, 2, 0),
            (4, "b", 2, "forgotten", 1, 0, 1, 0),
            (5, "a", 3, "active", 100, 100, 100, 100),
        ]
        for (
            generation,
            memory,
            revision,
            lifecycle,
            entities,
            relations,
            nodes,
            edges,
        ) in cases:
            self.db.execute(
                "INSERT INTO memory_revisions VALUES(?,?,?,?)",
                (memory, revision, "verified", lifecycle),
            )
            self.db.executemany(
                "INSERT INTO kg_revision_entities VALUES(?,?)",
                [(memory, revision)] * entities,
            )
            self.db.executemany(
                "INSERT INTO kg_revision_relations VALUES(?,?)",
                [(memory, revision)] * relations,
            )
            self.db.execute(
                "INSERT INTO kg_projection_generation_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "scope",
                    generation,
                    memory,
                    revision,
                    "fact",
                    "input",
                    "output",
                    entities,
                    relations,
                    nodes,
                    edges,
                ),
            )
            self.db.execute(
                "INSERT INTO kg_projection_generation_semantics VALUES(?,?,?,?)",
                ("scope", generation, "generation", "publication"),
            )
            self.db.execute(
                "INSERT INTO kg_projection_generation_storage VALUES(?,?,?)",
                ("scope", generation, "revision_facts_v1"),
            )

    def read(self, generation, memory, revision):
        self.db.execute("UPDATE kg_projection SET generation=?", (generation,))
        return self.db.execute(product_query(), (memory, revision)).fetchone()

    def test_scope_correction_forget_and_future_cut(self):
        for generation, memory, revision, expected in [
            (1, "a", 1, (2, 1)),
            (2, "b", 1, (3, 1)),
            (3, "a", 2, (2, 0)),
            (4, "b", 2, (1, 0)),
        ]:
            with self.subTest(generation=generation):
                row = self.read(generation, memory, revision)
                self.assertEqual(row[8:10], expected)
                self.assertEqual(row[10:12], expected)

    def test_extra_fact_cannot_match_unchanged_receipt(self):
        self.db.execute("INSERT INTO kg_revision_entities VALUES('a', 2)")
        row = self.read(3, "a", 2)
        self.assertNotEqual(row[8:10], row[10:12])

    def test_wrong_storage_witness_rejected(self):
        for mode in ("legacy", None):
            with self.subTest(mode=mode):
                self.db.execute(
                    "UPDATE kg_projection_generation_storage SET storage_mode=? WHERE generation=3",
                    (mode,),
                )
                self.assertIsNone(self.read(3, "a", 2))

    def test_noncurrent_generation_rejected(self):
        self.assertIsNone(self.read(3, "a", 1))
        self.assertIsNone(self.read(3, "b", 1))


if __name__ == "__main__":
    unittest.main()
