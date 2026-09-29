#!/usr/bin/env python3
"""Extend the cognitive schema oracle and reopen validation for KG delta receipts."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import struct
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "codex-rs/hepta-memory/src/cognitive_store.rs"
MIGRATIONS = ROOT / "codex-rs/hepta-memory/migrations"


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one exact predecessor, found {count}")
    return text.replace(old, new, 1)


def patch_required_objects(text: str) -> str:
    if '"kg_projection_generation_kernel_deltas", "table"' in text:
        return text
    anchor = """    ("kg_projection_generation_storage_counts_match", "trigger"),
    ("kg_revision_entity_fts", "table"),
"""
    replacement = """    ("kg_projection_generation_storage_counts_match", "trigger"),
    ("kg_projection_generation_transitions", "table"),
    (
        "kg_projection_generation_transitions_no_update",
        "trigger",
    ),
    (
        "kg_projection_generation_transitions_no_delete",
        "trigger",
    ),
    (
        "kg_projection_generation_transitions_predecessor",
        "index",
    ),
    (
        "kg_projection_generation_storage_trigger_payload_budget",
        "trigger",
    ),
    (
        "kg_projection_generation_storage_transition_receipt",
        "trigger",
    ),
    ("kg_projection_current_transition_on_update", "trigger"),
    ("kg_projection_generation_kernel_deltas", "table"),
    (
        "kg_projection_generation_kernel_deltas_no_update",
        "trigger",
    ),
    (
        "kg_projection_generation_kernel_deltas_no_delete",
        "trigger",
    ),
    (
        "kg_projection_generation_kernel_deltas_predecessor",
        "index",
    ),
    ("kg_projection_current_kernel_delta_on_update", "trigger"),
    ("kg_revision_entity_fts", "table"),
"""
    return replace_once(text, anchor, replacement, "required KG receipt objects")


def patch_current_pointer_validation(text: str) -> str:
    if "kernel delta digest does not match" in text:
        return text
    old = """    let invalid_current_pointers: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_projection p
         LEFT JOIN kg_projection_generation_receipts r
           ON r.projection_scope = p.projection_scope
          AND r.generation = p.generation
         WHERE p.generation <= 0 OR r.projection_scope IS NULL",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_current_pointers != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "KG current projection pointer has no complete immutable receipt".to_string(),
        ));
    }
"""
    new = """    let invalid_current_pointers: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_projection p
         LEFT JOIN kg_projection_generation_receipts r
           ON r.projection_scope = p.projection_scope
          AND r.generation = p.generation
         LEFT JOIN kg_projection_generation_semantics s
           ON s.projection_scope = p.projection_scope
          AND s.generation = p.generation
         LEFT JOIN kg_projection_generation_storage st
           ON st.projection_scope = p.projection_scope
          AND st.generation = p.generation
         LEFT JOIN kg_projection_generation_transitions t
           ON t.projection_scope = p.projection_scope
          AND t.generation = p.generation
         LEFT JOIN kg_projection_generation_kernel_deltas d
           ON d.projection_scope = p.projection_scope
          AND d.generation = p.generation
         LEFT JOIN kg_projection_generation_semantics predecessor
           ON predecessor.projection_scope = p.projection_scope
          AND predecessor.generation = p.generation - 1
         WHERE p.generation <= 0
            OR r.projection_scope IS NULL
            OR s.projection_scope IS NULL
            OR st.projection_scope IS NULL
            OR (t.projection_scope IS NOT NULL AND
                t.generation_sha256 != s.generation_sha256)
            OR (t.projection_scope IS NOT NULL AND p.generation > 1 AND (
                d.projection_scope IS NULL OR
                d.generation_sha256 != s.generation_sha256 OR
                (predecessor.projection_scope IS NOT NULL AND
                 d.predecessor_generation_sha256 != predecessor.generation_sha256)
            ))",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if invalid_current_pointers != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "KG current projection pointer or transition/kernel delta digest does not match its immutable receipts"
                .to_string(),
        ));
    }
"""
    return replace_once(text, old, new, "current generation receipt validation")


def apply_migrations(connection: sqlite3.Connection) -> None:
    migration_paths = sorted(
        MIGRATIONS.glob("*.sql"),
        key=lambda path: int(path.name.split("_", 1)[0]),
    )
    if not migration_paths:
        raise PatchError("no cognitive migrations found")
    for path in migration_paths:
        try:
            connection.executescript(path.read_text(encoding="utf-8"))
        except sqlite3.DatabaseError as exc:
            raise PatchError(f"migration {path.name} failed in schema oracle fixture: {exc}") from exc


def required_objects(text: str) -> list[tuple[str, str]]:
    match = re.search(
        r"const REQUIRED_SCHEMA_OBJECTS:.*?=\s*&\[(.*?)\n\];",
        text,
        flags=re.S,
    )
    if match is None:
        raise PatchError("cannot locate REQUIRED_SCHEMA_OBJECTS")
    pairs = re.findall(
        r"\(\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"\s*\)",
        match.group(1),
        flags=re.S,
    )
    if not pairs:
        raise PatchError("required schema object inventory is empty")
    if len({name for name, _ in pairs}) != len(pairs):
        raise PatchError("required schema object inventory contains duplicates")
    return pairs


def frame(digest: "hashlib._Hash", value: bytes) -> None:
    digest.update(struct.pack(">Q", len(value)))
    digest.update(value)


def compute_oracle(text: str) -> str:
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "schema.sqlite3"
        connection = sqlite3.connect(database)
        try:
            apply_migrations(connection)
            definitions: list[tuple[str, str, str]] = []
            for name, expected_type in required_objects(text):
                row = connection.execute(
                    "SELECT type, sql FROM sqlite_schema WHERE name = ?",
                    (name,),
                ).fetchone()
                if row is None:
                    raise PatchError(f"required schema object was not created: {name}")
                object_type, sql = row
                if object_type != expected_type or not sql:
                    raise PatchError(
                        f"required schema object has wrong definition class: {name}"
                    )
                definitions.append((name, object_type, sql))
        finally:
            connection.close()

    definitions.sort(key=lambda value: value[0])
    digest = hashlib.sha256()
    frame(digest, b"hepta:cognitive:required-schema-oracle:v1")
    frame(digest, struct.pack(">Q", len(definitions)))
    for name, object_type, sql in definitions:
        frame(digest, name.encode("utf-8"))
        frame(digest, object_type.encode("utf-8"))
        frame(digest, sql.encode("utf-8"))
    return digest.hexdigest()


def bind_oracle(text: str, oracle: str) -> str:
    pattern = re.compile(
        r'(const REQUIRED_SCHEMA_ORACLE_SHA256: &str =\s*\n\s*\")[0-9a-f]{64}(\";)',
        flags=re.S,
    )
    updated, count = pattern.subn(rf"\g<1>{oracle}\g<2>", text, count=1)
    if count != 1:
        raise PatchError("cannot bind REQUIRED_SCHEMA_ORACLE_SHA256")
    return updated


def main() -> int:
    text = STORE.read_text(encoding="utf-8")
    text = patch_required_objects(text)
    text = patch_current_pointer_validation(text)
    oracle = compute_oracle(text)
    text = bind_oracle(text, oracle)
    STORE.write_text(text, encoding="utf-8")
    print(f"PASS_APPLY_KG_SCHEMA_ORACLE {oracle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
