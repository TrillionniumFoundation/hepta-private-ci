use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::ForgetMemoryDraft;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

async fn seeded(
    temp: &TempDir,
    owner: &AgentId,
) -> (CognitiveStore, CognitiveAccess, MemoryRevisionRecord) {
    let store = CognitiveStore::open(&layout(temp, owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner.clone());
    let receipt = store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "recovery-source",
                "remembered fact",
            ),
            &MemoryDraft {
                stable_key: "recovery-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "remembered fact".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("seed memory");
    (store, access, receipt.memory)
}

async fn backup(store: &CognitiveStore, path: &std::path::Path) {
    // SQLite owns the consistent backup, including committed WAL state.
    sqlx::query("VACUUM INTO ?")
        .bind(path.to_str().expect("test path"))
        .execute(&store.pool)
        .await
        .expect("consistent backup");
}

#[tokio::test]
async fn exact_current_cut_survives_wal_checkpoint_and_consistent_backup() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(91);
    let (store, access, memory) = seeded(&temp, &owner).await;
    let anchor = store
        .recovery_anchor()
        .await
        .expect("trusted current witness");
    let serialized = serde_json::to_vec(&anchor).expect("host serializable witness");
    let retained: CognitiveRecoveryAnchor =
        serde_json::from_slice(&serialized).expect("retained witness");
    assert_eq!(retained, anchor);
    let backup_path = temp.path().join("current.sqlite3");
    backup(&store, &backup_path).await;
    let store_path = store.path().to_path_buf();
    store.pool.close().await;
    std::fs::copy(&backup_path, &store_path).expect("restore consistent current backup");

    let recovered = CognitiveStore::open_with_recovery(
        &layout(&temp, &owner),
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
    )
    .await
    .expect("exact current-cut recovery");
    assert_eq!(
        recovered
            .latest_memory(&access, &memory.id.memory_id)
            .await
            .expect("recovered memory"),
        memory
    );
    assert_eq!(
        recovered.recovery_anchor().await.expect("recovered cut"),
        anchor
    );
    recovered
        .append_source(
            &access,
            &source(CognitiveScope::AgentPrivate, "after-recovery", "new fact"),
        )
        .await
        .expect("recovered handle retains owner writer API");
}

#[tokio::test]
async fn pre_forget_backup_is_rejected_before_a_reader_escapes() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(92);
    let (store, access, memory) = seeded(&temp, &owner).await;
    let old_backup = temp.path().join("pre-forget.sqlite3");
    backup(&store, &old_backup).await;
    let tombstone = store
        .forget_with_kg(
            &access,
            &memory.id.memory_id,
            memory.id.revision,
            &source(
                CognitiveScope::AgentPrivate,
                "forget-source",
                "explicit forget",
            ),
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "explicit forget".to_string(),
                valid_from_unix_seconds: 200,
                citations: Vec::new(),
            },
        )
        .await
        .expect("acknowledged forget");
    let current = store
        .recovery_anchor()
        .await
        .expect("independent current witness");
    let store_path = store.path().to_path_buf();
    store.pool.close().await;
    let recovered = CognitiveStore::open_with_recovery(
        &layout(&temp, &owner),
        CognitiveRecoveryRequirement::ExactCurrentCut(&current),
    )
    .await
    .expect("current tombstone can reopen");
    assert_eq!(
        recovered
            .latest_memory(&access, &memory.id.memory_id)
            .await
            .expect("current head"),
        tombstone.memory
    );
    recovered.pool.close().await;
    std::fs::copy(old_backup, &store_path).expect("restore old backup");
    assert!(matches!(
        CognitiveStore::open_with_recovery(&layout(&temp, &owner), CognitiveRecoveryRequirement::ExactCurrentCut(&current)).await,
        Err(CognitiveStoreError::Corrupt(message)) if message.contains("current-cut mismatch")
    ));
}

#[tokio::test]
async fn lost_acknowledged_source_and_unwitnessed_successor_both_require_reconciliation() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(93);
    let (store, access, _) = seeded(&temp, &owner).await;
    let predecessor = store.recovery_anchor().await.expect("predecessor witness");
    let backup_path = temp.path().join("pre-append.sqlite3");
    backup(&store, &backup_path).await;
    store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "acknowledged-source",
                "acknowledged fact",
            ),
        )
        .await
        .expect("acknowledged source");
    let current = store.recovery_anchor().await.expect("current witness");
    let store_path = store.path().to_path_buf();
    store.pool.close().await;
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&predecessor)
        )
        .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
    std::fs::copy(backup_path, &store_path).expect("restore predecessor");
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&current)
        )
        .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
}

#[tokio::test]
async fn revoked_wrong_owner_and_tampered_witness_fail_closed() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(94);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current witness");
    store.pool.close().await;
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::Revoked
        )
        .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    let wrong_layout = layout(&temp, &agent_id(95));
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &wrong_layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor)
        )
        .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    assert!(!wrong_layout.cognitive_root().exists());
    let mut tampered = anchor.clone();
    tampered.state_digest = Sha256Digest::for_bytes(b"altered witness");
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&tampered)
        )
        .await,
        Err(CognitiveStoreError::Corrupt(_))
    ));
    let recovered = CognitiveStore::open_with_recovery(
        &layout(&temp, &owner),
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
    )
    .await
    .expect("rejected attempts preserve current store");
    assert_eq!(
        recovered
            .recovery_anchor()
            .await
            .expect("unchanged current cut"),
        anchor
    );
}

#[tokio::test]
async fn missing_database_is_not_reinitialized_by_recovery_or_existing_pool() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(96);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("retained witness");
    let store_path = store.path().to_path_buf();
    store.pool.close().await;
    std::fs::remove_file(&store_path).expect("simulate missing acknowledged database");
    assert!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        )
        .await
        .is_err()
    );
    let sqlite_home = AbsolutePathBuf::try_from(store_path.parent().expect("parent").to_path_buf())
        .expect("absolute root");
    assert!(
        SqliteConfig::from_sqlite_home(sqlite_home)
            .open_existing_durable_evidence_pool(&store_path)
            .await
            .is_err()
    );
    assert!(!store_path.exists());
}

#[tokio::test]
async fn recovery_bounds_large_rows_before_loading_payloads_and_rejects_unknown_tables() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(97);
    let (store, _, _) = seeded(&temp, &owner).await;
    let oversized_text = "x".repeat((MAX_ROW_BYTES + 1) as usize);
    sqlx::query("UPDATE _sqlx_migrations SET description = ? WHERE version = 1")
        .bind(oversized_text)
        .execute(&store.pool)
        .await
        .expect("oversized metadata fault");
    let oversized = store.recovery_anchor().await;
    assert!(
        matches!(&oversized, Err(CognitiveStoreError::Invalid(message)) if message.contains("exceeds bounds")),
        "unexpected oversized-row result: {oversized:?}"
    );

    let clean_temp = TempDir::new().expect("clean temp dir");
    let (clean, _, _) = seeded(&clean_temp, &agent_id(98)).await;
    sqlx::query("CREATE TABLE unregistered_owner_state (value TEXT)")
        .execute(&clean.pool)
        .await
        .expect("unknown table fault");
    assert!(
        matches!(clean.recovery_anchor().await, Err(CognitiveStoreError::Corrupt(message)) if message.contains("unregistered"))
    );
}

#[tokio::test]
async fn corrupt_physical_fts_segments_cannot_obtain_or_replay_a_witness() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(99);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store
        .recovery_anchor()
        .await
        .expect("trusted current witness");
    let damaged =
        sqlx::query("UPDATE memory_fts_data SET block = zeroblob(length(block)) WHERE id > 10")
            .execute(&store.pool)
            .await
            .expect("inject physical FTS segment damage");
    assert!(damaged.rows_affected() > 0);
    assert!(store.recovery_anchor().await.is_err());
    store.pool.close().await;
    assert!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        )
        .await
        .is_err()
    );
}
