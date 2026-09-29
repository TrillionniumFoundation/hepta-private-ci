#!/usr/bin/env python3
"""Repair exact automation.taskflow qualification blockers on the reviewed source head.

This is a one-shot developer carrier. Every edit requires an exact source anchor;
the convergence workflow removes this file before publishing the final candidate.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one exact anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(relative: str, old: str, new: str, expected: int) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{relative}: expected {expected} exact anchors, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# The legacy fixture must remove the schema-21 view before dropping the table it
# references. SQLite otherwise rejects the later ALTER TABLE before migration is
# even exercised.
replace_once(
    "codex-rs/hepta-automation/tests/automation.rs",
    '        "DROP TABLE IF EXISTS automation_occurrence_lifecycle",\n',
    '        "DROP VIEW IF EXISTS automation_recovery_frontier",\n'
    '        "DROP TABLE IF EXISTS automation_occurrence_lifecycle",\n',
)

# WaitJoin is a non-decision node and therefore has one deterministic successor.
# The recovery fixture observes a Ready result; an unused failure edge made the
# admitted candidate invalid before recovery semantics were tested.
replace_once(
    "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
    '            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),\n'
    '            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),\n',
    '            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),\n',
)
replace_once(
    "codex-rs/hepta-automation/tests/durable_neural_circuit_recovery.rs",
    '            CircuitEdgeV1::new("wait", "success"),\n'
    '            CircuitEdgeV1::new("wait", "failure"),\n',
    '            CircuitEdgeV1::new("wait", "success"),\n',
)

# AuthBus is a real Agentd dependency of the all-features TaskFlow qualification.
# Route its durable owner and transient schema-reference pools through the
# canonical codex-state SQLite shim instead of weakening strict lint or adding an
# allow. The reference lives in a private temporary directory beside the owner,
# contains no authority data, and is removed only after its pool is closed.
replace_once(
    "codex-rs/hepta-authbus/Cargo.toml",
    "[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }\n",
    "[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }\n"
    "codex-state = { workspace = true }\n"
    "codex-utils-absolute-path = { workspace = true }\n"
    "tempfile = { workspace = true }\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/authority_store.rs",
    "use std::path::Path;\nuse std::time::Duration;\n\n"
    "use codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;\n",
    "use std::path::Path;\n\n"
    "use codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;\n"
    "use codex_state::SqliteConfig;\n"
    "use codex_utils_absolute_path::AbsolutePathBuf;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/authority_store.rs",
    "use sqlx::sqlite::SqliteConnectOptions;\n"
    "use sqlx::sqlite::SqliteJournalMode;\n"
    "use sqlx::sqlite::SqlitePoolOptions;\n"
    "use sqlx::sqlite::SqliteSynchronous;\n",
    "",
)
replace_once(
    "codex-rs/hepta-authbus/src/authority_store.rs",
    "        let options = SqliteConnectOptions::new()\n"
    "            .filename(path)\n"
    "            .create_if_missing(true)\n"
    "            .journal_mode(SqliteJournalMode::Wal)\n"
    "            .synchronous(SqliteSynchronous::Full)\n"
    "            .foreign_keys(true)\n"
    "            .busy_timeout(Duration::from_secs(5));\n"
    "        let pool = SqlitePoolOptions::new()\n"
    "            .max_connections(5)\n"
    "            .connect_with(options)\n"
    "            .await\n"
    "            .map_err(storage)?;\n",
    "        let parent = path.parent().ok_or(AuthBusAuthorityError::InvalidInput(\n"
    "            \"authority database path has no parent\",\n"
    "        ))?;\n"
    "        let sqlite_home = AbsolutePathBuf::try_from(parent.to_path_buf()).map_err(|_| {\n"
    "            AuthBusAuthorityError::InvalidInput(\n"
    "                \"authority database parent must be an absolute path\",\n"
    "            )\n"
    "        })?;\n"
    "        let sqlite = SqliteConfig::from_sqlite_home(sqlite_home);\n"
    "        let pool = sqlite\n"
    "            .open_durable_evidence_pool(path)\n"
    "            .await\n"
    "            .map_err(storage)?;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/authority_store.rs",
    "        if let Err(error) = crate::authority_schema::verify_schema(&pool, &MIGRATOR).await {\n"
    "            pool.close().await;\n"
    "            return Err(error);\n"
    "        }\n",
    "        let reference_dir = tempfile::tempdir_in(parent).map_err(storage)?;\n"
    "        let reference_path = reference_dir\n"
    "            .path()\n"
    "            .join(\"compiled-authority-schema.sqlite3\");\n"
    "        if let Err(error) = crate::authority_schema::verify_schema(\n"
    "            &pool,\n"
    "            &MIGRATOR,\n"
    "            &sqlite,\n"
    "            &reference_path,\n"
    "        )\n"
    "        .await\n"
    "        {\n"
    "            pool.close().await;\n"
    "            return Err(error);\n"
    "        }\n"
    "        drop(reference_dir);\n",
)

replace_once(
    "codex-rs/hepta-authbus/src/authority_schema.rs",
    "use sqlx::SqlitePool;\nuse sqlx::migrate::Migrator;\n"
    "use sqlx::sqlite::SqlitePoolOptions;\n",
    "use std::path::Path;\n\n"
    "use codex_state::SqliteConfig;\n"
    "use sqlx::SqlitePool;\n"
    "use sqlx::migrate::Migrator;\n",
)
replace_once(
    "codex-rs/hepta-authbus/src/authority_schema.rs",
    "pub(crate) async fn verify_schema(\n"
    "    pool: &SqlitePool,\n"
    "    migrator: &Migrator,\n"
    ") -> Result<(), AuthBusAuthorityError> {\n"
    "    let reference = SqlitePoolOptions::new()\n"
    "        .max_connections(1)\n"
    "        .connect(\"sqlite::memory:\")\n"
    "        .await\n"
    "        .map_err(storage)?;\n",
    "pub(crate) async fn verify_schema(\n"
    "    pool: &SqlitePool,\n"
    "    migrator: &Migrator,\n"
    "    sqlite: &SqliteConfig,\n"
    "    reference_path: &Path,\n"
    ") -> Result<(), AuthBusAuthorityError> {\n"
    "    let reference = sqlite\n"
    "        .open_read_write_pool(reference_path)\n"
    "        .await\n"
    "        .map_err(storage)?;\n",
)

for relative in [
    "codex-rs/hepta-authbus/src/authority_store.rs",
    "codex-rs/hepta-authbus/src/quota_store.rs",
    "codex-rs/hepta-authbus/src/trust_store.rs",
]:
    replace_all(
        relative,
        ".is_some_and(|database| database.is_unique_violation())",
        ".is_some_and(sqlx::error::DatabaseError::is_unique_violation)",
        1,
    )

# sqlx::migrate! expands at compile time. Bazel must place both immutable
# migration directories in the hepta-operations sandbox just as Cargo does.
replace_once(
    "codex-rs/hepta-operations/BUILD.bazel",
    'codex_rust_crate(\n    name = "hepta-operations",\n'
    '    crate_name = "codex_hepta_operations",\n)\n',
    'codex_rust_crate(\n    name = "hepta-operations",\n'
    '    compile_data = glob([\n'
    '        "destination_migrations/**",\n'
    '        "migrations/**",\n'
    '    ]),\n'
    '    crate_name = "codex_hepta_operations",\n)\n',
)

print("automation.taskflow CI remediation applied")
