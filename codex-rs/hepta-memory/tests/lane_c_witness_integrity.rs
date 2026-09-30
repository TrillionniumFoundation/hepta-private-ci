use std::error::Error;
use std::fs;
use std::path::Path;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

async fn raw_pool(path: &Path, create: bool) -> Result<SqlitePool, sqlx::Error> {
    SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(
            SqliteConnectOptions::new()
                .filename(path)
                .create_if_missing(create),
        )
        .await
}

async fn seed_v16_source(pool: &SqlitePool, owner: &AgentId, suffix: &str) -> TestResult {
    sqlx::query(
        "INSERT INTO source_ledger (
            source_id, source_revision, owner_agent_id, scope_kind,
            workspace_sha256, source_kind, content, content_sha256,
            observed_at_unix_seconds, recorded_at_unix_seconds
         ) VALUES (?, 1, ?, 'agent_private', NULL, ?, ?, ?, 100, 100)",
    )
    .bind(format!("lane-c-witness-source-{suffix}"))
    .bind(owner.as_str())
    .bind("explicit_memory_directive")
    .bind(format!("migration seed {suffix}").into_bytes())
    .bind("0".repeat(64))
    .execute(pool)
    .await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lane_c_witness_guards_reject_drift_and_reopen_cleanly() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    fs::create_dir_all(&fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000517")?;
    let layout = HeptaFleetRoot::parse(fleet_path)?.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "lane-c-witness-integrity-source".to_string(),
                content: b"lane c witness integrity".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await?;
    store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "lane-c-witness-integrity-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: scope.clone(),
                    content: "guarded witness memory".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await?;

    let pool = raw_pool(store.path(), false).await?;
    let scope_problems: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_scope_witness_audit")
            .fetch_one(&pool)
            .await?;
    let head_problems: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_head_validity_audit")
            .fetch_one(&pool)
            .await?;
    assert_eq!(scope_problems, 0);
    assert_eq!(head_problems, 0);

    let witness_error = sqlx::query(
        "UPDATE lane_c_scope_witness
         SET source_count = source_count + 1",
    )
    .execute(&pool)
    .await
    .expect_err("an inconsistent scope witness must be rejected");
    assert!(
        witness_error
            .to_string()
            .contains("Lane C scope witness direct-write drift")
    );

    let validity_error = sqlx::query(
        "UPDATE lane_c_head_validity
         SET valid_from_unix_seconds = valid_from_unix_seconds + 1",
    )
    .execute(&pool)
    .await
    .expect_err("an inconsistent head-validity row must be rejected");
    assert!(
        validity_error
            .to_string()
            .contains("Lane C head-validity direct-write drift")
    );

    let delete_error = sqlx::query("DELETE FROM lane_c_scope_witness")
        .execute(&pool)
        .await
        .expect_err("derived scope witnesses must not be deleted");
    assert!(
        delete_error
            .to_string()
            .contains("Lane C scope witness rows are derived")
    );
    pool.close().await;

    let reopened = CognitiveStore::open(&layout).await?;
    let cut = reopened.lane_c_snapshot(&access, &scope, 200).await?;
    assert_eq!(cut.snapshot().records.len(), 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lane_c_witness_migration_recomputes_nonempty_v16_store() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    fs::create_dir_all(&fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000518")?;
    let layout = HeptaFleetRoot::parse(fleet_path)?.layout().agent(&owner);
    fs::create_dir_all(layout.cognitive_root())?;
    let path = layout.cognitive_root().join("cognitive_1.sqlite3");

    let pool = raw_pool(&path, true).await?;
    MIGRATOR.run_to(16, &pool).await?;
    seed_v16_source(&pool, &owner, "clean").await?;
    pool.close().await;

    let store = CognitiveStore::open(&layout).await?;
    let verification_pool = raw_pool(store.path(), false).await?;
    let scope_problems: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_scope_witness_audit")
            .fetch_one(&verification_pool)
            .await?;
    let head_problems: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_head_validity_audit")
            .fetch_one(&verification_pool)
            .await?;
    let migration_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM _sqlx_migrations
         WHERE version = 17 AND success = 1",
    )
    .fetch_one(&verification_pool)
    .await?;
    assert_eq!(scope_problems, 0);
    assert_eq!(head_problems, 0);
    assert_eq!(migration_rows, 1);
    verification_pool.close().await;

    drop(store);
    CognitiveStore::open(&layout).await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lane_c_witness_migration_rejects_preexisting_drift() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    fs::create_dir_all(&fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000519")?;
    let layout = HeptaFleetRoot::parse(fleet_path)?.layout().agent(&owner);
    fs::create_dir_all(layout.cognitive_root())?;
    let path = layout.cognitive_root().join("cognitive_1.sqlite3");

    let pool = raw_pool(&path, true).await?;
    MIGRATOR.run_to(16, &pool).await?;
    seed_v16_source(&pool, &owner, "drift").await?;
    sqlx::query("UPDATE lane_c_scope_witness SET source_count = 0")
        .execute(&pool)
        .await?;
    pool.close().await;

    let result = CognitiveStore::open(&layout).await;
    assert!(result.is_err(), "migration must fail closed on witness drift");

    let verification_pool = raw_pool(&path, false).await?;
    let migration_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM _sqlx_migrations WHERE version = 17",
    )
    .fetch_one(&verification_pool)
    .await?;
    assert_eq!(migration_rows, 0);
    verification_pool.close().await;
    Ok(())
}
