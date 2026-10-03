"""Execute the product fixture's real projection-count SQL on both storage modes."""

from pathlib import Path
import re
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectionOracleTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:")
        self.addCleanup(self.database.close)
        self.database.executescript(
            """
            CREATE TABLE memory_revisions(memory_id, revision, verification, lifecycle);
            CREATE TABLE kg_revision_entities(memory_id, memory_revision, source_id, source_revision);
            CREATE TABLE kg_revision_relations(memory_id, memory_revision, source_id, source_revision);
            CREATE TABLE kg_nodes(projection_scope, generation, memory_id, memory_revision, source_id, source_revision);
            CREATE TABLE kg_edges(projection_scope, generation, memory_id, memory_revision, source_id, source_revision);
            CREATE TABLE kg_projection_generation_receipts(
                projection_scope, generation, trigger_memory_id, trigger_memory_revision,
                fact_set_sha256, input_heads_sha256, output_sha256,
                entity_count, relation_count, node_count, edge_count
            );
            CREATE TABLE kg_projection_generation_semantics(projection_scope, generation, generation_sha256, publication_sha256);
            CREATE TABLE kg_projection(projection_scope, generation);
            CREATE TABLE kg_projection_generation_storage(projection_scope, generation, storage_mode);
            INSERT INTO memory_revisions VALUES ('first',1,'verified','active'),('first',2,'verified','active'),('second',1,'verified','active');
            INSERT INTO kg_revision_entities VALUES ('first',1,'source:first-old',1),('first',2,'source:first',1),('second',1,'source:second',1);
            INSERT INTO kg_revision_relations VALUES ('second',1,'source:second',1);
            INSERT INTO kg_projection_generation_receipts VALUES
                ('scope',1,'first',1,'f1','h1','o1',1,0,1,0),
                ('scope',2,'first',2,'f2','h2','o2',1,0,1,0),
                ('scope',3,'second',1,'f3','h3','o3',2,1,2,1);
            INSERT INTO kg_projection_generation_semantics VALUES ('scope',3,'g3','p3');
            INSERT INTO kg_projection VALUES ('scope',3);
            """
        )

    def observe(self):
        source = (
            ROOT / "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs"
        ).read_text()
        body = source.split("async fn read_kg_sqlite_evidence(", 1)[1].split(
            "async fn wait_inactive(", 1
        )[0]
        query = re.search(r'"(SELECT r\.generation,.*?)",\s*\)', body, re.S).group(1)
        arguments = ("second", 1)
        if query.count("?") == 4:
            arguments = ("source:second", "source:second", *arguments)
        return self.database.execute(query, arguments).fetchone()

    def test_revision_facts_count_all_current_heads_without_historical_duplicates(self):
        self.database.execute(
            "INSERT INTO kg_projection_generation_storage VALUES ('scope',3,'revision_facts_v1')"
        )
        row = self.observe()
        self.assertEqual(row[8:12], (2, 1, 2, 1))

    def test_copied_generation_counts_all_occurrences_not_only_trigger_memory(self):
        self.database.executescript(
            """
            INSERT INTO kg_nodes VALUES ('scope',3,'first',2,'source:first',1),('scope',3,'second',1,'source:second',1);
            INSERT INTO kg_edges VALUES ('scope',3,'second',1,'source:second',1);
            """
        )
        row = self.observe()
        self.assertEqual(row[8:12], (2, 1, 2, 1))

    def test_receipt_counts_do_not_substitute_for_independent_fact_rows(self):
        self.database.execute(
            "INSERT INTO kg_projection_generation_storage VALUES ('scope',3,'revision_facts_v1')"
        )
        self.database.execute(
            "UPDATE kg_projection_generation_receipts SET node_count=99 WHERE generation=3"
        )
        row = self.observe()
        self.assertEqual(row[10:12], (2, 1))
        self.assertNotEqual(row[8:10], row[10:12])

    def test_unknown_storage_mode_has_no_permissive_count_fallback(self):
        self.database.execute(
            "INSERT INTO kg_projection_generation_storage VALUES ('scope',3,'unknown')"
        )
        self.assertEqual(self.observe()[10:12], (-1, -1))


if __name__ == "__main__":
    unittest.main()
