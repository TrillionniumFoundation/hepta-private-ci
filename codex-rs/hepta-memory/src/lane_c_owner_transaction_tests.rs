use super::*;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::SourceRevisionId;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::memory_revision;
use crate::cognitive_test_support::source;
use crate::cognitive_test_support::workspace;
use pretty_assertions::assert_eq;
use std::time::Duration;
use tempfile::TempDir;

struct Fixture {
    store: CognitiveStore,
    access: CognitiveAccess,
    scope: CognitiveScope,
    memory: MemoryRevisionRecord,
    citation: SourceRevisionId,
    _temp: TempDir,
}

async fn owner_fixture(
    content: &str,
    scope: CognitiveScope,
    valid_to_unix_seconds: Option<i64>,
) -> Fixture {
    let temp = TempDir::new().expect("temporary owner");
    let owner = agent_id(/*suffix*/ 61);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("owner store");
    let access = match &scope {
        CognitiveScope::AgentPrivate => CognitiveAccess::agent_private(owner),
        CognitiveScope::WorkspacePrivate { workspace_sha256 } => {
            CognitiveAccess::workspace_private(owner, workspace_sha256.clone())
        }
    };
    let citation = store
        .append_source(&access, &source(scope.clone(), "owner-tx-source", content))
        .await
        .expect("source");
    let mut revision = memory_revision(scope.clone(), content, citation.clone());
    revision.valid_to_unix_seconds = valid_to_unix_seconds;
    let memory = store
        .create_memory(
            &access,
            &MemoryDraft {
                stable_key: "owner-tx-memory".to_string(),
                revision,
            },
        )
        .await
        .expect("memory");
    Fixture {
        store,
        access,
        scope,
        memory,
        citation,
        _temp: temp,
    }
}

// Qualification-only construction. Runtime exposes only begin_read; a future
// compact writer must add its own authority and fenced publication composition.
async fn write_locked(fixture: &Fixture) -> LaneCOwnerTransaction<'_> {
    fixture
        .store
        .authorize(&fixture.access, &fixture.scope)
        .expect("scope authorized");
    let transaction = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("same-owner write transaction");
    LaneCOwnerTransaction {
        store: &fixture.store,
        access: fixture.access.clone(),
        scope: fixture.scope.clone(),
        transaction,
    }
}

#[tokio::test]
async fn bound_read_freezes_the_owner_and_authorized_scope_and_matches_public_reads() {
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace("bound-a"),
    };
    let fixture = owner_fixture(
        "owner one",
        scope.clone(),
        /*valid_to_unix_seconds*/ None,
    )
    .await;
    let other = owner_fixture(
        "owner two",
        scope.clone(),
        /*valid_to_unix_seconds*/ None,
    )
    .await;
    let expected = fixture
        .store
        .lane_c_lineage(&fixture.access, &scope, /*now_unix_seconds*/ 150)
        .await
        .expect("public lineage");
    let expected_snapshot = fixture
        .store
        .lane_c_snapshot(&fixture.access, &scope, /*now_unix_seconds*/ 150)
        .await
        .expect("public snapshot");
    let mut caller_access = fixture.access.clone();
    let mut caller_scope = scope.clone();
    let mut transaction = LaneCOwnerTransaction::begin_read(
        &fixture.store,
        &caller_access,
        &caller_scope,
        /*now_unix_seconds*/ 150,
    )
    .await
    .expect("bound read");
    caller_access = CognitiveAccess::agent_private(agent_id(/*suffix*/ 62));
    caller_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace("bound-b"),
    };
    assert_eq!(
        transaction
            .snapshot(/*now_unix_seconds*/ 150)
            .await
            .expect("bound snapshot"),
        expected_snapshot
    );
    assert_eq!(
        transaction
            .lineage(/*now_unix_seconds*/ 150)
            .await
            .expect("bound lineage"),
        expected
    );
    transaction.commit().await.expect("read commit");
    let other_cut = other
        .store
        .lane_c_lineage(&other.access, &scope, /*now_unix_seconds*/ 150)
        .await
        .expect("distinct physical owner cut");
    assert_ne!(
        expected.source_binding_digest(),
        other_cut.source_binding_digest()
    );
    assert!(matches!(
        LaneCOwnerTransaction::begin_read(
            &fixture.store,
            &caller_access,
            &caller_scope,
            /*now_unix_seconds*/ -1,
        )
        .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    assert!(matches!(
        LaneCOwnerTransaction::begin_read(
            &fixture.store,
            &fixture.access,
            &caller_scope,
            /*now_unix_seconds*/ -1,
        )
        .await,
        Err(CognitiveStoreError::AccessDenied(_))
    ));
    assert!(matches!(LaneCOwnerTransaction::begin_read(
        &fixture.store, &fixture.access, &fixture.scope, /*now_unix_seconds*/ -1,
    ).await, Err(CognitiveStoreError::Invalid(message)) if message == "negative snapshot time"));
}

#[tokio::test]
async fn owner_projection_sees_uncommitted_correction_and_tombstone_then_rollback() {
    let fixture = owner_fixture(
        "original",
        CognitiveScope::AgentPrivate,
        /*valid_to_unix_seconds*/ None,
    )
    .await;
    let expected = fixture
        .store
        .lane_c_lineage(
            &fixture.access,
            &fixture.scope,
            /*now_unix_seconds*/ 150,
        )
        .await
        .expect("original lineage");
    let mut transaction = write_locked(&fixture).await;
    let correction = memory_revision(fixture.scope.clone(), "corrected", fixture.citation.clone());
    fixture
        .store
        .revise_memory_revision_tx(
            &mut transaction.transaction,
            &transaction.access,
            &fixture.memory.id.memory_id,
            /*expected_revision*/ 1,
            &correction,
        )
        .await
        .expect("uncommitted correction");
    let corrected = transaction
        .lineage(/*now_unix_seconds*/ 150)
        .await
        .expect("own write visible");
    assert_eq!(
        corrected
            .records()
            .iter()
            .map(|record| record.revision.get())
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    assert_eq!(
        corrected.current_heads()[0].content_digest,
        Digest32::of_bytes(b"corrected")
    );
    assert_eq!(
        transaction
            .snapshot(/*now_unix_seconds*/ 150)
            .await
            .expect("same transaction heads")
            .snapshot()
            .records
            .as_slice(),
        corrected.current_heads()
    );
    assert!(matches!(
        transaction
            .revalidate_lineage(&expected, /*now_unix_seconds*/ 150)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let mut tombstone =
        memory_revision(fixture.scope.clone(), "withdrawn", fixture.citation.clone());
    tombstone.lifecycle = MemoryLifecycleState::Tombstoned {
        reason: "withdrawn in transaction".to_string(),
    };
    fixture
        .store
        .revise_memory_revision_tx(
            &mut transaction.transaction,
            &transaction.access,
            &fixture.memory.id.memory_id,
            /*expected_revision*/ 2,
            &tombstone,
        )
        .await
        .expect("uncommitted tombstone");
    let deleted = transaction
        .lineage(/*now_unix_seconds*/ 150)
        .await
        .expect("own tombstone visible");
    assert_eq!(
        deleted
            .records()
            .iter()
            .map(|record| record.revision.get())
            .collect::<Vec<_>>(),
        vec![1, 2, 3]
    );
    assert_eq!(deleted.current_heads()[0].state, RecordState::Tombstone);
    assert_ne!(
        deleted.source_binding_digest(),
        corrected.source_binding_digest()
    );
    transaction
        .transaction
        .rollback()
        .await
        .expect("rollback owner changes");
    assert_eq!(
        fixture
            .store
            .lane_c_lineage(
                &fixture.access,
                &fixture.scope,
                /*now_unix_seconds*/ 150
            )
            .await
            .expect("rolled back lineage"),
        expected
    );
    assert_eq!(
        fixture
            .store
            .latest_memory(&fixture.access, &fixture.memory.id.memory_id)
            .await
            .expect("original memory restored"),
        fixture.memory
    );
}

#[tokio::test]
async fn caller_owned_write_lock_serializes_projection_against_external_correction() {
    let fixture = owner_fixture(
        "before lock",
        CognitiveScope::AgentPrivate,
        /*valid_to_unix_seconds*/ None,
    )
    .await;
    let expected = fixture
        .store
        .lane_c_lineage(
            &fixture.access,
            &fixture.scope,
            /*now_unix_seconds*/ 150,
        )
        .await
        .expect("original cut");
    let mut transaction = write_locked(&fixture).await;
    let mut contender = fixture
        .store
        .pool
        .acquire()
        .await
        .expect("second owner connection");
    let busy_timeout: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
        .fetch_one(&mut *contender)
        .await
        .expect("timeout");
    sqlx::query("PRAGMA busy_timeout = 0")
        .execute(&mut *contender)
        .await
        .expect("fail-fast contender");
    let blocked = sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *contender)
        .await
        .expect_err("write lock is held");
    assert!(
        matches!(blocked, sqlx::Error::Database(error) if error.code().and_then(|code| code.parse::<i32>().ok()).is_some_and(|code| matches!(code & 255, 5 | 6)))
    );
    assert_eq!(
        transaction
            .revalidate_lineage(&expected, /*now_unix_seconds*/ 150)
            .await
            .expect("same locked cut"),
        expected
    );
    transaction.commit().await.expect("release write lock");
    // PRAGMA assignments do not accept a bound parameter. This value is the
    // integer read from the same connection, not caller-supplied SQL text.
    let mut restore_timeout = sqlx::QueryBuilder::<Sqlite>::new("PRAGMA busy_timeout = ");
    restore_timeout.push(busy_timeout);
    restore_timeout
        .build()
        .execute(&mut *contender)
        .await
        .expect("restore timeout");
    drop(contender);
    fixture
        .store
        .correct_memory(
            &fixture.access,
            &fixture.memory.id.memory_id,
            /*expected_revision*/ 1,
            &memory_revision(
                fixture.scope.clone(),
                "after lock",
                fixture.citation.clone(),
            ),
        )
        .await
        .expect("external correction after unlock");
    let mut current = LaneCOwnerTransaction::begin_read(
        &fixture.store,
        &fixture.access,
        &fixture.scope,
        /*now_unix_seconds*/ 150,
    )
    .await
    .expect("new read transaction");
    assert!(matches!(
        current
            .revalidate_lineage(&expected, /*now_unix_seconds*/ 150)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    current.commit().await.expect("new cut commit");
}

#[tokio::test]
async fn same_transaction_revalidation_recomputes_time_and_current_head_eligibility() {
    let fixture = owner_fixture(
        "expires",
        CognitiveScope::AgentPrivate,
        /*valid_to_unix_seconds*/ Some(200),
    )
    .await;
    let expected = fixture
        .store
        .lane_c_lineage(
            &fixture.access,
            &fixture.scope,
            /*now_unix_seconds*/ 150,
        )
        .await
        .expect("eligible before expiry");
    let mut transaction = write_locked(&fixture).await;
    let valid = transaction
        .revalidate_lineage(&expected, /*now_unix_seconds*/ 199)
        .await
        .expect("still eligible");
    assert_eq!(valid.records(), expected.records());
    assert_eq!(
        valid.source_binding_digest(),
        expected.source_binding_digest()
    );
    assert!(matches!(
        transaction
            .revalidate_lineage(&expected, /*now_unix_seconds*/ 200)
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let expired = transaction
        .lineage(/*now_unix_seconds*/ 200)
        .await
        .expect("expired head excluded");
    assert_eq!(
        (
            expired.source_head_count(),
            expired.excluded_head_count(),
            expired.records(),
            expired.current_heads()
        ),
        (1, 1, &[][..], &[][..])
    );
    let mut provisional =
        memory_revision(fixture.scope.clone(), "pending", fixture.citation.clone());
    provisional.verification = MemoryVerification::Provisional;
    fixture
        .store
        .revise_memory_revision_tx(
            &mut transaction.transaction,
            &transaction.access,
            &fixture.memory.id.memory_id,
            /*expected_revision*/ 1,
            &provisional,
        )
        .await
        .expect("uncommitted unverified head");
    let excluded = transaction
        .lineage(/*now_unix_seconds*/ 200)
        .await
        .expect("pending head excludes its ancestors");
    assert_eq!(
        (
            excluded.source_head_count(),
            excluded.excluded_head_count(),
            excluded.records(),
            excluded.current_heads()
        ),
        (1, 1, &[][..], &[][..])
    );
    assert_ne!(
        excluded.source_head_manifest_digest(),
        expired.source_head_manifest_digest()
    );
    assert!(
        matches!(transaction.revalidate_lineage(&expected, /*now_unix_seconds*/ 149).await, Err(CognitiveStoreError::Invalid(message)) if message == "lineage clock regressed")
    );
    transaction
        .transaction
        .rollback()
        .await
        .expect("rollback pending head");
    let foreign = CognitiveAccess::agent_private(agent_id(/*suffix*/ 62));
    assert!(matches!(fixture.store.revalidate_lane_c_lineage(
        &foreign, &fixture.scope, &expected, /*now_unix_seconds*/ 149,
    ).await, Err(CognitiveStoreError::Invalid(message)) if message == "lineage clock regressed"));
}

#[tokio::test]
async fn default_read_transaction_is_a_historical_cut_and_new_transaction_detects_wal_write() {
    let fixture = owner_fixture(
        "original cut",
        CognitiveScope::AgentPrivate,
        /*valid_to_unix_seconds*/ None,
    )
    .await;
    let mut transaction = LaneCOwnerTransaction::begin_read(
        &fixture.store,
        &fixture.access,
        &fixture.scope,
        /*now_unix_seconds*/ 150,
    )
    .await
    .expect("default read");
    let pinned = transaction
        .lineage(/*now_unix_seconds*/ 150)
        .await
        .expect("pinned owner cut");
    tokio::time::timeout(
        Duration::from_secs(/*secs*/ 30),
        fixture.store.correct_memory(
            &fixture.access,
            &fixture.memory.id.memory_id,
            /*expected_revision*/ 1,
            &memory_revision(
                fixture.scope.clone(),
                "new WAL cut",
                fixture.citation.clone(),
            ),
        ),
    )
    .await
    .expect("WAL writer can complete beside default reader")
    .expect("external correction");
    assert_eq!(
        transaction
            .revalidate_lineage(&pinned, /*now_unix_seconds*/ 150)
            .await
            .expect("same historical snapshot"),
        pinned
    );
    transaction.commit().await.expect("finish historical read");
    assert!(matches!(
        fixture
            .store
            .revalidate_lane_c_lineage(
                &fixture.access,
                &fixture.scope,
                &pinned,
                /*now_unix_seconds*/ 150,
            )
            .await,
        Err(CognitiveStoreError::Conflict(_))
    ));
}
