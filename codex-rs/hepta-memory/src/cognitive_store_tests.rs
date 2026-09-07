use pretty_assertions::assert_eq;
use tempfile::TempDir;

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::StableMemoryId;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;

#[tokio::test]
async fn stores_are_per_agent_append_only_and_scope_fail_closed() {
    let temp = TempDir::new().expect("temp dir");
    let first_agent = agent_id(1);
    let second_agent = agent_id(2);
    let first = CognitiveStore::open(&layout(&temp, &first_agent))
        .await
        .expect("first store");
    let second = CognitiveStore::open(&layout(&temp, &second_agent))
        .await
        .expect("second store");
    assert_ne!(first.path(), second.path());

    let first_access = CognitiveAccess::agent_private(first_agent.clone());
    let source_draft = source(CognitiveScope::AgentPrivate, "explicit-1", "remember this");
    let appended = first
        .append_source(&first_access, &source_draft)
        .await
        .expect("append source");
    assert_eq!(
        first
            .append_source(&first_access, &source_draft)
            .await
            .expect("idempotent replay"),
        appended
    );

    let cross_agent = first
        .append_source(&CognitiveAccess::agent_private(second_agent), &source_draft)
        .await
        .expect_err("cross-agent write must fail");
    assert!(matches!(cross_agent, CognitiveStoreError::AccessDenied(_)));

    let scoped = source(
        CognitiveScope::WorkspacePrivate {
            workspace_sha256: workspace("alpha"),
        },
        "workspace-1",
        "private workspace fact",
    );
    let wrong_workspace = first
        .append_source(
            &CognitiveAccess::workspace_private(first_agent, workspace("beta")),
            &scoped,
        )
        .await
        .expect_err("workspace mismatch must fail");
    assert!(matches!(
        wrong_workspace,
        CognitiveStoreError::AccessDenied(_)
    ));

    let delete_error = sqlx::query("DELETE FROM source_ledger")
        .execute(&first.pool)
        .await
        .expect_err("source ledger must be immutable");
    assert!(
        delete_error
            .to_string()
            .contains("source ledger is immutable")
    );
}

#[tokio::test]
async fn concurrent_source_identity_conflict_commits_exactly_one_payload() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(81);
    let owner_layout = layout(&temp, &owner);
    let first = CognitiveStore::open(&owner_layout)
        .await
        .expect("first writer");
    let second = CognitiveStore::open(&owner_layout)
        .await
        .expect("second writer");
    let access = CognitiveAccess::agent_private(owner);
    let first_draft = source(
        CognitiveScope::AgentPrivate,
        "shared-operation",
        "first payload",
    );
    let second_draft = source(
        CognitiveScope::AgentPrivate,
        "shared-operation",
        "second payload",
    );

    let (first_result, second_result) = tokio::join!(
        first.append_source(&access, &first_draft),
        second.append_source(&access, &second_draft),
    );
    let (committed, expected_content) = match (first_result, second_result) {
        (Ok(receipt), Err(CognitiveStoreError::Conflict(_))) => (receipt, first_draft.content),
        (Err(CognitiveStoreError::Conflict(_)), Ok(receipt)) => (receipt, second_draft.content),
        outcomes => panic!("expected one committed identity and one conflict: {outcomes:?}"),
    };
    let rows: Vec<(String, i64, Vec<u8>)> =
        sqlx::query_as("SELECT source_id, source_revision, content FROM source_ledger")
            .fetch_all(&first.pool)
            .await
            .expect("committed source rows");
    assert_eq!(
        rows,
        vec![(
            committed.source_id.as_str().to_string(),
            1,
            expected_content
        )]
    );
}

#[tokio::test]
async fn source_acknowledgement_retry_survives_wal_reader_and_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(82);
    let owner_layout = layout(&temp, &owner);
    let writer = CognitiveStore::open(&owner_layout).await.expect("writer");
    let access = CognitiveAccess::agent_private(owner);
    let draft = source(
        CognitiveScope::AgentPrivate,
        "retry-operation",
        "durable payload",
    );
    let committed = writer.append_source(&access, &draft).await.expect("commit");
    let wal_path = writer.path().with_extension("sqlite3-wal");
    assert!(std::fs::metadata(wal_path).expect("live WAL").len() > 0);

    // Keep the first pool alive so this handle must honor the committed WAL.
    let reader = CognitiveStore::open(&owner_layout)
        .await
        .expect("WAL reopen");
    assert_eq!(
        reader
            .append_source(&access, &draft)
            .await
            .expect("lost-ack retry"),
        committed
    );
    writer.pool.close().await;
    reader.pool.close().await;
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("closed-store reopen");
    assert_eq!(
        reopened
            .append_source(&access, &draft)
            .await
            .expect("reopen retry"),
        committed
    );
    let rows: Vec<Vec<u8>> = sqlx::query_scalar("SELECT content FROM source_ledger")
        .fetch_all(&reopened.pool)
        .await
        .expect("source rows after retries");
    assert_eq!(rows, vec![draft.content]);
}

#[tokio::test]
async fn competing_memory_corrections_rollback_the_losing_source() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(83);
    let first = seeded_projection_store(&temp, &owner).await;
    let second = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("second writer");
    let access = CognitiveAccess::agent_private(owner);
    let memory_id = StableMemoryId::for_key(
        first.owner_agent_id(),
        &CognitiveScope::AgentPrivate,
        "projection-integrity-memory",
    );
    let first_source = source(
        CognitiveScope::AgentPrivate,
        "correction-a",
        "first correction",
    );
    let second_source = source(
        CognitiveScope::AgentPrivate,
        "correction-b",
        "second correction",
    );
    let first_revision = MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: "first correction".to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 200,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    };
    let mut second_revision = first_revision.clone();
    second_revision.content = "second correction".to_string();
    let facts = KgFactSetDraft::default();
    let (first_result, second_result) = tokio::join!(
        first.correct_with_kg(
            &access,
            &memory_id,
            1,
            &first_source,
            &first_revision,
            &facts
        ),
        second.correct_with_kg(
            &access,
            &memory_id,
            1,
            &second_source,
            &second_revision,
            &facts
        ),
    );
    let winner = match (first_result, second_result) {
        (Ok(receipt), Err(CognitiveStoreError::Conflict(_)))
        | (Err(CognitiveStoreError::Conflict(_)), Ok(receipt)) => receipt,
        outcomes => panic!("expected one committed correction and one conflict: {outcomes:?}"),
    };
    assert_eq!(
        first
            .latest_memory(&access, &memory_id)
            .await
            .expect("current head"),
        winner.memory
    );
    let counts: (i64, i64, i64) = sqlx::query_as(
        "SELECT (SELECT COUNT(*) FROM source_ledger),
                (SELECT COUNT(*) FROM memory_revisions),
                (SELECT COUNT(*) FROM kg_projection_generation_receipts)",
    )
    .fetch_one(&first.pool)
    .await
    .expect("committed row counts");
    assert_eq!(counts, (2, 2, 2));
}

#[tokio::test]
async fn projection_failure_rolls_back_source_memory_and_facts_before_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(84);
    let owner_layout = layout(&temp, &owner);
    let store = seeded_projection_store(&temp, &owner).await;
    let access = CognitiveAccess::agent_private(owner);
    let count_query = "SELECT (SELECT COUNT(*) FROM source_ledger),
                             (SELECT COUNT(*) FROM memory_revisions),
                             (SELECT COUNT(*) FROM memory_citations),
                             (SELECT COUNT(*) FROM memory_heads),
                             (SELECT COUNT(*) FROM memory_fts),
                             (SELECT COUNT(*) FROM kg_revision_fact_sets),
                             (SELECT COUNT(*) FROM kg_projection_generation_receipts)";
    let before: (i64, i64, i64, i64, i64, i64, i64) = sqlx::query_as(count_query)
        .fetch_one(&store.pool)
        .await
        .expect("predecessor counts");
    // Fail after source, revision, citations, FTS and fact insertion, while the
    // same owner transaction still contains all of the tentative changes.
    sqlx::query(
        "CREATE TRIGGER test_abort_projection BEFORE INSERT ON kg_projection_generation_receipts
         BEGIN SELECT RAISE(ABORT, 'injected publication failure'); END",
    )
    .execute(&store.pool)
    .await
    .expect("install fault");
    let failed = store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "failed-publication",
                "uncommitted fact",
            ),
            &MemoryDraft {
                stable_key: "failed-publication".to_string(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "uncommitted fact".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 200,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect_err("injected publication failure");
    assert!(
        matches!(failed, CognitiveStoreError::Unavailable(message) if message.contains("injected publication failure"))
    );
    sqlx::query("DROP TRIGGER test_abort_projection")
        .execute(&store.pool)
        .await
        .expect("remove fault");
    let after: (i64, i64, i64, i64, i64, i64, i64) = sqlx::query_as(count_query)
        .fetch_one(&store.pool)
        .await
        .expect("post-failure counts");
    assert_eq!(after, before);
    store.pool.close().await;
    let reopened = CognitiveStore::open(&owner_layout)
        .await
        .expect("reopen predecessor");
    let recovered: (i64, i64, i64, i64, i64, i64, i64) = sqlx::query_as(count_query)
        .fetch_one(&reopened.pool)
        .await
        .expect("recovered counts");
    assert_eq!(recovered, before);
}

#[tokio::test]
async fn h7_trajectory_schema_is_bound_and_append_only() {
    let temp = TempDir::new().expect("H7 trajectory temp dir");
    let owner = agent_id(3);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("H7 trajectory store");
    let digest = "a".repeat(64);
    sqlx::query(
        "INSERT INTO cognitive_h7_trajectory_events (
            owner_agent_id, trajectory_id, event_seq, event_id, occurrence_key,
            event_kind, turn_id, causal_parent_sha256, causal_parent_seq,
            receipt_sha256, outcome, reward_bps, safety_ok, terminal,
            propensity_json, support_json, metadata_json, reason,
            external_effect_executed, kg_write_authority, production_caller,
            lease_id, lease_head_sha256, authority_epoch, owner_epoch, generation,
            fencing_token_sha256, state_digest, policy_digest, model_receipt_digest,
            payload_json, payload_sha256, previous_sha256, event_sha256,
            recorded_at_unix_seconds
         ) VALUES (?, ?, 1, ?, ?, ?, ?, NULL, NULL, ?, ?, 0, 1, 0,
                   NULL, NULL, '{}', 'not_applicable', 0, 0, 0, ?, ?, 1, 1, 1,
                   ?, ?, ?, ?, ?, ?, ?, ?, 1)",
    )
    .bind(owner.as_str())
    .bind("trajectory:test")
    .bind("event:test:1")
    .bind("occurrence:test:1")
    .bind("turn_start")
    .bind("turn:test:1")
    .bind(&digest)
    .bind("observed")
    .bind("lease:test")
    .bind(&digest)
    .bind(&digest)
    .bind(&digest)
    .bind(&digest)
    .bind(&digest)
    .bind("{}")
    .bind(&digest)
    .bind(&digest)
    .bind(&digest)
    .execute(&store.pool)
    .await
    .expect("valid H7 trajectory row");
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM cognitive_h7_trajectory_events",)
            .fetch_one(&store.pool)
            .await
            .expect("H7 trajectory row count"),
        1
    );

    let feedback_error = sqlx::query(
        "INSERT INTO cognitive_h7_trajectory_events (
            owner_agent_id, trajectory_id, event_seq, event_id, occurrence_key,
            event_kind, turn_id, causal_parent_sha256, causal_parent_seq,
            receipt_sha256, outcome, reward_bps, safety_ok, terminal,
            propensity_json, support_json, metadata_json, reason,
            external_effect_executed, kg_write_authority, production_caller,
            lease_id, lease_head_sha256, authority_epoch, owner_epoch, generation,
            fencing_token_sha256, state_digest, policy_digest, model_receipt_digest,
            payload_json, payload_sha256, previous_sha256, event_sha256,
            recorded_at_unix_seconds
         ) SELECT owner_agent_id, 'trajectory:guard-feedback', 1,
            'event:guard-feedback', 'occurrence:guard-feedback', 'feedback',
            turn_id, NULL, NULL, receipt_sha256, outcome, 0, safety_ok, 0,
            propensity_json, support_json, metadata_json, reason, 0, 0, 0,
            lease_id, lease_head_sha256, authority_epoch, owner_epoch, generation,
            fencing_token_sha256, state_digest, policy_digest, model_receipt_digest,
            payload_json, payload_sha256, previous_sha256, event_sha256,
            recorded_at_unix_seconds
         FROM cognitive_h7_trajectory_events
         WHERE trajectory_id = 'trajectory:test'",
    )
    .execute(&store.pool)
    .await
    .expect_err("untyped H7 feedback must be rejected by the schema guard");
    assert!(
        feedback_error
            .to_string()
            .contains("H7-LQ trajectory rows require typed observation provenance")
    );

    let update_error = sqlx::query(
        "UPDATE cognitive_h7_trajectory_events
         SET outcome = 'tampered' WHERE owner_agent_id = ?",
    )
    .bind(owner.as_str())
    .execute(&store.pool)
    .await
    .expect_err("H7 trajectory rows must be immutable");
    assert!(
        update_error
            .to_string()
            .contains("H7 trajectory events are immutable")
    );

    let delete_error = sqlx::query("DELETE FROM cognitive_h7_trajectory_events")
        .execute(&store.pool)
        .await
        .expect_err("H7 trajectory rows must not be deleted");
    assert!(
        delete_error
            .to_string()
            .contains("H7 trajectory events are immutable")
    );
}

async fn seeded_projection_store(
    temp: &TempDir,
    owner: &codex_hepta_contracts::AgentId,
) -> CognitiveStore {
    let store = CognitiveStore::open(&layout(temp, owner))
        .await
        .expect("seed store");
    let content = "Ada contributes to the analytical engine.";
    store
        .remember_with_kg(
            &CognitiveAccess::agent_private(owner.clone()),
            &source(
                CognitiveScope::AgentPrivate,
                "projection-integrity-source",
                content,
            ),
            &MemoryDraft {
                stable_key: "projection-integrity-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: content.to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            },
            &KgFactSetDraft {
                entities: vec![
                    KgEntityFactDraft {
                        key: "ada".to_string(),
                        entity_type: "person".to_string(),
                        label: "Ada Lovelace".to_string(),
                    },
                    KgEntityFactDraft {
                        key: "engine".to_string(),
                        entity_type: "project".to_string(),
                        label: "Analytical Engine".to_string(),
                    },
                ],
                relations: vec![KgRelationFactDraft {
                    key: "ada-engine".to_string(),
                    from_entity_key: "ada".to_string(),
                    to_entity_key: "engine".to_string(),
                    relation: "contributes_to".to_string(),
                }],
            },
        )
        .await
        .expect("seed projection");
    store
}

fn expect_corrupt_with(error: CognitiveStoreError, needle: &str) {
    match error {
        CognitiveStoreError::Corrupt(message) => assert!(
            message.contains(needle),
            "expected corruption containing {needle:?}, got {message:?}"
        ),
        other => panic!("expected corruption containing {needle:?}, got {other}"),
    }
}

#[tokio::test]
async fn reopen_rejects_foreign_owned_rows_inside_agent_local_store() {
    let temp = TempDir::new().expect("foreign-owner temp dir");
    let owner = agent_id(79);
    let foreign_owner = agent_id(80);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("owner store");
    let content = b"foreign source row";
    sqlx::query(
        "INSERT INTO source_ledger (
            source_id, source_revision, owner_agent_id, scope_kind,
            workspace_sha256, source_kind, content, content_sha256,
            observed_at_unix_seconds, recorded_at_unix_seconds
         ) VALUES (?, 1, ?, 'agent_private', NULL,
                   'explicit_memory_directive', ?, ?, 100, 101)",
    )
    .bind(format!("source:v1:{}", "f".repeat(64)))
    .bind(foreign_owner.as_str())
    .bind(content.as_slice())
    .bind(Sha256Digest::for_bytes(content).as_str())
    .execute(&store.pool)
    .await
    .expect("inject foreign-owned source row");
    store.pool.close().await;
    drop(store);

    let error = match CognitiveStore::open(&layout(&temp, &owner)).await {
        Ok(_) => panic!("foreign-owned row must fail reopen"),
        Err(error) => error,
    };
    expect_corrupt_with(error, "foreign-owned source or memory rows");
}

#[tokio::test]
async fn reopen_recomputes_current_projection_digests_and_exact_fts_rows() {
    let input_temp = TempDir::new().expect("input temp dir");
    let input_owner = agent_id(81);
    let input_store = seeded_projection_store(&input_temp, &input_owner).await;
    let mut input_connection = input_store
        .pool
        .acquire()
        .await
        .expect("input tamper connection");
    let receipt_trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema
         WHERE name = 'kg_projection_generation_receipts_no_update'",
    )
    .fetch_one(&mut *input_connection)
    .await
    .expect("receipt trigger SQL");
    sqlx::query("DROP TRIGGER kg_projection_generation_receipts_no_update")
        .execute(&mut *input_connection)
        .await
        .expect("drop receipt trigger");
    sqlx::query(
        "UPDATE kg_projection_generation_receipts
         SET input_heads_sha256 = ?",
    )
    .bind(Sha256Digest::for_bytes(b"tampered input heads").as_str())
    .execute(&mut *input_connection)
    .await
    .expect("tamper input digest");
    sqlx::query(sqlx::AssertSqlSafe(receipt_trigger.as_str()))
        .execute(&mut *input_connection)
        .await
        .expect("restore receipt trigger");
    drop(input_connection);
    input_store.pool.close().await;
    drop(input_store);
    let input_error = match CognitiveStore::open(&layout(&input_temp, &input_owner)).await {
        Ok(_) => panic!("tampered input digest must fail reopen"),
        Err(error) => error,
    };
    expect_corrupt_with(input_error, "input-head digest");

    let output_temp = TempDir::new().expect("output temp dir");
    let output_owner = agent_id(82);
    let output_store = seeded_projection_store(&output_temp, &output_owner).await;
    let mut output_connection = output_store
        .pool
        .acquire()
        .await
        .expect("output tamper connection");
    let receipt_trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema
         WHERE name = 'kg_projection_generation_receipts_no_update'",
    )
    .fetch_one(&mut *output_connection)
    .await
    .expect("receipt trigger SQL");
    sqlx::query("DROP TRIGGER kg_projection_generation_receipts_no_update")
        .execute(&mut *output_connection)
        .await
        .expect("drop receipt trigger");
    sqlx::query(
        "UPDATE kg_projection_generation_receipts
         SET output_sha256 = ?",
    )
    .bind(Sha256Digest::for_bytes(b"tampered output").as_str())
    .execute(&mut *output_connection)
    .await
    .expect("tamper output digest");
    sqlx::query(sqlx::AssertSqlSafe(receipt_trigger.as_str()))
        .execute(&mut *output_connection)
        .await
        .expect("restore receipt trigger");
    drop(output_connection);
    output_store.pool.close().await;
    drop(output_store);
    let output_error = match CognitiveStore::open(&layout(&output_temp, &output_owner)).await {
        Ok(_) => panic!("tampered output digest must fail reopen"),
        Err(error) => error,
    };
    expect_corrupt_with(output_error, "output digest");

    let fts_temp = TempDir::new().expect("FTS temp dir");
    let fts_owner = agent_id(83);
    let fts_store = seeded_projection_store(&fts_temp, &fts_owner).await;
    sqlx::query("UPDATE kg_entity_fts SET label = label || ' tampered'")
        .execute(&fts_store.pool)
        .await
        .expect("tamper FTS payload without changing its row count");
    fts_store.pool.close().await;
    drop(fts_store);
    let fts_error = match CognitiveStore::open(&layout(&fts_temp, &fts_owner)).await {
        Ok(_) => panic!("tampered FTS payload must fail reopen"),
        Err(error) => error,
    };
    expect_corrupt_with(fts_error, "FTS rows");
}

#[tokio::test]
async fn reopen_rejects_0008_migration_checksum_drift_without_repair() {
    let temp = TempDir::new().expect("migration checksum temp dir");
    let owner = agent_id(85);
    let agent_layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&agent_layout)
        .await
        .expect("open cognitive store");

    let original_checksum: Vec<u8> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations WHERE version = 8")
            .fetch_one(&store.pool)
            .await
            .expect("read migration 0008 checksum");
    assert_eq!(
        original_checksum.len(),
        48,
        "SQLx 0.9 migration checksums are SHA-384"
    );

    sqlx::query("UPDATE _sqlx_migrations SET checksum = ? WHERE version = 8")
        .bind(vec![0_u8; 48])
        .execute(&store.pool)
        .await
        .expect("tamper migration 0008 checksum in isolated fixture");

    let error = match CognitiveStore::open(&agent_layout).await {
        Ok(_) => panic!("migration 0008 checksum drift must fail closed"),
        Err(error) => error,
    };
    expect_corrupt_with(
        error,
        "migration 8 was previously applied but has been modified",
    );

    let checksum_after_failed_open: Vec<u8> =
        sqlx::query_scalar("SELECT checksum FROM _sqlx_migrations WHERE version = 8")
            .fetch_one(&store.pool)
            .await
            .expect("read migration checksum after failed reopen");
    assert_eq!(checksum_after_failed_open, vec![0_u8; 48]);
    store.pool.close().await;
}

#[tokio::test]
async fn v2_fixture_migrates_forward_preserving_memory_and_revoking_legacy_projection() {
    let temp = TempDir::new().expect("migration temp dir");
    let owner = agent_id(84);
    let agent_layout = layout(&temp, &owner);
    let pool = crate::cognitive_store::open_v2_test_pool(&agent_layout)
        .await
        .expect("v2 store");
    let source_id = format!("source:v1:{}", "1".repeat(64));
    let memory_id = format!("memory:v1:{}", "2".repeat(64));
    let content = "legacy cited memory";
    let content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
    sqlx::query(
        "INSERT INTO source_ledger (
            source_id, source_revision, owner_agent_id, scope_kind,
            workspace_sha256, source_kind, content, content_sha256,
            observed_at_unix_seconds, recorded_at_unix_seconds
         ) VALUES (?, 1, ?, 'agent_private', NULL,
                   'explicit_memory_directive', ?, ?, 100, 101)",
    )
    .bind(&source_id)
    .bind(owner.as_str())
    .bind(content.as_bytes())
    .bind(content_sha256.as_str())
    .execute(&pool)
    .await
    .expect("legacy source");
    sqlx::query(
        "INSERT INTO memory_revisions (
            memory_id, revision, owner_agent_id, scope_kind,
            workspace_sha256, content, content_sha256, verification,
            lifecycle, tombstone_reason, valid_from_unix_seconds,
            valid_to_unix_seconds, supersedes_revision,
            recorded_at_unix_seconds
         ) VALUES (?, 1, ?, 'agent_private', NULL, ?, ?, 'verified',
                   'active', NULL, 100, NULL, NULL, 101)",
    )
    .bind(&memory_id)
    .bind(owner.as_str())
    .bind(content)
    .bind(content_sha256.as_str())
    .execute(&pool)
    .await
    .expect("legacy memory revision");
    sqlx::query(
        "INSERT INTO memory_citations (
            memory_id, memory_revision, ordinal, source_id, source_revision
         ) VALUES (?, 1, 0, ?, 1)",
    )
    .bind(&memory_id)
    .bind(&source_id)
    .execute(&pool)
    .await
    .expect("legacy citation");
    sqlx::query("INSERT INTO memory_heads (memory_id, revision) VALUES (?, 1)")
        .bind(&memory_id)
        .execute(&pool)
        .await
        .expect("legacy head");
    sqlx::query("INSERT INTO memory_fts (memory_id, revision, content) VALUES (?, 1, ?)")
        .bind(&memory_id)
        .bind(content)
        .execute(&pool)
        .await
        .expect("legacy memory FTS");
    sqlx::query(
        "INSERT INTO kg_projection (projection_scope, generation)
         VALUES ('agent_private', 7)",
    )
    .execute(&pool)
    .await
    .expect("legacy projection pointer");
    sqlx::query(
        "INSERT INTO kg_nodes (
            projection_scope, generation, node_id, entity_type, label,
            valid_from_unix_seconds, valid_to_unix_seconds, memory_id,
            memory_revision, source_id, source_revision
         ) VALUES ('agent_private', 7, 'legacy-node', 'person', 'Legacy Ada',
                   100, NULL, ?, 1, ?, 1)",
    )
    .bind(&memory_id)
    .bind(&source_id)
    .execute(&pool)
    .await
    .expect("legacy KG node");
    sqlx::query(
        "INSERT INTO kg_entity_fts (
            projection_scope, generation, node_id, entity_type, label
         ) VALUES ('agent_private', 7, 'legacy-node', 'person', 'Legacy Ada')",
    )
    .execute(&pool)
    .await
    .expect("legacy KG FTS");
    pool.close().await;
    drop(pool);

    let migrated = CognitiveStore::open(&agent_layout)
        .await
        .expect("v2 fixture migrates through v3 and verifies");
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&migrated.pool)
            .await
            .expect("preserved memory"),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM memory_citations")
            .fetch_one(&migrated.pool)
            .await
            .expect("preserved citation"),
        1
    );
    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM memory_heads WHERE memory_id = ? AND revision = 1",
        )
        .bind(&memory_id)
        .fetch_one(&migrated.pool)
        .await
        .expect("preserved head"),
        1
    );
    let legacy_header = sqlx::query(
        "SELECT extractor_contract, fact_set_sha256, source_id,
                source_revision, entity_count, relation_count
         FROM kg_revision_fact_sets
         WHERE memory_id = ? AND memory_revision = 1",
    )
    .bind(&memory_id)
    .fetch_one(&migrated.pool)
    .await
    .expect("legacy zero-fact header");
    assert_eq!(
        legacy_header
            .try_get::<String, _>("extractor_contract")
            .expect("extractor contract"),
        "legacy_pre_g3_empty_v1"
    );
    assert_eq!(
        legacy_header
            .try_get::<String, _>("fact_set_sha256")
            .expect("fact digest"),
        "6eb8599ab837d22123cda62453adb0c22a20fb1986308de666507188e79297af"
    );
    assert_eq!(
        legacy_header
            .try_get::<String, _>("source_id")
            .expect("source id"),
        source_id
    );
    assert_eq!(
        legacy_header
            .try_get::<i64, _>("source_revision")
            .expect("source revision"),
        1
    );
    assert_eq!(
        legacy_header
            .try_get::<i64, _>("entity_count")
            .expect("entity count"),
        0
    );
    assert_eq!(
        legacy_header
            .try_get::<i64, _>("relation_count")
            .expect("relation count"),
        0
    );
    for table in ["kg_projection", "kg_nodes", "kg_edges", "kg_entity_fts"] {
        let count: i64 =
            sqlx::query_scalar(sqlx::AssertSqlSafe(format!("SELECT COUNT(*) FROM {table}")))
                .fetch_one(&migrated.pool)
                .await
                .expect("legacy projection revoked");
        assert_eq!(count, 0, "legacy {table} rows must be revoked");
    }
    assert_eq!(
        sqlx::query_scalar::<_, String>(
            "SELECT group_concat(version, ',') FROM _sqlx_migrations ORDER BY version",
        )
        .fetch_one(&migrated.pool)
        .await
        .expect("migration ledger"),
        "1,2,3,4,5,6,7,8,9,10"
    );
}
