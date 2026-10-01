"""Exercise compiled SQLite migrations independently of owner-generated state."""

import hashlib
import re
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "codex-rs/hepta-memory/migrations"
OWNER = "00000000-0000-4000-8000-000000000522"
SOURCE_INSERT = """
INSERT INTO source_ledger (
    source_id, source_revision, owner_agent_id, scope_kind, workspace_sha256,
    source_kind, content, content_sha256, observed_at_unix_seconds,
    recorded_at_unix_seconds
) VALUES (?, 1, ?, ?, ?, 'explicit_memory_directive', X'61', ?, 100, 100)
"""


def migrate(db: sqlite3.Connection, first: int = 1, last: int = 20) -> None:
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if first <= int(path.name.split("_", 1)[0]) <= last:
            db.executescript(path.read_text())


def connection(last: int = 20) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA recursive_triggers = OFF")
    migrate(db, last=last)
    return db


def source(db: sqlite3.Connection, name: str, workspace: str | None = None) -> None:
    db.execute(
        SOURCE_INSERT,
        (
            name,
            OWNER,
            "agent_private" if workspace is None else "workspace_private",
            workspace,
            hashlib.sha256(b"a").hexdigest(),
        ),
    )


def memory(db: sqlite3.Connection, name: str, revision: int = 1) -> None:
    db.execute(
        """
        INSERT INTO memory_revisions (
            memory_id, revision, owner_agent_id, scope_kind, workspace_sha256,
            content, content_sha256, verification, lifecycle, tombstone_reason,
            valid_from_unix_seconds, valid_to_unix_seconds, supersedes_revision,
            recorded_at_unix_seconds
        ) VALUES (?, ?, ?, 'agent_private', NULL, 'a', ?, 'verified', 'active',
                  NULL, 100, NULL, ?, 100)
    """,
        (
            name,
            revision,
            OWNER,
            hashlib.sha256(b"a").hexdigest(),
            None if revision == 1 else revision - 1,
        ),
    )


def canonical_rows(db: sqlite3.Connection) -> None:
    source(db, "s1")
    memory(db, "a")
    db.execute("INSERT INTO cognitive_meta VALUES (1, 1, ?)", (OWNER,))
    db.execute("INSERT INTO memory_heads VALUES ('a', 1)")
    db.execute("INSERT INTO memory_citations VALUES ('a', 1, 0, 's1', 1)")
    db.execute(
        "INSERT INTO kg_revision_fact_sets VALUES ('a', 1, 'fixture', ?, 's1', 1, 2, 1, 100)",
        ("0" * 64,),
    )
    db.executemany(
        "INSERT INTO kg_revision_entities VALUES ('a', 1, ?, ?, 'fixture', ?, 100, NULL, 's1', 1)",
        [("one", "canonical-one", "one"), ("two", "canonical-two", "two")],
    )
    db.execute("""
        INSERT INTO kg_revision_relations VALUES (
            'a', 1, 'relation', 'canonical-relation', 'one', 'canonical-one',
            'two', 'canonical-two', 'related', 100, NULL, 's1', 1
        )
    """)
    for generation in (1, 2):
        db.execute(
            "INSERT INTO kg_projection_generation_receipts VALUES ('agent_private', ?, 'a', 1, ?, ?, ?, 2, 1, 2, 1, 100)",
            (generation, "0" * 64, "1" * 64, "2" * 64),
        )
        db.execute(
            "INSERT INTO kg_projection_generation_semantics VALUES ('agent_private', ?, ?, ?, ?, ?, ?)",
            (generation, *("3" * 64 for _ in range(5))),
        )
        db.execute(
            "INSERT INTO kg_projection_generation_storage VALUES ('agent_private', ?, 'revision_facts_v1')",
            (generation,),
        )
        db.executemany(
            "INSERT INTO kg_nodes VALUES ('agent_private', ?, ?, 'fixture', ?, 100, NULL, 'a', 1, 's1', 1)",
            [(generation, "node-one", "one"), (generation, "node-two", "two")],
        )
        db.executemany(
            "INSERT INTO kg_projection_node_entities VALUES ('agent_private', ?, ?, ?)",
            [
                (generation, "node-one", "canonical-one"),
                (generation, "node-two", "canonical-two"),
            ],
        )
        db.execute(
            "INSERT INTO kg_edges VALUES ('agent_private', ?, 'edge', 'node-one', 'node-two', 'related', 100, NULL, 'a', 1, 's1', 1)",
            (generation,),
        )
    db.execute("INSERT INTO kg_projection VALUES ('agent_private', 1)")
    db.execute(
        "UPDATE kg_projection SET generation = 2 WHERE projection_scope = 'agent_private'"
    )


def owner_insert_sql(filename: str, prefix: str, conflict: str) -> str:
    code = (ROOT / "codex-rs/hepta-memory/src" / filename).read_text()
    return re.search(
        '"(' + re.escape(prefix) + ".*?" + re.escape(conflict) + ')"',
        code,
        re.DOTALL,
    )[1]


def schema_oracle(db: sqlite3.Connection) -> str:
    code = (ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs").read_text()
    inventory = code.split("const REQUIRED_SCHEMA_OBJECTS:", 1)[1].split("];")[0]
    entries = re.findall(
        r'\(\s*"([^"]+)",\s*"(table|index|view|trigger)",?\s*\)', inventory
    )
    if len(entries) != len(set(entries)):
        raise AssertionError("duplicate canonical schema inventory")
    rows = []
    for name, kind in sorted(entries):
        row = db.execute(
            "SELECT type, sql FROM sqlite_schema WHERE name = ?", (name,)
        ).fetchone()
        if row is None or row[0] != kind or not row[1]:
            raise AssertionError(f"missing or malformed schema object {name}")
        rows.append((name, *row))
    digest = hashlib.sha256()

    def frame(part: bytes) -> None:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)

    frame(b"hepta:cognitive:required-schema-oracle:v1")
    frame(len(rows).to_bytes(8, "big"))
    for row in rows:
        for value in row:
            frame(value.encode())
    return digest.hexdigest()


class SQLiteIntegrityTests(unittest.TestCase):
    def test_compiled_schema_matches_independent_oracle(self) -> None:
        with connection() as db:
            code = (ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs").read_text()
            expected = re.search(
                r'REQUIRED_SCHEMA_ORACLE_SHA256: &str\s*=\s*"([0-9a-f]{64})"', code
            )[1]
            self.assertEqual(schema_oracle(db), expected)
            db.executescript("""
                DROP TRIGGER memory_heads_identity_guard;
                CREATE TRIGGER memory_heads_identity_guard BEFORE UPDATE ON memory_heads
                WHEN 0 BEGIN SELECT RAISE(ABORT, 'disabled'); END;
            """)
            self.assertNotEqual(schema_oracle(db), expected)

    def test_normal_owner_maintenance_keeps_independent_audits_clean(self) -> None:
        with connection() as db:
            source(db, "s1")
            source(db, "s2")
            memory(db, "a")
            memory(db, "a", 2)
            db.execute("INSERT INTO memory_heads VALUES ('a', 1)")
            db.execute("UPDATE memory_heads SET revision = 2 WHERE memory_id = 'a'")
            db.execute("DELETE FROM memory_heads WHERE memory_id = 'a'")
            db.execute("INSERT INTO memory_heads VALUES ('a', 2)")
            db.execute("INSERT INTO memory_citations VALUES ('a', 2, 0, 's1', 1)")
            self.assertEqual(
                db.execute("SELECT * FROM lane_c_scope_witness_audit").fetchall(), []
            )
            self.assertEqual(
                db.execute("SELECT * FROM lane_c_head_validity_audit").fetchall(), []
            )

    def test_non_recursive_replacement_cannot_restore_an_older_frontier(self) -> None:
        with connection() as db:
            memory(db, "a")
            memory(db, "b")
            memory(db, "b", 2)
            db.executemany(
                "INSERT INTO memory_heads VALUES (?, ?)", [("a", 1), ("b", 2)]
            )
            prior = db.execute(
                "SELECT state_revision FROM lane_c_scope_witness"
            ).fetchone()[0]
            db.execute("UPDATE memory_heads SET revision = 1 WHERE memory_id = 'b'")
            for statement in (
                "UPDATE lane_c_scope_witness SET state_revision = ?",
                "INSERT OR REPLACE INTO lane_c_scope_witness SELECT owner_agent_id, scope_kind, workspace_key, ?, memory_revision_count, source_count, citation_count, tombstone_count, knowledge_fact_count, head_count FROM lane_c_scope_witness",
            ):
                with (
                    self.subTest(statement=statement),
                    self.assertRaises(sqlite3.IntegrityError),
                ):
                    db.execute(statement, (prior,))
            self.assertGreater(
                db.execute(
                    "SELECT state_revision FROM lane_c_scope_witness"
                ).fetchone()[0],
                prior,
            )

    def test_identity_updates_cannot_leave_unselected_validity_rows(self) -> None:
        with connection() as db:
            for name in ("a", "b", "c"):
                memory(db, name)
                db.execute("INSERT INTO memory_heads VALUES (?, 1)", (name,))
            db.execute("DELETE FROM memory_heads WHERE memory_id = 'b'")
            for table in ("memory_heads", "lane_c_head_validity"):
                with (
                    self.subTest(table=table),
                    self.assertRaises(sqlite3.IntegrityError),
                ):
                    db.execute(
                        f"UPDATE OR REPLACE {table} SET memory_id = 'b' WHERE memory_id = 'c'"
                    )
            self.assertEqual(
                db.execute("SELECT * FROM lane_c_head_validity_audit").fetchall(), []
            )

    def test_indexed_audit_preserves_all_drift_categories(self) -> None:
        with connection(last=18) as db:
            source(db, "s1")
            source(db, "s2", "1" * 64)
            old = db.execute(
                "SELECT sql FROM sqlite_schema WHERE name = 'lane_c_scope_witness_audit'"
            ).fetchone()[0]
            db.executescript(
                old.replace(
                    "CREATE VIEW lane_c_scope_witness_audit",
                    "CREATE VIEW reference_scope_audit",
                    1,
                )
            )
            migrate(db, first=19)
            for state in ("clean", "counter_drift", "missing", "unexpected"):
                if state == "counter_drift":
                    db.executescript(
                        "DROP TRIGGER lane_c_scope_witness_direct_update_guard;"
                    )
                    db.execute(
                        "UPDATE lane_c_scope_witness SET source_count = source_count + 1, state_revision = state_revision + 1 WHERE workspace_key = ''"
                    )
                elif state == "missing":
                    db.executescript(
                        "DROP TRIGGER lane_c_scope_witness_direct_delete_guard;"
                    )
                    db.execute(
                        "DELETE FROM lane_c_scope_witness WHERE workspace_key = ?",
                        ("1" * 64,),
                    )
                elif state == "unexpected":
                    db.executescript(
                        "DROP TRIGGER lane_c_scope_witness_direct_insert_guard;"
                    )
                    db.execute(
                        "INSERT INTO lane_c_scope_witness VALUES (?, 'workspace_private', ?, 0, 0, 0, 0, 0, 0, 0)",
                        (OWNER, "2" * 64),
                    )
                with self.subTest(state=state):
                    actual = db.execute(
                        "SELECT * FROM lane_c_scope_witness_audit ORDER BY 1, 2, 3, 4"
                    ).fetchall()
                    expected = db.execute(
                        "SELECT * FROM reference_scope_audit ORDER BY 1, 2, 3, 4"
                    ).fetchall()
                    self.assertEqual(actual, expected)
                    if state != "clean":
                        self.assertTrue(actual)

    def test_replace_cannot_move_a_canonical_row_between_scopes(self) -> None:
        for table in ("source_ledger", "memory_revisions"):
            with self.subTest(table=table), connection() as db:
                source(db, "s1")
                source(db, "keep")
                memory(db, "a")
                before = db.execute("SELECT * FROM lane_c_scope_witness").fetchall()
                columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
                projection = [
                    "'workspace_private'"
                    if column == "scope_kind"
                    else "?"
                    if column == "workspace_sha256"
                    else column
                    for column in columns
                ]
                with self.assertRaisesRegex(
                    sqlite3.IntegrityError,
                    f"{table} existing identity cannot be replaced",
                ):
                    db.execute(
                        f"INSERT OR REPLACE INTO {table} SELECT {', '.join(projection)} FROM {table}",
                        ("1" * 64,),
                    )
                self.assertEqual(
                    db.execute("SELECT * FROM lane_c_scope_witness").fetchall(), before
                )
                self.assertEqual(
                    db.execute("SELECT * FROM lane_c_scope_witness_audit").fetchall(),
                    [],
                )

    def test_all_canonical_insert_guards_precede_replace_conflict_resolution(
        self,
    ) -> None:
        with connection() as db:
            canonical_rows(db)
            tables = (
                "cognitive_meta",
                "source_ledger",
                "memory_revisions",
                "memory_citations",
                "kg_revision_fact_sets",
                "kg_revision_entities",
                "kg_revision_relations",
                "kg_projection_generation_receipts",
                "kg_projection_node_entities",
                "kg_nodes",
                "kg_edges",
                "kg_projection_generation_semantics",
                "kg_projection_generation_storage",
                "kg_projection",
            )
            for table in tables:
                before = db.execute(f"SELECT * FROM {table}").fetchall()
                with (
                    self.subTest(table=table),
                    self.assertRaisesRegex(
                        sqlite3.IntegrityError,
                        f"{table} existing identity cannot be replaced",
                    ),
                ):
                    db.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")
                self.assertEqual(
                    db.execute(f"SELECT * FROM {table}").fetchall(), before
                )
            # The pointer previously allowed REPLACE to bypass its generation
            # update guard and restore any earlier complete generation.
            with self.assertRaisesRegex(
                sqlite3.IntegrityError, "kg_projection existing identity"
            ):
                db.execute(
                    "INSERT OR REPLACE INTO kg_projection VALUES ('agent_private', 1)"
                )
            self.assertEqual(
                db.execute("SELECT generation FROM kg_projection").fetchall(), [(2,)]
            )

    def test_actual_owner_insert_if_absent_keeps_replay_and_initialization(
        self,
    ) -> None:
        with connection() as db:
            meta_sql = owner_insert_sql(
                "cognitive_store.rs",
                "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id)",
                "ON CONFLICT(singleton) DO NOTHING",
            )
            self.assertEqual(db.execute(meta_sql, (1, OWNER)).rowcount, 1)
            self.assertEqual(db.execute(meta_sql, (1, OWNER)).rowcount, 0)
            source_sql = owner_insert_sql(
                "cognitive_store.rs",
                "INSERT INTO source_ledger (",
                "ON CONFLICT(source_id, source_revision) DO NOTHING",
            )
            parameters = (
                "s1",
                OWNER,
                "agent_private",
                None,
                "explicit_memory_directive",
                b"a",
                hashlib.sha256(b"a").hexdigest(),
                100,
                100,
                "s1",
            )
            self.assertEqual(db.execute(source_sql, parameters).rowcount, 1)
            # Recorded time can differ on a legitimate replay. The subsequent
            # owner's semantic comparison deliberately excludes recorded time.
            replay = (*parameters[:8], 200, parameters[9])
            self.assertEqual(db.execute(source_sql, replay).rowcount, 0)
            self.assertEqual(
                db.execute(
                    "SELECT recorded_at_unix_seconds FROM source_ledger"
                ).fetchall(),
                [(100,)],
            )
            conflict = (*parameters[:5], b"different", *parameters[6:])
            self.assertEqual(db.execute(source_sql, conflict).rowcount, 0)
            self.assertEqual(
                db.execute("SELECT content FROM source_ledger").fetchall(), [(b"a",)]
            )
            pointer_sql = owner_insert_sql(
                "cognitive_kg_store.rs",
                "INSERT INTO kg_projection (projection_scope, generation)",
                "ON CONFLICT(projection_scope) DO NOTHING",
            )
            self.assertEqual(
                db.execute(pointer_sql, ("agent_private", "agent_private")).rowcount, 1
            )
            self.assertEqual(
                db.execute(pointer_sql, ("agent_private", "agent_private")).rowcount, 0
            )
            self.assertEqual(
                db.execute("SELECT * FROM lane_c_scope_witness_audit").fetchall(), []
            )

    def test_independent_audit_detects_drift_despite_restored_canonical_schema(
        self,
    ) -> None:
        with connection() as db:
            source(db, "s1")
            before = schema_oracle(db)
            guard = db.execute(
                "SELECT sql FROM sqlite_schema WHERE name = 'lane_c_scope_witness_direct_update_guard'"
            ).fetchone()[0]
            db.execute("DROP TRIGGER lane_c_scope_witness_direct_update_guard")
            db.execute(
                "UPDATE lane_c_scope_witness SET source_count = source_count + 1, state_revision = state_revision + 1"
            )
            db.execute(guard)
            self.assertEqual(schema_oracle(db), before)
            self.assertEqual(db.execute("PRAGMA quick_check(1)").fetchall(), [("ok",)])
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(
                db.execute(
                    "SELECT EXISTS (SELECT 1 FROM lane_c_scope_witness_audit UNION ALL SELECT 1 FROM lane_c_head_validity_audit)"
                ).fetchone(),
                (1,),
            )

    def test_cross_scope_append_avoids_global_history_scan(self) -> None:
        measurements = []
        for version in (18, 19):
            with connection(last=15) as db:
                for index in range(2_000):
                    source(db, f"s{index}", f"{index % 20:064x}")
                migrate(db, first=16, last=version)
                steps = [0]

                def progress(counter: list[int] = steps) -> int:
                    counter[0] += 100
                    return 0

                db.set_progress_handler(progress, 100)
                source(db, "one-target-append", "0" * 64)
                db.set_progress_handler(None, 0)
                measurements.append(steps[0])
        # A broad ratio avoids binding the test to SQLite instruction numbers.
        self.assertGreater(measurements[0], measurements[1] * 5)


if __name__ == "__main__":
    unittest.main()
