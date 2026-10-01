use pretty_assertions::assert_eq;
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
            .map(|column| format!("quote(\"{}\")", column.replace('"', "\"\"")))
            .collect::<Vec<_>>()
            .join(", ");
        // Only identifiers from our migration-created fixture enter SQL.
        // quote() retains NULL, text, integers and complete BLOB bytes, so the
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
    let before = image(&pool).await;
    let versions: Vec<i64> =
        sqlx::query_scalar("SELECT version FROM _sqlx_migrations ORDER BY version")
            .fetch_all(&pool)
            .await
            .expect("original prefix");
    assert!(
        versions.last().copied().expect("historical prefix")
            < MIGRATOR.iter().last().expect("compiled lineage").version
    );
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
                 VALUES ('historical-source', 1, ?, 'agent_private',
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
                 VALUES ('historical-memory', 1, ?, 'agent_private', 'fact', ?,
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
