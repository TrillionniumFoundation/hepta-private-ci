use pretty_assertions::assert_eq;
use sqlx::Connection;
use sqlx::Row;
use sqlx::SqlitePool;
use tempfile::TempDir;

use super::super::super::CognitiveStore;
use super::super::super::CognitiveStoreError;
use super::super::super::MIGRATOR;
use super::super::super::open_v2_test_pool;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

#[derive(Debug, PartialEq, Eq)]
struct DatabaseImage {
    schema: Vec<(String, String, String, Option<String>)>,
    tables: Vec<(String, Vec<Vec<String>>)>,
}

async fn image(pool: &SqlitePool) -> DatabaseImage {
    let schema: Vec<(String, String, String, Option<String>)> =
        sqlx::query_as("SELECT name, type, tbl_name, sql FROM sqlite_schema ORDER BY name")
            .fetch_all(pool)
            .await
            .expect("complete compiled fixture schema");
    let mut tables = Vec::new();
    for (table, kind, _, _) in &schema {
        if kind != "table" {
            continue;
        }
        let columns: Vec<String> =
            sqlx::query_scalar("SELECT name FROM pragma_table_info(?) ORDER BY cid")
                .bind(table)
                .fetch_all(pool)
                .await
                .expect("compiled fixture columns");
        let selection = columns
            .iter()
            .map(|column| {
                let column = column.replace('"', "\"\"");
                format!("typeof(\"{column}\") || ':' || hex(CAST(\"{column}\" AS BLOB))")
            })
            .collect::<Vec<_>>()
            .join(", ");
        // Only identifiers from our migration-created fixture enter SQL.
        // Keep storage types and complete raw bytes, including embedded NULs
        // and invalid UTF-8 TEXT. Every selected result is safe ASCII, and the
        // image includes every ledger column and every FTS shadow/content row.
        let mut query = sqlx::QueryBuilder::<sqlx::Sqlite>::new("SELECT ");
        query
            .push(&selection)
            .push(" FROM \"")
            .push(table.replace('"', "\"\""))
            .push("\" ORDER BY ")
            .push(&selection);
        let rows = query
            .build()
            .fetch_all(pool)
            .await
            .expect("complete fixture table contents");
        let rows = rows
            .iter()
            .map(|row| {
                (0..columns.len())
                    .map(|index| row.try_get(index).expect("quoted fixture value"))
                    .collect()
            })
            .collect();
        tables.push((table.clone(), rows));
    }
    DatabaseImage { schema, tables }
}

async fn delete_metadata(pool: &SqlitePool) {
    let mut transaction = pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("fixture tx");
    let guard: String =
        sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = 'cognitive_meta_no_delete'")
            .fetch_one(&mut *transaction)
            .await
            .expect("trusted compiled seed trigger before tampering");
    sqlx::query("DROP TRIGGER cognitive_meta_no_delete")
        .execute(&mut *transaction)
        .await
        .expect("temporarily remove immutable fixture guard");
    sqlx::query("DELETE FROM cognitive_meta")
        .execute(&mut *transaction)
        .await
        .expect("simulate missing owner metadata");
    sqlx::query(sqlx::AssertSqlSafe(guard.as_str()))
        .execute(&mut *transaction)
        .await
        .expect("restore exact trusted compiled guard in same transaction");
    transaction
        .commit()
        .await
        .expect("fixture tamper committed");
}

async fn assert_denied_unchanged(
    pool: SqlitePool,
    owner_layout: &codex_hepta_paths::HeptaAgentLayout,
    expected: &str,
) {
    let versions: Vec<i64> =
        sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("original prefix");
    assert!(
        versions.last().copied().expect("historical prefix")
            < MIGRATOR.iter().last().expect("compiled lineage").version
    );
    assert_corrupt_unchanged(pool, owner_layout, expected).await;
}

async fn assert_corrupt_unchanged(
    pool: SqlitePool,
    owner_layout: &codex_hepta_paths::HeptaAgentLayout,
    expected: &str,
) {
    let before = image(&pool).await;
    pool.close().await;
    drop(pool);
    let path = owner_layout.cognitive_root().join("cognitive_1.sqlite3");
    let bytes = std::fs::read(&path).expect("cold historical bytes");
    assert!(matches!(CognitiveStore::open(owner_layout).await,
        Err(CognitiveStoreError::Corrupt(message)) if message.contains(expected)));
    assert_eq!(std::fs::read(&path).expect("retained source bytes"), bytes);
    let home = codex_utils_absolute_path::AbsolutePathBuf::try_from(
        owner_layout.cognitive_root().to_path_buf(),
    )
    .expect("regular inspection home");
    let inspection = codex_state::SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(&path)
        .await
        .expect("inspect without migrations or owner binding");
    assert_eq!(image(&inspection).await, before);
    inspection.close().await;
}

async fn seed_row(pool: &SqlitePool, table: &str, owner: &codex_hepta_contracts::AgentId) {
    match table {
        "source_ledger" => {
            sqlx::query(
                "INSERT INTO source_ledger
                 (source_id, source_revision, owner_agent_id, scope_kind,
                  source_kind, content, content_sha256,
                  observed_at_unix_seconds, recorded_at_unix_seconds)
                 VALUES ('source:v1:1111111111111111111111111111111111111111111111111111111111111111', 1, ?, 'agent_private',
                         'explicit_memory_directive', X'66616374', ?, 100, 101)",
            )
            .bind(owner.as_str())
            .bind(codex_hepta_contracts::Sha256Digest::for_bytes(b"fact").as_str())
            .execute(pool)
            .await
            .expect("historical source fact");
        }
        "memory_revisions" => {
            sqlx::query(
                "INSERT INTO memory_revisions
                 (memory_id, revision, owner_agent_id, scope_kind, content,
                  content_sha256, verification, lifecycle,
                  valid_from_unix_seconds, recorded_at_unix_seconds)
                 VALUES ('memory:v1:2222222222222222222222222222222222222222222222222222222222222222', 1, ?, 'agent_private', 'fact', ?,
                         'verified', 'active', 100, 101)",
            )
            .bind(owner.as_str())
            .bind(codex_hepta_contracts::Sha256Digest::for_bytes(b"fact").as_str())
            .execute(pool)
            .await
            .expect("historical memory fact");
        }
        "kg_projection" => {
            sqlx::query(
                "INSERT INTO kg_projection (projection_scope, generation)
                 VALUES ('agent_private', 7)",
            )
            .execute(pool)
            .await
            .expect("legacy KG state that migration 0003 would delete");
        }
        _ => panic!("unknown compiled fixture table: {table}"),
    }
}

#[tokio::test]
async fn missing_metadata_cannot_adopt_residual_source_memory_or_kg_state() {
    for table in ["source_ledger", "memory_revisions", "kg_projection"] {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(96);
        let owner_layout = layout(&temp, &owner);
        let pool = open_v2_test_pool(&owner_layout).await.expect("real v2");
        seed_row(&pool, table, &owner).await;
        delete_metadata(&pool).await;
        assert_denied_unchanged(
            pool,
            &owner_layout,
            "owner metadata is missing while application state remains",
        )
        .await;
    }
}

#[tokio::test]
async fn matching_metadata_cannot_upgrade_foreign_source_or_memory_rows() {
    for table in ["source_ledger", "memory_revisions"] {
        let temp = TempDir::new().expect("temp");
        let owner_layout = layout(&temp, &agent_id(97));
        let pool = open_v2_test_pool(&owner_layout).await.expect("real v2");
        seed_row(&pool, table, &agent_id(98)).await;
        seed_row(&pool, "kg_projection", owner_layout.agent_id()).await;
        assert_denied_unchanged(pool, &owner_layout, "foreign-owned source or memory rows").await;
    }
}

async fn seed_complete_v2_ledger(pool: &SqlitePool, owner: &codex_hepta_contracts::AgentId) {
    for table in ["source_ledger", "memory_revisions", "kg_projection"] {
        seed_row(pool, table, owner).await;
    }
    for statement in [
        "INSERT INTO source_ledger
         (source_id, source_revision, owner_agent_id, scope_kind, source_kind,
          content, content_sha256, observed_at_unix_seconds, recorded_at_unix_seconds)
         SELECT 'source:v1:3333333333333333333333333333333333333333333333333333333333333333',
                source_revision, owner_agent_id, scope_kind, source_kind, content,
                content_sha256, observed_at_unix_seconds + 100, recorded_at_unix_seconds + 100
         FROM source_ledger",
        "INSERT INTO memory_heads(memory_id, revision) VALUES ('memory:v1:2222222222222222222222222222222222222222222222222222222222222222', 1)",
        "INSERT INTO memory_citations
         (memory_id, memory_revision, ordinal, source_id, source_revision)
         VALUES ('memory:v1:2222222222222222222222222222222222222222222222222222222222222222', 1, 0, 'source:v1:1111111111111111111111111111111111111111111111111111111111111111', 1)",
        "INSERT INTO memory_fts(memory_id, revision, content)
         VALUES ('memory:v1:2222222222222222222222222222222222222222222222222222222222222222', 1, 'fact')",
        "INSERT INTO kg_nodes
         (projection_scope, generation, node_id, entity_type, label,
          valid_from_unix_seconds, memory_id, memory_revision, source_id, source_revision)
         VALUES ('agent_private', 7, 'old-node', 'concept', 'Legacy fact',
                 100, 'memory:v1:2222222222222222222222222222222222222222222222222222222222222222', 1, 'source:v1:1111111111111111111111111111111111111111111111111111111111111111', 1)",
        "INSERT INTO kg_entity_fts
         (projection_scope, generation, node_id, entity_type, label)
         VALUES ('agent_private', 7, 'old-node', 'concept', 'Legacy fact')",
        "INSERT INTO memory_revisions
         (memory_id, revision, owner_agent_id, scope_kind, content, content_sha256,
          verification, lifecycle, valid_from_unix_seconds, supersedes_revision,
          recorded_at_unix_seconds)
         SELECT memory_id, 2, owner_agent_id, scope_kind, content, content_sha256,
                verification, lifecycle, valid_from_unix_seconds + 100, 1,
                recorded_at_unix_seconds + 100
         FROM memory_revisions WHERE revision = 1",
        "INSERT INTO memory_citations
         (memory_id, memory_revision, ordinal, source_id, source_revision)
         SELECT memory_id, 2, ordinal,
                'source:v1:3333333333333333333333333333333333333333333333333333333333333333', source_revision
         FROM memory_citations WHERE memory_revision = 1",
        "INSERT INTO memory_fts(memory_id, revision, content)
         SELECT memory_id, revision, content FROM memory_revisions WHERE revision = 2",
        "UPDATE memory_heads SET revision = 2",
    ] {
        sqlx::query(statement)
            .execute(pool)
            .await
            .expect("complete valid historical evidence and legacy KG");
    }
}

#[tokio::test]
async fn corrupt_historical_ledger_cannot_upgrade_or_revoke_old_kg() {
    for (mutation, expected) in [
        (
            "UPDATE source_ledger SET content = CAST('corrupt source' AS BLOB)",
            "source_ledger content digest failed canonical recomputation",
        ),
        (
            "UPDATE memory_revisions SET content = 'corrupt memory'",
            "memory_revisions content digest failed canonical recomputation",
        ),
        (
            "UPDATE memory_citations SET ordinal = 1",
            "memory citations are missing, excessive, or non-contiguous",
        ),
        (
            "UPDATE memory_fts SET content = 'corrupt search content'",
            "memory FTS rows do not exactly match immutable memory revisions",
        ),
        (
            "DELETE FROM memory_fts_docsize",
            "memory FTS index integrity failed:",
        ),
        (
            "UPDATE memory_citations SET source_id = 'source:v1:9999999999999999999999999999999999999999999999999999999999999999'",
            "SQLite foreign_key_check rejected the cognitive store",
        ),
        (
            "UPDATE memory_heads SET memory_id = 'memory:v1:9999999999999999999999999999999999999999999999999999999999999999'",
            "SQLite foreign_key_check rejected the cognitive store",
        ),
        (
            "UPDATE memory_revisions SET valid_to_unix_seconds = valid_from_unix_seconds",
            "SQLite quick_check rejected the cognitive store",
        ),
        (
            "UPDATE source_ledger SET scope_kind = 'workspace_private', workspace_sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
            "memory citation does not match the exact owner and scope",
        ),
        (
            "DELETE FROM memory_heads",
            "current memory heads do not identify every latest immutable revision",
        ),
        (
            "UPDATE memory_heads SET revision = 1",
            "current memory heads do not identify every latest immutable revision",
        ),
        (
            "UPDATE source_ledger SET scope_kind = 'workspace_private', workspace_sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' WHERE source_id = 'source:v1:3333333333333333333333333333333333333333333333333333333333333333';
             UPDATE memory_revisions SET scope_kind = 'workspace_private', workspace_sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' WHERE revision = 2",
            "memory revision history violates predecessor, scope, or tombstone continuity",
        ),
        (
            "UPDATE memory_revisions SET lifecycle = 'tombstoned', tombstone_reason = 'withdrawn' WHERE revision = 1",
            "memory revision history violates predecessor, scope, or tombstone continuity",
        ),
        (
            "UPDATE memory_revisions SET supersedes_revision = NULL WHERE revision = 2",
            "memory revision history violates predecessor, scope, or tombstone continuity",
        ),
        (
            "UPDATE memory_revisions SET supersedes_revision = 2 WHERE revision = 1",
            "memory revision history violates predecessor, scope, or tombstone continuity",
        ),
        (
            "UPDATE source_ledger SET source_kind = 'bogus'",
            "source_ledger has invalid typed metadata",
        ),
        (
            "UPDATE source_ledger SET scope_kind = 'workspace_private';
             UPDATE memory_revisions SET scope_kind = 'workspace_private'",
            "source_ledger has invalid typed metadata",
        ),
        (
            "UPDATE memory_revisions SET lifecycle = 'tombstoned' WHERE revision = 2",
            "memory_revisions has invalid typed metadata",
        ),
        (
            "UPDATE memory_revisions SET lifecycle = 'tombstoned', tombstone_reason = ' ' WHERE revision = 2",
            "memory_revisions has invalid typed metadata",
        ),
        (
            "UPDATE memory_revisions SET lifecycle = 'tombstoned', tombstone_reason = replace(hex(zeroblob(129)), '00', 'é') WHERE revision = 2",
            "memory_revisions typed metadata exceeds durable bounds",
        ),
        (
            "UPDATE source_ledger SET scope_kind = 'workspace_private', workspace_sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' || char(0);
             UPDATE memory_revisions SET scope_kind = 'workspace_private', workspace_sha256 = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' || char(0)",
            "source_ledger typed metadata exceeds durable bounds",
        ),
        (
            "UPDATE memory_revisions SET content = CAST(X'FF' AS TEXT), content_sha256 = 'a8100ae6aa1940d0b663bb31cd466142ebbdbd5187131b92d93818987832eb89';
             UPDATE memory_fts SET content = CAST(X'FF' AS TEXT)",
            "memory_revisions content is not valid UTF-8",
        ),
        (
            "UPDATE memory_fts SET revision = '01' WHERE revision = 2",
            "memory FTS rows do not exactly match immutable memory revisions",
        ),
        (
            "UPDATE source_ledger SET source_id = 'malformed' WHERE source_id = 'source:v1:1111111111111111111111111111111111111111111111111111111111111111';
             UPDATE memory_citations SET source_id = 'malformed' WHERE memory_revision = 1;
             UPDATE kg_nodes SET source_id = 'malformed'",
            "source_ledger has invalid typed metadata",
        ),
        (
            "UPDATE memory_revisions SET memory_id = 'malformed';
             UPDATE memory_heads SET memory_id = 'malformed';
             UPDATE memory_citations SET memory_id = 'malformed';
             UPDATE memory_fts SET memory_id = 'malformed';
             UPDATE kg_nodes SET memory_id = 'malformed'",
            "memory_revisions has invalid typed metadata",
        ),
    ] {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(104);
        let owner_layout = layout(&temp, &owner);
        let pool = open_v2_test_pool(&owner_layout).await.expect("real v2");
        seed_complete_v2_ledger(&pool, &owner).await;
        let mut connection = pool.acquire().await.expect("fixture connection");
        // FK enforcement is connection-local and cannot be changed inside a
        // transaction. Disable it only for this data-adversary fault fixture.
        sqlx::query("PRAGMA foreign_keys = OFF")
            .execute(&mut *connection)
            .await
            .expect("permit dangling-reference fixture");
        sqlx::query("PRAGMA ignore_check_constraints = ON")
            .execute(&mut *connection)
            .await
            .expect("permit CHECK-only validity-range fixture");
        let mut fault = connection
            .begin_with("BEGIN IMMEDIATE")
            .await
            .expect("historical fixture fault transaction");
        let mut guards = Vec::new();
        for (trigger, drop_trigger) in [
            ("source_ledger_no_update", "DROP TRIGGER source_ledger_no_update"),
            ("memory_revisions_no_update", "DROP TRIGGER memory_revisions_no_update"),
            ("memory_citations_no_update", "DROP TRIGGER memory_citations_no_update"),
        ] {
            // Only exact SQL saved from the compiled, untampered fixture is
            // restored. Owner-supplied SQL never enters AssertSqlSafe.
            let sql: String = sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ?")
                .bind(trigger)
                .fetch_one(&mut *fault)
                .await
                .expect("trusted compiled immutable guard");
            sqlx::query(drop_trigger)
                .execute(&mut *fault)
                .await
                .expect("temporarily remove immutable fixture guard");
            guards.push(sql);
        }
        // The static fault may update several mutually referencing tables.
        // raw_sql executes every statement, preserving FK-valid isolated faults.
        sqlx::raw_sql(mutation)
            .execute(&mut *fault)
            .await
            .expect("corrupt historical evidence without changing compiled schema");
        for guard_sql in guards {
            sqlx::query(sqlx::AssertSqlSafe(guard_sql.as_str()))
                .execute(&mut *fault)
                .await
                .expect("restore exact compiled immutable fixture guard");
        }
        fault.commit().await.expect("commit historical corruption");
        sqlx::query("PRAGMA ignore_check_constraints = OFF")
            .execute(&mut *connection)
            .await
            .expect("restore ordinary CHECK enforcement");
        sqlx::query("PRAGMA foreign_keys = ON")
            .execute(&mut *connection)
            .await
            .expect("restore ordinary FK enforcement");
        drop(connection);
        // The complete image includes the 1..2 migration ledger, immutable
        // owner row, Source/Memory/citations and old generation-7 KG contents.
        assert_denied_unchanged(pool, &owner_layout, expected).await;
    }
}

#[tokio::test]
async fn current_owned_corrupt_source_is_rejected_without_initialization_writes() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(107);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("current owner");
    store
        .append_source(
            &crate::CognitiveAccess::agent_private(owner),
            &crate::cognitive_test_support::source(
                crate::CognitiveScope::AgentPrivate,
                "current-corrupt-source",
                "canonical source",
            ),
        )
        .await
        .expect("canonical current source");
    let mut fault = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("fault transaction");
    let guard: String =
        sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = 'source_ledger_no_update'")
            .fetch_one(&mut *fault)
            .await
            .expect("trusted compiled guard before tampering");
    sqlx::query("DROP TRIGGER source_ledger_no_update")
        .execute(&mut *fault)
        .await
        .expect("remove fixture guard");
    sqlx::query("UPDATE source_ledger SET content = CAST('corrupted current source' AS BLOB)")
        .execute(&mut *fault)
        .await
        .expect("corrupt current content only");
    sqlx::query(sqlx::AssertSqlSafe(guard.as_str()))
        .execute(&mut *fault)
        .await
        .expect("restore exact compiled guard");
    fault.commit().await.expect("commit fault");
    let versions: Vec<i64> =
        sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await
            .expect("current lineage");
    assert_eq!(
        versions,
        MIGRATOR
            .iter()
            .map(|migration| migration.version)
            .collect::<Vec<_>>()
    );
    let pool = store.pool.clone();
    drop(store);
    assert_corrupt_unchanged(
        pool,
        &owner_layout,
        "source_ledger content digest failed canonical recomputation",
    )
    .await;
}

#[tokio::test]
async fn current_empty_metadata_with_corrupt_fts_shadow_cannot_bind_an_owner() {
    let temp = TempDir::new().expect("temp");
    let owner_layout = layout(&temp, &agent_id(108));
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("empty current owner");
    delete_metadata(&store.pool).await;
    sqlx::query("DELETE FROM memory_fts_data WHERE id = 1")
        .execute(&store.pool)
        .await
        .expect("corrupt physical empty FTS index");
    let logical_rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_fts")
        .fetch_one(&store.pool)
        .await
        .expect("logical FTS remains empty");
    let owners: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_meta")
        .fetch_one(&store.pool)
        .await
        .expect("metadata remains absent");
    assert_eq!((logical_rows, owners), (0, 0));
    let versions: Vec<i64> =
        sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await
            .expect("current lineage");
    assert_eq!(
        versions,
        MIGRATOR
            .iter()
            .map(|migration| migration.version)
            .collect::<Vec<_>>()
    );
    let pool = store.pool.clone();
    drop(store);
    assert_corrupt_unchanged(pool, &owner_layout, "memory FTS index integrity failed:").await;
}

#[tokio::test]
async fn valid_historical_revision_chain_preserves_legacy_memory_ids() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(106);
    let owner_layout = layout(&temp, &owner);
    let pool = open_v2_test_pool(&owner_layout).await.expect("real v2");
    seed_complete_v2_ledger(&pool, &owner).await;
    pool.close().await;
    drop(pool);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("valid historical predecessor chain upgrades");
    let revisions: Vec<(String, i64, String)> = sqlx::query_as(
        "SELECT memory_id, revision, content FROM memory_revisions ORDER BY revision",
    )
    .fetch_all(&store.pool)
    .await
    .expect("retained immutable historical revisions");
    let id = format!("memory:v1:{}", "2".repeat(64));
    assert_eq!(
        revisions,
        vec![
            (id.clone(), 1, "fact".to_string()),
            (id, 2, "fact".to_string())
        ]
    );
    let head: i64 = sqlx::query_scalar("SELECT revision FROM memory_heads")
        .fetch_one(&store.pool)
        .await
        .expect("retained latest historical head");
    assert_eq!(head, 2);
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("upgraded legacy history remains reopenable");
    reopened.pool.close().await;
}

#[tokio::test]
async fn empty_utf16_historical_owner_is_rejected_without_upgrading() {
    let temp = TempDir::new().expect("temp");
    let owner_layout = layout(&temp, &agent_id(105));
    super::super::super::create_private_directory(owner_layout.cognitive_root())
        .expect("private owner directory");
    let path = owner_layout.cognitive_root().join("cognitive_1.sqlite3");
    let _file = super::super::super::files::DatabaseFileGuard::prepare(&path)
        .expect("private regular fixture database");
    let home = codex_utils_absolute_path::AbsolutePathBuf::try_from(
        owner_layout.cognitive_root().to_path_buf(),
    )
    .expect("fixture home");
    let pool = codex_state::SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(&path)
        .await
        .expect("approved fixture SQLite opener");
    let mut connection = pool.acquire().await.expect("single fixture connection");
    sqlx::query("PRAGMA encoding = 'UTF-16le'")
        .execute(&mut *connection)
        .await
        .expect("set encoding before the first schema object");
    MIGRATOR
        .run_to(2, &mut *connection)
        .await
        .expect("real UTF-16 historical schema");
    sqlx::query(
        "INSERT INTO cognitive_meta (singleton, schema_version, owner_agent_id)
         VALUES (1, 1, ?)",
    )
    .bind(owner_layout.agent_id().as_str())
    .execute(&mut *connection)
    .await
    .expect("matching historical owner with no application facts");
    let encoding: String = sqlx::query_scalar("PRAGMA encoding")
        .fetch_one(&mut *connection)
        .await
        .expect("actual non-UTF-8 owner encoding");
    assert_eq!(encoding, "UTF-16le");
    drop(connection);
    assert_denied_unchanged(pool, &owner_layout, "database encoding must be UTF-8").await;
}

#[tokio::test]
async fn matching_metadata_cannot_upgrade_foreign_logical_turn_or_operation_subject() {
    for version in [10, 11] {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(99);
        let owner_layout = layout(&temp, &owner);
        let pool = open_v2_test_pool(&owner_layout).await.expect("real v2");
        MIGRATOR
            .run_to(version, &pool)
            .await
            .expect("real historical prefix");
        let expected = if version == 10 {
            sqlx::query(
                "INSERT INTO cognitive_logical_turns
                 (owner_agent_id, logical_turn_id, scope_key, logical_binding_sha256,
                  identity_sha256, recorded_at_unix_seconds)
                 VALUES (?, 'turn', 'agent_private', ?, ?, 100)",
            )
            .bind(agent_id(100).as_str())
            .bind("a".repeat(64))
            .bind("b".repeat(64))
            .execute(&pool)
            .await
            .expect("foreign logical-turn owner");
            "foreign-owned cognitive_logical_turns rows"
        } else {
            let mut connection = pool.acquire().await.expect("fixture connection");
            sqlx::query("PRAGMA foreign_keys = OFF")
                .execute(&mut *connection)
                .await
                .expect("data adversary fixture");
            sqlx::query(
                "INSERT INTO cognitive_operation_ledger
                 (operation_id, semantic_sha256, subject_id, destination_id,
                  payload_sha256, scope_sha256, policy_generation, lease_id,
                  event_id, outbox_id, owner_agent_id, generation, fencing_token,
                  authority_epoch, owner_epoch, prepared_at_unix_seconds)
                 VALUES ('op', ?, ?, 'destination', ?, ?, 1, 'lease', 'event',
                         'outbox', ?, 1, 'fence', 1, 1, 100)",
            )
            .bind("a".repeat(64))
            .bind(agent_id(100).as_str())
            .bind("b".repeat(64))
            .bind("c".repeat(64))
            .bind(owner.as_str())
            .execute(&mut *connection)
            .await
            .expect("foreign operation subject");
            sqlx::query("PRAGMA foreign_keys = ON")
                .execute(&mut *connection)
                .await
                .expect("restore FK checks");
            "foreign-owned cognitive_operation_ledger rows"
        };
        assert_denied_unchanged(pool, &owner_layout, expected).await;
    }
}

#[tokio::test]
async fn empty_historical_initialization_excludes_default_fts_shadow_rows() {
    let temp = TempDir::new().expect("temp");
    let owner_layout = layout(&temp, &agent_id(101));
    let pool = open_v2_test_pool(&owner_layout).await.expect("real v2");
    delete_metadata(&pool).await;
    let shadow_rows: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_fts_data")
        .fetch_one(&pool)
        .await
        .expect("default FTS physical state");
    assert!(shadow_rows > 0);
    pool.close().await;
    drop(pool);
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("empty admitted historical state may initialize");
    let owner: String = sqlx::query_scalar("SELECT owner_agent_id FROM cognitive_meta")
        .fetch_one(&store.pool)
        .await
        .expect("new owner binding");
    let versions: Vec<i64> =
        sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&store.pool)
            .await
            .expect("upgraded lineage");
    assert_eq!(
        (owner, versions),
        (
            owner_layout.agent_id().as_str().to_string(),
            MIGRATOR.iter().map(|migration| migration.version).collect()
        )
    );
    store.pool.close().await;
}

#[tokio::test]
async fn local_federation_owner_may_retain_an_external_consumer() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(102);
    let owner_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&owner_layout).await.expect("owner");
    let capability = store
        .grant_federated_recall(
            &crate::CognitiveAccess::agent_private(owner),
            &crate::FederationGrantRequest {
                consumer_agent_id: agent_id(103),
                scope: crate::FederationGrantScope::new(
                    crate::CognitiveScope::AgentPrivate,
                    crate::cognitive_test_support::workspace("external-consumer"),
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1000,
            },
        )
        .await
        .expect("legitimate remote consumer");
    store.pool.close().await;
    drop(store);
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("local producer remains valid");
    assert_eq!(
        reopened
            .list_federation_capabilities(16)
            .await
            .expect("retained grant")[0]
            .capability,
        capability
    );
    reopened.pool.close().await;
}
