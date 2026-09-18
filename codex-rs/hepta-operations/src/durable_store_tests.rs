use super::*;

use std::collections::BTreeSet;
use std::time::Duration;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("test generation")
}

fn intent(payload: &[u8]) -> OperationIntentV1 {
    OperationIntentV1 {
        scope_id: stable_id("scope:test"),
        operation_id: stable_id("operation:test:durable"),
        expected_predecessor: None,
        destination: stable_id("automation.taskflow"),
        payload_digest: Digest32::of_bytes(payload),
        owner_generation: generation(1),
    }
}

#[tokio::test]
async fn prepare_is_atomic_and_survives_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    let prepared = store.prepare_intent(&operation).await.expect("prepare");
    assert_eq!(prepared.disposition, PrepareDisposition::Inserted);
    let counts: (i64, i64) = sqlx::query_as(
        "SELECT (SELECT COUNT(*) FROM operation_ledger),
                (SELECT COUNT(*) FROM cross_owner_outbox)",
    )
    .fetch_one(&store.pool)
    .await
    .expect("counts");
    assert_eq!(counts, (1, 1));
    store.close().await;

    let reopened = DurableOperationStore::open(&path).await.expect("reopen");
    let record = reopened
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(record.state, DurableOperationState::Prepared);
    let outbox = reopened
        .outbox_status(
            &operation.destination,
            &operation.scope_id,
            &operation.operation_id,
        )
        .await
        .expect("outbox")
        .expect("outbox row");
    assert_eq!(outbox.state, DurableOutboxState::Queued);
}

#[tokio::test]
async fn exact_multiwriter_prepare_is_idempotent_and_payload_drift_conflicts() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let first = DurableOperationStore::open(&path).await.expect("open one");
    let second = DurableOperationStore::open(&path).await.expect("open two");
    let operation = intent(b"payload");
    let a = operation.clone();
    let b = operation.clone();
    let (left, right) = tokio::join!(first.prepare_intent(&a), second.prepare_intent(&b));
    let left = left.expect("left");
    let right = right.expect("right");
    assert!(matches!(
        (left.disposition, right.disposition),
        (PrepareDisposition::Inserted, PrepareDisposition::AlreadyPresent)
            | (PrepareDisposition::AlreadyPresent, PrepareDisposition::Inserted)
            | (PrepareDisposition::AlreadyPresent, PrepareDisposition::AlreadyPresent)
    ));
    let changed = intent(b"changed");
    assert!(matches!(
        first.prepare_intent(&changed).await,
        Err(DurableOperationError::Conflict(_))
    ));
}

#[tokio::test]
async fn expired_safe_lease_can_be_taken_over_by_higher_generation() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let first = DurableOperationStore::open(&path).await.expect("open one");
    let second = DurableOperationStore::open(&path).await.expect("open two");
    let operation = intent(b"payload");
    first.prepare_intent(&operation).await.expect("prepare");
    let stale = first
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_millis(1),
        )
        .await
        .expect("claim")
        .expect("claim row");
    tokio::time::sleep(Duration::from_millis(5)).await;
    let current = second
        .claim_next(
            &operation.destination,
            &stable_id("worker:two"),
            generation(2),
            Duration::from_secs(1),
        )
        .await
        .expect("takeover")
        .expect("current claim");
    assert!(current.fence > stale.fence);
    assert_eq!(current.owner_generation, generation(2));
    assert!(matches!(
        first.renew_claim(&stale, Duration::from_secs(1)).await,
        Err(DurableOperationError::StaleLease)
    ));
}

#[cfg(unix)]
fn authority_fixture(
    operation: &OperationIntentV1,
    nonce: u8,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    SignedFinalUseGrant,
    tempfile::TempDir,
) {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let signing = SigningKey::from_bytes(&[47; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_owned(),
        authority_epoch: 9,
        grant_id: format!("grant-{nonce}"),
        nonce: [nonce; 32],
        binding: operation.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("authority tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("permissions");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    (
        authority,
        SignedFinalUseGrant { grant, signature },
        directory,
    )
}

#[cfg(unix)]
#[tokio::test]
async fn crash_after_dispatch_admission_recovers_as_indeterminate_not_retryable() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_millis(1),
        )
        .await
        .expect("claim")
        .expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 5);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("authorize dispatch");
    drop(authorized);
    store.close().await;
    tokio::time::sleep(Duration::from_millis(5)).await;

    let reopened = DurableOperationStore::open(&path).await.expect("reopen");
    let record = reopened
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(record.state, DurableOperationState::Indeterminate);
    assert!(
        reopened
            .claim_next(
                &operation.destination,
                &stable_id("worker:two"),
                generation(2),
                Duration::from_secs(1),
            )
            .await
            .expect("claim query")
            .is_none()
    );
}

#[cfg(unix)]
#[tokio::test]
async fn acknowledgement_loss_stays_indeterminate_until_terminal_observer() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 6);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("authorize dispatch");
    let value = store
        .execute_authorized(authorized, |_| DispatchEffect::Dispatched {
            value: 7,
            dispatch_digest: Digest32::of_bytes(b"sent"),
            acknowledgement_digest: None,
        })
        .await
        .expect("effect");
    assert_eq!(value, 7);
    let unknown = store
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(unknown.state, DurableOperationState::Indeterminate);
    let terminal = store
        .observe_terminal(
            &operation.scope_id,
            &operation.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: Digest32::of_bytes(b"destination-observed"),
                observer_id: stable_id("observer:automation"),
                observer_generation: generation(1),
            },
        )
        .await
        .expect("reconcile");
    assert_eq!(terminal.state, DurableOperationState::Applied);
    let outbox = store
        .outbox_status(
            &operation.destination,
            &operation.scope_id,
            &operation.operation_id,
        )
        .await
        .expect("outbox")
        .expect("row");
    assert_eq!(outbox.state, DurableOutboxState::Acknowledged);
}

#[cfg(unix)]
#[tokio::test]
async fn proven_not_dispatched_requeues_with_a_new_fence() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 7);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("authorize");
    store
        .execute_authorized(authorized, |_| DispatchEffect::NotDispatched {
            value: (),
            reason_digest: Digest32::of_bytes(b"connection-refused-before-write"),
            retry_after: Duration::ZERO,
        })
        .await
        .expect("classify");
    let next = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:two"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("reclaim")
        .expect("row");
    assert!(next.fence > claim.fence);
    assert_eq!(next.attempts, 2);
}

#[tokio::test]
async fn terminal_gc_writes_tombstone_and_prevents_resurrection() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:one"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");
    sqlx::query(
        "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
         revision = revision + 1 WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(Digest32::of_bytes(b"fixture").as_array().as_slice())
    .bind(operation.scope_id.as_str())
    .bind(operation.operation_id.as_str())
    .execute(&store.pool)
    .await
    .expect("fixture state");
    let terminal = store
        .observe_terminal(
            &operation.scope_id,
            &operation.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::NotApplied,
                evidence_digest: Digest32::of_bytes(b"not-applied"),
                observer_id: stable_id("observer:test"),
                observer_generation: claim.owner_generation,
            },
        )
        .await
        .expect("terminal");
    let settled_at = terminal.terminal_at_unix_ms.expect("terminal timestamp");
    assert!(settled_at > 0);
    assert_eq!(
        store
            .prune_terminal(settled_at - 1, 10)
            .await
            .expect("before inclusive cutoff"),
        0
    );
    let pruned = store
        .prune_terminal(settled_at, 10)
        .await
        .expect("prune at inclusive cutoff");
    assert_eq!(pruned, 1);
    assert!(matches!(
        store.prepare_intent(&operation).await,
        Err(DurableOperationError::Retired(_))
    ));
}

#[tokio::test]
async fn retirement_never_discards_an_unreconciled_external_effect() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"retirement-payload");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:retirement"),
            generation(1),
            Duration::from_secs(1),
        )
        .await
        .expect("claim")
        .expect("row");

    sqlx::query(
        "UPDATE operation_ledger SET state = 'indeterminate', indeterminate_digest = ?,
         revision = revision + 1 WHERE scope_id = ? AND operation_id = ?",
    )
    .bind(Digest32::of_bytes(b"effect-may-have-crossed").as_array().as_slice())
    .bind(operation.scope_id.as_str())
    .bind(operation.operation_id.as_str())
    .execute(&store.pool)
    .await
    .expect("fixture indeterminate");

    assert_eq!(
        store.prune_terminal(u64::MAX, 10).await.expect("prune"),
        0,
        "retirement/GC must not erase an unresolved external effect",
    );
    let still_open = store
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("lookup")
        .expect("operation remains");
    assert_eq!(still_open.state, DurableOperationState::Indeterminate);

    store
        .observe_terminal(
            &operation.scope_id,
            &operation.operation_id,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: Digest32::of_bytes(b"terminal-retirement-observation"),
                observer_id: stable_id("observer:retirement"),
                observer_generation: claim.owner_generation,
            },
        )
        .await
        .expect("reconcile before retirement");
    assert_eq!(store.prune_terminal(u64::MAX, 10).await.expect("prune"), 1);
    assert!(matches!(
        store.prepare_intent(&operation).await,
        Err(DurableOperationError::Retired(_))
    ));
}

#[tokio::test]
async fn migration_checksum_tamper_fails_reopen() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.close().await;
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(SqliteConnectOptions::new().filename(&path))
        .await
        .expect("raw open");
    sqlx::query("UPDATE _sqlx_migrations SET checksum = X'00' WHERE version = 1")
        .execute(&pool)
        .await
        .expect("tamper");
    pool.close().await;
    assert!(matches!(
        DurableOperationStore::open(&path).await,
        Err(DurableOperationError::Corrupt(_))
    ));
}

#[tokio::test]
async fn corrupt_database_fails_closed() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.close().await;
    std::fs::write(&path, b"not a sqlite database").expect("corrupt");
    assert!(DurableOperationStore::open(&path).await.is_err());
}

#[tokio::test]
async fn retirement_cutoff_range_never_retires_pending_work_or_relaxes_batch_limits() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let operation = intent(b"pending cutoff boundary");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store.prepare_intent(&operation).await.expect("prepare");
    for cutoff in [0, 1, i64::MAX as u64, (i64::MAX as u64) + 1, u64::MAX] {
        assert_eq!(store.prune_terminal(cutoff, 1).await.expect("cutoff"), 0);
        assert_eq!(
            store
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("lookup")
                .expect("pending identity retained")
                .state,
            DurableOperationState::Prepared
        );
    }
    for limit in [0, MAX_DURABLE_CLAIM_BATCH + 1] {
        assert_eq!(
            store.prune_terminal(u64::MAX, limit).await,
            Err(DurableOperationError::Invalid("prune limit"))
        );
    }
    // The query-bound rule is not a permissive replacement for value storage.
    assert_eq!(to_i64(u64::MAX), Err(DurableOperationError::Capacity));
    store.close().await;
}
