#!/usr/bin/env python3
"""Execute original migration/fixture SQL; this is not a Rust/API test runner."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3


def literals(text):
    return re.findall(r'"((?:[^"\\]|\\.)*)"', text, re.S)


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def sql(text):
    return [s for s in literals(text) if re.match(r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|WITH)\b", s)]


def scalar(db, query, args=()):
    return db.execute(query, args).fetchone()[0]


def migrations(root, crate):
    return sorted((root / "codex-rs" / crate / "migrations").glob("*.sql"))


def apply_migration(db, path):
    db.executescript(path.read_text())
    db.execute("INSERT INTO _sqlx_migrations VALUES (?)", (int(path.name[:4]),))


def database():
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    # SQLx bookkeeping is represented only by version IDs. This probe does not
    # claim to exercise SQLx checksums, pooling, async APIs, or Rust types.
    db.execute("CREATE TABLE _sqlx_migrations (version INTEGER PRIMARY KEY)")
    return db


def automation(baseline, candidate):
    path = "codex-rs/hepta-automation/tests/automation.rs"
    ms = migrations(baseline, "hepta-automation")
    assert [int(p.name[:4]) for p in ms] == list(range(1, 20))
    results = {}
    for label, root in [("baseline", baseline), ("candidate", candidate)]:
        db = database()
        for m in ms:
            apply_migration(db, m)
        db.execute("INSERT INTO automation_meta VALUES (1,19,'owner')")
        db.execute("INSERT INTO automation_tasks VALUES ('task','owner','thread','prompt','once',NULL,'enabled',100,1,0,0)")
        before = db.execute("SELECT * FROM automation_tasks").fetchall()
        db.commit()
        queries = sql(section((root / path).read_text(), "let mut rewind =", "rewind.commit()"))
        db.execute("BEGIN")
        try:
            for query in queries:
                db.execute(query)
            db.commit()
        except sqlite3.Error as error:
            db.rollback()
            assert label == "baseline"
            assert str(error) == "error in trigger automation_timer_lifecycle_drain: no such table: main.automation_dispatch_outcomes"
            assert query == "ALTER TABLE automation_runs DROP COLUMN schedule_revision"
            assert scalar(db, "SELECT schema_version FROM automation_meta") == 19
            results[label] = {"error": str(error), "statement": query, "transaction_rolled_back": True}
            continue
        assert label == "candidate"
        objects = db.execute("SELECT type,name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        v1 = database()
        apply_migration(v1, ms[0])
        expected = v1.execute("SELECT type,name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        assert objects == expected
        for table in ["automation_meta", "automation_tasks", "automation_runs"]:
            assert db.execute(f"PRAGMA table_info({table})").fetchall() == v1.execute(f"PRAGMA table_info({table})").fetchall()
        assert scalar(db, "SELECT schema_version FROM automation_meta") == 1
        assert db.execute("SELECT version FROM _sqlx_migrations").fetchall() == [(1,)]
        for m in ms[1:]:
            apply_migration(db, m)
        assert scalar(db, "SELECT schema_version FROM automation_meta") == 19
        assert db.execute("SELECT * FROM automation_tasks").fetchall() == before
        db.commit()
        try:
            db.execute("UPDATE automation_meta SET schema_version = 99 WHERE singleton=1")
        except sqlite3.IntegrityError as error:
            assert str(error) == "automation owner metadata is immutable"
        else:
            raise AssertionError("restored metadata guard did not reject mutation")
        results[label] = {"rewind_statements": len(queries), "v1_schema_objects": objects, "replayed_migrations": list(range(2, 20)), "final_schema": 19, "task_row_preserved": True, "metadata_immutable": True}
    return results


def memory(baseline, candidate):
    path = "codex-rs/hepta-memory/src/cognitive_store_tests.rs"
    ms = migrations(baseline, "hepta-memory")
    assert [int(p.name[:4]) for p in ms] == list(range(1, 16))
    db = database()
    for m in ms[:2]:
        apply_migration(db, m)
    source = (baseline / path).read_text()
    queries = [q for q in sql(section(source, "async fn v2_fixture_migrates_forward_", "pool.close().await;")) if q.startswith("INSERT")]
    assert len(queries) == 8
    owner = "019153a4-3088-7000-a56a-9b1964f75054"
    source_id, memory_id, content = "source:v1:" + "1" * 64, "memory:v1:" + "2" * 64, "legacy cited memory"
    digest = hashlib.sha256(content.encode()).hexdigest()
    binds = [(source_id, owner, content.encode(), digest), (memory_id, owner, content, digest), (memory_id, source_id), (memory_id,), (memory_id, content), (), (memory_id, source_id), ()]
    for query, args in zip(queries, binds, strict=True):
        db.execute(query, args)
    for m in ms[2:]:
        apply_migration(db, m)
    actual = scalar(db, "SELECT group_concat(version, ',') FROM _sqlx_migrations ORDER BY version")
    expected = {}
    for label, root in [("baseline", baseline), ("candidate", candidate)]:
        values = [x for x in literals((root / path).read_text()) if re.fullmatch(r"1,2,3,4,5,6,7,8,9,10,11,12,13,14(?:,15)?", x)]
        assert len(values) == 1
        expected[label] = values[0]
    assert actual != expected["baseline"] and actual == expected["candidate"]
    counts = {t: scalar(db, f"SELECT COUNT(*) FROM {t}") for t in ["memory_revisions", "memory_citations", "memory_heads", "kg_projection", "kg_nodes", "kg_edges", "kg_entity_fts", "shared_experience_use_events"]}
    assert counts == {"memory_revisions": 1, "memory_citations": 1, "memory_heads": 1, "kg_projection": 0, "kg_nodes": 0, "kg_edges": 0, "kg_entity_fts": 0, "shared_experience_use_events": 0}
    header = db.execute("SELECT extractor_contract,fact_set_sha256,source_id,source_revision,entity_count,relation_count FROM kg_revision_fact_sets").fetchone()
    assert header == ("legacy_pre_g3_empty_v1", "6eb8599ab837d22123cda62453adb0c22a20fb1986308de666507188e79297af", source_id, 1, 0, 0)
    return {"observed_versions": actual, "expected_versions": expected, "preserved_and_revoked_counts": counts, "legacy_header_preserved": True}


def outbox(baseline, candidate):
    prefix = baseline / "codex-rs/hepta-evidence"
    product = (prefix / "src/authbus_outbox.rs").read_text()
    record = (prefix / "src/authbus_outbox_record.rs").read_text()
    worker = (prefix / "src/authbus_outbox_worker.rs").read_text()
    constant = lambda name: int(re.search(rf"const {name}: i64 = ([\d_]+);", record)[1].replace("_", ""))
    max_rows, max_issuer = constant("AUTHBUS_OUTBOX_MAX_ROWS"), constant("AUTHBUS_OUTBOX_MAX_ACTIVE_PER_ISSUER")
    insert = next(q for q in sql(product) if q.startswith("INSERT INTO authbus_outbox"))
    active = next(q for q in sql(product) if q.startswith("SELECT COUNT(*) FROM authbus_outbox\n"))
    maintain = sql(section(product, "pub(crate) async fn maintain(", "#[cfg(test)]"))
    assert len(maintain) == 3
    claim = next(q for q in sql(worker) if q.startswith("UPDATE authbus_outbox SET state = 'leased'"))
    ack = next(q for q in sql(worker) if q.startswith("UPDATE authbus_outbox SET state = 'acked'"))
    results = {}
    for label, root in [("baseline", baseline), ("candidate", candidate)]:
        db = database()
        db.executescript((prefix / "migrations/0010_authbus_outbox.sql").read_text())
        delivery_id = bytes([1]) * 32
        db.execute(insert, (delivery_id, "issuer:queue", (1).to_bytes(8, "big"), "message:1", "subject:queue", bytes(32), bytes(32), (1).to_bytes(8, "big"), (2**64-1).to_bytes(8, "big"), bytes(64), b"payload", 100, 100, 100))
        test = section((root / "codex-rs/hepta-evidence/src/authbus_outbox_tests.rs").read_text(), "async fn bounded_capacity_", "#[tokio::test]")
        fill = next(q for q in sql(test) if q.startswith("WITH RECURSIVE"))
        db.execute(fill, (delivery_id,))
        total = scalar(db, "SELECT COUNT(*) FROM authbus_outbox")
        largest = scalar(db, "SELECT MAX(n) FROM (SELECT COUNT(*) n FROM authbus_outbox GROUP BY issuer_id)")
        assert total == max_rows
        assert (largest <= max_issuer) == (label == "candidate")
        try:
            db.execute("DELETE FROM authbus_outbox WHERE delivery_id=?", (delivery_id,))
        except sqlite3.IntegrityError as error:
            assert str(error) == "active AuthBus messages cannot be pruned"
        else:
            raise AssertionError("active row deletion must be rejected")
        db.execute(claim, ("worker:queue", 60_100, 100, delivery_id))
        db.execute(ack, (101, 101, bytes([2])*32, delivery_id))
        for query, args in zip(maintain, [(102, 102, (102).to_bytes(8, "big")), (102-constant("TERMINAL_RETENTION_MS"), constant("TERMINAL_RETAINED_ROWS")), (max_rows-1,)], strict=True):
            db.execute(query, args)
        after = scalar(db, "SELECT COUNT(*) FROM authbus_outbox")
        issuer_count = scalar(db, active, ("issuer:queue",))
        assert after == max_rows-1
        assert scalar(db, "SELECT COUNT(*) FROM authbus_outbox WHERE delivery_id=?", (delivery_id,)) == 0
        assert (issuer_count >= max_issuer) == (label == "baseline")
        results[label] = {"initial_rows": total, "max_active_per_fixture_issuer": largest, "after_terminal_pruning_rows": after, "incoming_issuer_active_after_ack": issuer_count, "per_issuer_guard_rejects": issuer_count >= max_issuer, "global_guard_allows_one_slot": after < max_rows, "active_delete_rejected": True, "terminal_row_pruned": True}
    return {"limits": {"rows": max_rows, "active_per_issuer": max_issuer}, "runs": results, "scope": "Executes exact fixture, claim, ack and maintenance SQL. Does not execute Rust authentication, replay registry, async transactions, or enqueue APIs."}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = {"sqlite_version": sqlite3.sqlite_version, "scope": "Original-source SQL integration probes, not native Rust suites", "automation": automation(args.baseline, args.candidate), "memory": memory(args.baseline, args.candidate), "outbox": outbox(args.baseline, args.candidate)}
    result["sources_sha256"] = {str(path.relative_to(args.baseline)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(args.baseline.rglob("*")) if path.is_file()}
    result["candidate_sha256"] = {str(path.relative_to(args.candidate)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(args.candidate.rglob("*")) if path.is_file()}
    args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"passed": True, "sqlite_version": sqlite3.sqlite_version, "output": str(args.output)}))


if __name__ == "__main__":
    main()
