"""Exercise the actual v20/v21 migrations and Rust SQL using Python's SQLite engine.

This is SQL/protocol regression evidence, not SQLx or native Agentd execution.
Native owner/reopen tests live in hepta-automation/tests/scheduler_review_regressions.rs.
"""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "codex-rs/hepta-automation/migrations/0020_recovery_sweeps.sql"
SOURCE = ROOT / "codex-rs/hepta-automation/src/recovery_sweeps.rs"


def sql(name: str) -> str:
    match = re.search(rf'const {re.escape(name)}: &str = "([^"]+)";', SOURCE.read_text(), re.S)
    if not match:
        raise AssertionError(f"missing actual source SQL: {name}")
    return match[1]


def task_id(number: int) -> str:
    return f"019153a4-3088-7000-a56a-{number:012x}"


def prepare(db: sqlite3.Connection) -> None:
    # Minimal predecessor shape for testing this additive migration, not a
    # claim to reconstruct historical SQLx migrations or the full owner store.
    db.executescript("""
        CREATE TABLE automation_meta(singleton INTEGER PRIMARY KEY, schema_version INTEGER);
        INSERT INTO automation_meta VALUES(1, 19);
        CREATE TRIGGER automation_meta_no_update BEFORE UPDATE ON automation_meta
        BEGIN SELECT RAISE(ABORT, 'immutable'); END;
        CREATE TABLE automation_tasks(task_id TEXT PRIMARY KEY, owner_agent_id TEXT);
        CREATE TABLE automation_runs(task_id TEXT, occurrence INTEGER,
                                     PRIMARY KEY(task_id, occurrence));
        CREATE TABLE automation_dispatch_outcomes(task_id TEXT, occurrence INTEGER,
                                                 outcome TEXT, PRIMARY KEY(task_id, occurrence));
        CREATE TABLE automation_occurrence_lifecycle(owner_agent_id TEXT, task_id TEXT,
            occurrence INTEGER, state TEXT, updated_at_ms INTEGER,
            PRIMARY KEY(task_id, occurrence));
    """)
    db.executescript(MIGRATION.read_text())
    db.executescript(MIGRATION.with_name("0021_recovery_frontier_indexes.sql").read_text())


def add(db: sqlite3.Connection, number: int, lane: str = "terminal", owner: str = "agent") -> None:
    key = task_id(number)
    db.execute("INSERT INTO automation_tasks VALUES(?, ?)", (key, owner))
    if lane == "terminal":
        db.execute("INSERT INTO automation_occurrence_lifecycle VALUES(?,?,1,'running',100)",
                   (owner, key))
    else:
        db.execute("INSERT INTO automation_runs VALUES(?,1)", (key,))
        db.execute("INSERT INTO automation_dispatch_outcomes VALUES(?,1,'uncertain')", (key,))


def select(db: sqlite3.Connection, lane: str, limit: int, owner: str = "agent") -> list[tuple[str, int]]:
    """Small reference driver of the exact SELECT/CAS statements in Rust."""
    row = db.execute("SELECT sweep_generation, after_task_id, after_occurrence, upper_task_id, "
                     "upper_occurrence FROM automation_recovery_sweeps WHERE lane=?", (lane,)).fetchone()
    if row is None:
        raise ValueError("missing permanent sweep")
    generation, after, occurrence, upper, upper_occurrence = row
    if limit == 0:
        return []
    for _ in range(2):
        if upper:
            keys = db.execute(sql("SELECT_WINDOW"),
                              (owner, lane, after, occurrence, upper, upper_occurrence, limit)).fetchall()
            if keys:
                after, occurrence = keys[-1]
                changed = db.execute(sql("SAVE_SWEEP"),
                    (generation, after, occurrence, upper, upper_occurrence, lane, *row)).rowcount
                if changed != 1:
                    raise ValueError("CAS conflict")
                return keys
        high = db.execute(sql("SELECT_UPPER"), (owner, lane)).fetchone()
        if high is None:
            return []
        generation, after, occurrence = row[0] + 1, "", 0
        upper, upper_occurrence = high
    raise ValueError("inconsistent frozen window")


class RecoverySqlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "owner.sqlite3"
        self.db = sqlite3.connect(self.path)
        prepare(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_ninth_running_key_is_reached_without_changing_business_timestamps(self) -> None:
        for n in range(9):
            add(self.db, n)
        first = select(self.db, "terminal", 8)
        second = select(self.db, "terminal", 8)
        self.assertEqual(first, [(task_id(n), 1) for n in range(8)])
        self.assertEqual(second, [(task_id(8), 1)])
        self.assertEqual(self.db.execute("SELECT DISTINCT state,updated_at_ms "
            "FROM automation_occurrence_lifecycle").fetchall(), [("running", 100)])

    def test_cursor_survives_connection_restart(self) -> None:
        for n in range(9):
            add(self.db, n)
        select(self.db, "terminal", 8)
        self.db.commit()
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.assertEqual(select(self.db, "terminal", 8), [(task_id(8), 1)])

    def test_frozen_upper_does_not_chase_continuous_arrivals(self) -> None:
        for n in range(25):
            add(self.db, n)
        seen = select(self.db, "terminal", 4)
        for cycle in range(6):
            for extra in range(10):
                add(self.db, 1000 + cycle * 10 + extra)
            seen += select(self.db, "terminal", 4)
        self.assertEqual(seen, [(task_id(n), 1) for n in range(25)])
        self.assertEqual(self.db.execute("SELECT sweep_generation FROM automation_recovery_sweeps "
            "WHERE lane='terminal'").fetchone(), (1,))
        self.assertEqual(select(self.db, "terminal", 4), [(task_id(n), 1) for n in range(4)])

    def test_failure_rollback_does_not_consume_selected_progress(self) -> None:
        for n in range(12):
            add(self.db, n)
        self.db.commit()
        self.db.execute("BEGIN IMMEDIATE")
        expected = select(self.db, "terminal", 8)
        self.db.rollback()
        self.assertEqual(select(self.db, "terminal", 8), expected)

    def test_pending_and_unknown_cursors_are_independent(self) -> None:
        for n in range(30):
            add(self.db, n, "unknown")
            add(self.db, n + 100, "terminal")
        terminal_seen = []
        for _ in range(30):
            unknown = select(self.db, "unknown", 7)
            terminal_seen += select(self.db, "terminal", 1)
            self.assertLessEqual(len(unknown), 7)
        self.assertEqual(terminal_seen, [(task_id(n + 100), 1) for n in range(30)])

    def test_resolved_rows_disappear_without_becoming_absence_proofs(self) -> None:
        for n in range(12):
            add(self.db, n)
        select(self.db, "terminal", 8)
        self.db.execute("UPDATE automation_occurrence_lifecycle SET state='succeeded' WHERE task_id=?",
                        (task_id(8),))
        self.assertEqual(select(self.db, "terminal", 8), [(task_id(n), 1) for n in range(9, 12)])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM automation_dispatch_outcomes").fetchone(), (0,))

    def test_cursor_cannot_rewind_in_same_generation(self) -> None:
        for n in range(12):
            add(self.db, n)
        select(self.db, "terminal", 8)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE automation_recovery_sweeps SET after_task_id='',after_occurrence=0 "
                            "WHERE lane='terminal'")

    def test_frozen_upper_and_generation_are_guarded(self) -> None:
        for n in range(12):
            add(self.db, n)
        select(self.db, "terminal", 8)
        for statement in [
            "UPDATE automation_recovery_sweeps SET upper_occurrence=2 WHERE lane='terminal'",
            "UPDATE automation_recovery_sweeps SET sweep_generation=0 WHERE lane='terminal'",
            "UPDATE automation_recovery_sweeps SET sweep_generation=9 WHERE lane='terminal'",
            "DELETE FROM automation_recovery_sweeps WHERE lane='terminal'",
        ]:
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(statement)

    def test_empty_frontier_later_accepts_work(self) -> None:
        self.assertEqual(select(self.db, "terminal", 8), [])
        add(self.db, 3)
        self.assertEqual(select(self.db, "terminal", 8), [(task_id(3), 1)])

    def test_foreign_owner_keys_are_not_selected(self) -> None:
        for n in range(10):
            add(self.db, n, owner="another-agent")
        add(self.db, 100)
        self.assertEqual(select(self.db, "terminal", 8), [(task_id(100), 1)])

    def test_long_backlog_has_bounded_pages_and_constant_polling_state(self) -> None:
        for n in range(5000):
            add(self.db, n)
        seen = []
        for _ in range(625):
            page = select(self.db, "terminal", 8)
            self.assertEqual(len(page), 8)
            seen += page
        self.assertEqual(seen, [(task_id(n), 1) for n in range(5000)])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM automation_recovery_sweeps").fetchone(), (2,))
        self.assertEqual(select(self.db, "terminal", 8), [(task_id(n), 1) for n in range(8)])

    def test_unknown_upper_uses_the_partial_identity_index_without_history_sort(self) -> None:
        plan = self.db.execute("EXPLAIN QUERY PLAN " + sql("SELECT_UPPER"),
                               ("agent", "unknown")).fetchall()
        details = "\n".join(row[3] for row in plan)
        self.assertIn("automation_dispatch_recovery_identity", details)
        self.assertNotIn("TEMP B-TREE", details)

    def test_sparse_unknowns_do_not_scan_ten_thousand_settled_dispatches(self) -> None:
        for n in range(10000):
            add(self.db, n, "unknown")
        self.db.execute("UPDATE automation_dispatch_outcomes SET outcome='submitted' WHERE task_id < ?",
                        (task_id(9997),))
        instructions = 0
        def progress() -> int:
            nonlocal instructions
            instructions += 100
            return 0
        self.db.set_progress_handler(progress, 100)
        try:
            selected = select(self.db, "unknown", 8)
        finally:
            self.db.set_progress_handler(None, 0)
        self.assertEqual(selected, [(task_id(n), 1) for n in range(9997, 10000)])
        self.assertLess(instructions, 3000)

    def test_additive_schema_metadata_remains_immutable(self) -> None:
        self.assertEqual(self.db.execute("SELECT schema_version FROM automation_meta").fetchone(), (21,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE automation_meta SET schema_version=19")


if __name__ == "__main__":
    unittest.main()
