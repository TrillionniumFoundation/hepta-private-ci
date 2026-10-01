use std::error::Error;
use std::fs;
use std::path::Path;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

// This fixture opens old or deliberately corrupted schemas outside normal owner admission.
#[allow(clippy::disallowed_methods)]
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
    let scope_problems: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_scope_witness_audit")
        .fetch_one(&pool)
        .await?;
    let head_problems: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_head_validity_audit")
        .fetch_one(&pool)
        .await?;
    assert_eq!(scope_problems, 0);
    assert_eq!(head_problems, 0);

    let witness_error = sqlx::query(
        "UPDATE lane_c_scope_witness
         SET source_count = source_count + 1, state_revision = state_revision + 1",
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
    reopened.recovery_anchor().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lane_c_witness_reopen_rejects_missing_and_weakened_schema() -> TestResult {
    for (mutation, expected_message) in [
        (
            "DROP TRIGGER lane_c_source_witness_after_insert",
            "required cognitive schema object",
        ),
        (
            "DROP VIEW lane_c_scope_witness_audit",
            "required cognitive schema object",
        ),
        (
            "DROP INDEX lane_c_head_validity_end_lookup",
            "required cognitive schema object",
        ),
        (
            "DROP TABLE lane_c_head_validity",
            "required cognitive schema object",
        ),
        (
            "DROP TRIGGER lane_c_source_witness_after_insert;
             CREATE TRIGGER lane_c_source_witness_after_insert
             AFTER INSERT ON source_ledger BEGIN SELECT 1; END",
            "schema definition oracle mismatch",
        ),
        (
            "DROP VIEW lane_c_scope_witness_audit;
             CREATE VIEW lane_c_scope_witness_audit AS
             SELECT owner_agent_id, scope_kind, workspace_key, 'ignored' AS problem
             FROM lane_c_scope_witness WHERE 0",
            "schema definition oracle mismatch",
        ),
    ] {
        let temp = tempfile::tempdir()?;
        let fleet_path = temp.path().join("fleet");
        fs::create_dir_all(&fleet_path)?;
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000520")?;
        let layout = HeptaFleetRoot::parse(fleet_path)?.layout().agent(&owner);
        let store = CognitiveStore::open(&layout).await?;
        let pool = raw_pool(store.path(), /*create*/ false).await?;
        sqlx::raw_sql(mutation).execute(&pool).await?;
        pool.close().await;
        drop(store);

        let reopened = CognitiveStore::open(&layout).await;
        assert!(
            matches!(reopened, Err(CognitiveStoreError::Corrupt(message)) if message.contains(expected_message)),
            "reopen must authenticate Lane C schema after {mutation}"
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lane_c_witness_reopen_audits_existing_v17_content() -> TestResult {
    for (guard_name, drop_sql, mutation) in [
        (
            "lane_c_scope_witness_direct_update_guard",
            "DROP TRIGGER lane_c_scope_witness_direct_update_guard",
            "UPDATE lane_c_scope_witness
             SET source_count = source_count + 1, state_revision = state_revision + 1",
        ),
        (
            "lane_c_head_validity_direct_update_guard",
            "DROP TRIGGER lane_c_head_validity_direct_update_guard",
            "UPDATE lane_c_head_validity
             SET valid_from_unix_seconds = valid_from_unix_seconds + 1",
        ),
    ] {
        let temp = tempfile::tempdir()?;
        let fleet_path = temp.path().join("fleet");
        fs::create_dir_all(&fleet_path)?;
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000521")?;
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
                    event_key: "reopen-witness-source".to_string(),
                    content: b"reopen witness source".to_vec(),
                    observed_at_unix_seconds: 100,
                },
            )
            .await?;
        store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: "reopen-witness-memory".to_string(),
                    revision: MemoryRevisionDraft {
                        scope,
                        content: "reopen witness memory".to_string(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: vec![citation],
                    },
                },
            )
            .await?;
        let pool = raw_pool(store.path(), /*create*/ false).await?;
        let guard_sql: String =
            sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE name = ? AND type = 'trigger'")
                .bind(guard_name)
                .fetch_one(&pool)
                .await?;
        sqlx::raw_sql(drop_sql).execute(&pool).await?;
        sqlx::raw_sql(mutation).execute(&pool).await?;
        // Restore the exact compiled definition so schema authentication passes
        // and only the independent reopen content audit can detect this drift.
        // This DDL came from one of the two fixed fixture guards above in a
        // freshly opened, schema-authenticated database, before corruption.
        sqlx::raw_sql(sqlx::AssertSqlSafe(guard_sql))
            .execute(&pool)
            .await?;
        pool.close().await;
        assert!(
            matches!(
                store.recovery_anchor().await,
                Err(CognitiveStoreError::Corrupt(message)) if message.contains("Lane C witness does not match")
            ),
            "a corrupt projection must not receive a fresh recovery anchor"
        );
        drop(store);

        let reopened = CognitiveStore::open(&layout).await;
        assert!(
            matches!(reopened, Err(CognitiveStoreError::Corrupt(message)) if message.contains("Lane C witness does not match")),
            "already-migrated witness drift must fail reopen after {mutation}"
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unselected_head_rollback_cannot_restore_an_earlier_selection_witness() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    fs::create_dir_all(&fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000522")?;
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
                event_key: "head-rollback-source".to_string(),
                content: b"head rollback source".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await?;
    let revision = MemoryRevisionDraft {
        scope: scope.clone(),
        content: "rollback fixture".to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: vec![citation],
    };
    let selected_record = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "selected-head".to_string(),
                revision: revision.clone(),
            },
        )
        .await?;
    let unselected_record = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "unselected-head".to_string(),
                revision: revision.clone(),
            },
        )
        .await?;
    let corrected_record = store
        .correct_memory(
            &access,
            &unselected_record.id.memory_id,
            unselected_record.id.revision,
            &MemoryRevisionDraft {
                content: "corrected rollback fixture".to_string(),
                ..revision
            },
        )
        .await?;
    let selected_id = StableId::new(selected_record.id.memory_id.as_str())?;
    let selected = store
        .lane_c_snapshot_ids(
            &access,
            &scope,
            /*now_unix_seconds*/ 200,
            &[selected_id],
        )
        .await?;
    let pool = raw_pool(store.path(), /*create*/ false).await?;
    sqlx::query("PRAGMA recursive_triggers = OFF")
        .execute(&pool)
        .await?;
    // Changing a head's primary identity at an unchanged revision must not
    // leave stale validity rows outside the selected ID set. UPDATE OR REPLACE
    // must be rejected before its conflicting-row deletion can take effect.
    for mutation in [
        "UPDATE OR REPLACE memory_heads SET memory_id = ? WHERE memory_id = ?",
        "UPDATE OR REPLACE lane_c_head_validity SET memory_id = ? WHERE memory_id = ?",
    ] {
        let identity_error = sqlx::query(mutation)
            .bind(selected_record.id.memory_id.as_str())
            .bind(unselected_record.id.memory_id.as_str())
            .execute(&pool)
            .await
            .expect_err("head and validity identities must remain immutable");
        assert!(
            identity_error
                .to_string()
                .contains("identity cannot change")
        );
    }
    let prior_revision: i64 = sqlx::query_scalar("SELECT state_revision FROM lane_c_scope_witness")
        .fetch_one(&pool)
        .await?;
    // All row counts and validity boundaries stay fixed. Only an unselected
    // head pointer changes, which the mutation revision must continue to bind.
    sqlx::query("UPDATE memory_heads SET revision = 1 WHERE memory_id = ?")
        .bind(corrected_record.id.memory_id.as_str())
        .execute(&pool)
        .await?;
    let reset_error = sqlx::query("UPDATE lane_c_scope_witness SET state_revision = ?")
        .bind(prior_revision)
        .execute(&pool)
        .await
        .expect_err("a valid earlier revision must not hide the unselected head mutation");
    assert!(reset_error.to_string().contains("state revision regressed"));
    let replace_error = sqlx::query(
        "INSERT OR REPLACE INTO lane_c_scope_witness
         SELECT owner_agent_id, scope_kind, workspace_key, ?, memory_revision_count,
                source_count, citation_count, tombstone_count, knowledge_fact_count,
                head_count
         FROM lane_c_scope_witness",
    )
    .bind(prior_revision)
    .execute(&pool)
    .await
    .expect_err("REPLACE must not bypass the witness update/delete guards");
    assert!(
        replace_error
            .to_string()
            .contains("identity cannot be replaced")
    );
    let identity_error = sqlx::query(
        "UPDATE lane_c_scope_witness
         SET workspace_key = ?, scope_kind = 'workspace_private',
             state_revision = state_revision + 1",
    )
    .bind("0".repeat(64))
    .execute(&pool)
    .await
    .expect_err("the owner witness must retain its scope identity");
    assert!(identity_error.to_string().contains("witness identity"));
    pool.close().await;
    assert!(matches!(
        store
            .revalidate_lane_c_selection(&access, &scope, &selected, /*now_unix_seconds*/ 200)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
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
    let scope_problems: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_scope_witness_audit")
        .fetch_one(&verification_pool)
        .await?;
    let head_problems: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM lane_c_head_validity_audit")
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
    assert!(
        result.is_err(),
        "migration must fail closed on witness drift"
    );

    let verification_pool = raw_pool(&path, false).await?;
    let migration_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM _sqlx_migrations WHERE version = 17")
            .fetch_one(&verification_pool)
            .await?;
    assert_eq!(migration_rows, 0);
    verification_pool.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn canonical_replace_guards_preserve_owner_replay_and_current_cut() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    fs::create_dir_all(&fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000523")?;
    let layout = HeptaFleetRoot::parse(fleet_path)?.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let source_draft = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "canonical-replace-source".to_string(),
        content: b"canonical source".to_vec(),
        observed_at_unix_seconds: 100,
    };
    let citation = store.append_source(&access, &source_draft).await?;
    assert_eq!(store.append_source(&access, &source_draft).await?, citation);
    assert!(matches!(
        store
            .append_source(
                &access,
                &SourceDraft {
                    content: b"conflicting replay".to_vec(),
                    ..source_draft
                }
            )
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let draft = MemoryRevisionDraft {
        scope: scope.clone(),
        content: "canonical memory".to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 100,
        valid_to_unix_seconds: None,
        citations: vec![citation],
    };
    let record = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "canonical-replace-memory".to_string(),
                revision: draft.clone(),
            },
        )
        .await?;
    // A second legitimate publication exercises insert-if-absent initialization
    // of the existing KG pointer followed by its guarded generation update.
    store
        .correct_memory(
            &access,
            &record.id.memory_id,
            record.id.revision,
            &MemoryRevisionDraft {
                content: "canonical correction".to_string(),
                ..draft
            },
        )
        .await?;
    let selected = store
        .lane_c_snapshot_ids(
            &access,
            &scope,
            /*now_unix_seconds*/ 200,
            &[StableId::new(record.id.memory_id.as_str())?],
        )
        .await?;
    let anchor = store.recovery_anchor().await?;
    let pool = raw_pool(store.path(), /*create*/ false).await?;
    sqlx::query("PRAGMA recursive_triggers = OFF")
        .execute(&pool)
        .await?;
    for mutation in [
        "INSERT OR REPLACE INTO source_ledger
         SELECT source_id, source_revision, owner_agent_id, 'workspace_private',
                printf('%064d', 0), source_kind, content, content_sha256,
                observed_at_unix_seconds, recorded_at_unix_seconds FROM source_ledger",
        "INSERT OR REPLACE INTO memory_revisions
         SELECT memory_id, revision, owner_agent_id, 'workspace_private', printf('%064d', 0),
                content, content_sha256, verification, lifecycle, tombstone_reason,
                valid_from_unix_seconds, valid_to_unix_seconds, supersedes_revision,
                recorded_at_unix_seconds FROM memory_revisions",
        "INSERT OR REPLACE INTO memory_citations SELECT * FROM memory_citations",
        "INSERT OR REPLACE INTO kg_revision_fact_sets SELECT * FROM kg_revision_fact_sets",
        "INSERT OR REPLACE INTO cognitive_meta SELECT * FROM cognitive_meta",
        "INSERT OR REPLACE INTO kg_projection SELECT projection_scope, 1 FROM kg_projection",
        "INSERT OR REPLACE INTO kg_projection_generation_receipts
         SELECT * FROM kg_projection_generation_receipts",
        "INSERT OR REPLACE INTO kg_projection_generation_semantics
         SELECT * FROM kg_projection_generation_semantics",
        "INSERT OR REPLACE INTO kg_projection_generation_storage
         SELECT * FROM kg_projection_generation_storage",
    ] {
        let error = sqlx::query(mutation)
            .execute(&pool)
            .await
            .expect_err("REPLACE must not bypass immutable canonical identities");
        assert!(
            error
                .to_string()
                .contains("existing identity cannot be replaced")
        );
    }
    pool.close().await;
    assert_eq!(
        store
            .revalidate_lane_c_selection(&access, &scope, &selected, /*now_unix_seconds*/ 200,)
            .await?,
        selected
    );
    assert_eq!(store.recovery_anchor().await?, anchor);
    drop(store);
    let reopened = CognitiveStore::open(&layout).await?;
    assert_eq!(reopened.recovery_anchor().await?, anchor);
    assert_eq!(
        reopened
            .lane_c_snapshot_ids(
                &access,
                &scope,
                /*now_unix_seconds*/ 200,
                &[StableId::new(record.id.memory_id.as_str())?],
            )
            .await?,
        selected
    );
    Ok(())
}
