use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sqlx::Acquire;
use tempfile::TempDir;

use super::*;
use crate::DESTINATION_DEDUPE_SCHEMA_V1;
use crate::DestinationDedupeKey;
use crate::DestinationEffectAdapter;
use crate::DestinationReservation;
use crate::DispatchEnvelope;
use crate::DispatchResult;
use crate::DurableDispatcher;
use crate::finish_destination_effect;
use crate::reserve_destination_effect;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identifier")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("fixture generation")
}

fn identity() -> OperationIdentity {
    OperationIdentity {
        scope_id: stable_id("scope:test"),
        operation_id: stable_id("operation:test:durable:1"),
    }
}

fn intent(payload: &[u8]) -> DurableIntent {
    DurableIntent {
        identity: identity(),
        predecessor_id: Some(stable_id("operation:test:predecessor")),
        destination_id: stable_id("cognitive.store"),
        payload_digest: Digest32::of_bytes(payload),
        owner_generation: generation(1),
        authority_epoch: generation(1),
    }
}

async fn store(root: &TempDir) -> DurableOperationStore {
    DurableOperationStore::open(root.path().join("operations.sqlite"))
        .await
        .expect("durable store opens")
}

#[tokio::test]
async fn prepare_commits_ledger_and_outbox_atomically() {
    let root = TempDir::new().expect("tempdir");
    let store = store(&root).await;
    sqlx::query(
        "CREATE TRIGGER test_fail_outbox BEFORE INSERT ON cross_owner_outbox
         BEGIN SELECT RAISE(ABORT, 'injected outbox failure'); END",
    )
    .execute(&store.pool)
    .await
    .expect("install failure trigger");

    assert!(store.prepare_intent(&intent(b"payload")).await.is_err());
    assert_eq!(
        store.operation_status(&identity()).await.expect("status"),
        None
    );
    assert_eq!(store.outbox_status(&identity()).await.expect("status"), None);

    sqlx::query("DROP TRIGGER test_fail_outbox")
        .execute(&store.pool)
        .await
        .expect("drop failure trigger");
    let prepared = store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("prepare");
    assert_eq!(prepared.state, DurableOperationState::Prepared);
    assert_eq!(
        store
            .outbox_status(&identity())
            .await
            .expect("status")
            .expect("outbox")
            .state,
        DurableOutboxState::Queued
    );
}

#[tokio::test]
async fn exact_prepare_replay_is_idempotent_and_payload_drift_conflicts() {
    let root = TempDir::new().expect("tempdir");
    let store = store(&root).await;
    let first = store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("first prepare");
    let replay = store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("replay");
    assert_eq!(first, replay);
    assert!(matches!(
        store.prepare_intent(&intent(b"changed")).await,
        Err(DurableOperationError::Conflict(_))
    ));
}

#[tokio::test]
async fn expired_pre_dispatch_lease_can_be_taken_over_by_new_generation() {
    let root = TempDir::new().expect("tempdir");
    let store = store(&root).await;
    store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("prepare");
    let first = store
        .claim_outbox(&identity(), &stable_id("worker:one"), generation(1), 1)
        .await
        .expect("claim");
    tokio::time::sleep(Duration::from_millis(5)).await;
    let report = store
        .recover_expired_leases()
        .await
        .expect("recover lease");
    assert_eq!(report.requeued_before_dispatch, 1);
    let second = store
        .claim_outbox(&identity(), &stable_id("worker:two"), generation(2), 1_000)
        .await
        .expect("take over");
    assert!(second.fence > first.fence);
    assert_eq!(second.owner_generation, generation(2));
}

#[tokio::test]
async fn reopen_after_dispatch_never_blindly_requeues_unknown_effect() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("operations.sqlite");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("prepare");
    let lease = store
        .claim_outbox(&identity(), &stable_id("worker:one"), generation(1), 2)
        .await
        .expect("claim");
    store
        .mark_dispatch_started(&lease)
        .await
        .expect("dispatch start");
    store.close().await;
    tokio::time::sleep(Duration::from_millis(8)).await;

    let reopened = DurableOperationStore::open(&path).await.expect("reopen");
    let operation = reopened
        .operation_status(&identity())
        .await
        .expect("status")
        .expect("operation");
    let outbox = reopened
        .outbox_status(&identity())
        .await
        .expect("status")
        .expect("outbox");
    assert_eq!(operation.state, DurableOperationState::Indeterminate);
    assert_eq!(outbox.state, DurableOutboxState::Indeterminate);
    assert_eq!(
        reopened
            .claim_outbox(&identity(), &stable_id("worker:two"), generation(2), 1_000)
            .await,
        Err(DurableOperationError::RequiresReconciliation)
    );
}

#[tokio::test]
async fn acknowledgement_loss_stays_indeterminate_until_authoritative_observation() {
    let root = TempDir::new().expect("tempdir");
    let store = store(&root).await;
    store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("prepare");
    let lease = store
        .claim_outbox(&identity(), &stable_id("worker:one"), generation(1), 1_000)
        .await
        .expect("claim");
    store
        .mark_dispatch_started(&lease)
        .await
        .expect("dispatch start");
    store
        .record_transport_ack(&lease, Digest32::of_bytes(b"transport-ack"), 7)
        .await
        .expect("record ack");
    assert_eq!(
        store
            .operation_status(&identity())
            .await
            .expect("status")
            .expect("operation")
            .state,
        DurableOperationState::Indeterminate
    );
    let terminal = store
        .observe_terminal(
            &identity(),
            generation(2),
            &stable_id("observer:cognitive.store"),
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"destination-receipt"),
        )
        .await
        .expect("reconcile");
    assert_eq!(terminal.state, DurableOperationState::Applied);
}

#[tokio::test]
async fn independent_store_handles_serialize_conflicting_writers() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("operations.sqlite");
    let first = DurableOperationStore::open(&path).await.expect("first");
    let second = DurableOperationStore::open(&path).await.expect("second");
    let a = intent(b"payload");
    let b = a.clone();
    let (left, right) = tokio::join!(first.prepare_intent(&a), second.prepare_intent(&b));
    assert!(left.is_ok());
    assert!(right.is_ok());
    assert!(matches!(
        second.prepare_intent(&intent(b"changed")).await,
        Err(DurableOperationError::Conflict(_))
    ));
}

#[tokio::test]
async fn destination_dedupe_commits_with_destination_transaction() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("destination.sqlite");
    let options = sqlx::sqlite::SqliteConnectOptions::new()
        .filename(&path)
        .create_if_missing(true)
        .journal_mode(sqlx::sqlite::SqliteJournalMode::Wal)
        .synchronous(sqlx::sqlite::SqliteSynchronous::Full);
    let pool = sqlx::sqlite::SqlitePoolOptions::new()
        .max_connections(2)
        .connect_with(options)
        .await
        .expect("destination store");
    sqlx::raw_sql(DESTINATION_DEDUPE_SCHEMA_V1)
        .execute(&pool)
        .await
        .expect("dedupe schema");
    sqlx::query("CREATE TABLE domain_effect (id TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT")
        .execute(&pool)
        .await
        .expect("domain schema");

    let key = DestinationDedupeKey {
        identity: identity(),
        destination_id: stable_id("cognitive.store"),
        semantic_digest: intent(b"payload").semantic_digest(),
    };
    let receipt = Digest32::of_bytes(b"receipt");
    let mut tx = pool.begin_with("BEGIN IMMEDIATE").await.expect("transaction");
    assert_eq!(
        reserve_destination_effect(&mut tx, &key, 1)
            .await
            .expect("reserve"),
        DestinationReservation::Reserved
    );
    sqlx::query("INSERT INTO domain_effect (id, value) VALUES (?, ?)")
        .bind(key.identity.operation_id.as_str())
        .bind("applied")
        .execute(&mut *tx)
        .await
        .expect("domain mutation");
    finish_destination_effect(&mut tx, &key, receipt, 2)
        .await
        .expect("finish");
    tx.commit().await.expect("commit");

    let mut replay = pool.begin_with("BEGIN IMMEDIATE").await.expect("replay tx");
    assert_eq!(
        reserve_destination_effect(&mut replay, &key, 3)
            .await
            .expect("reserve replay"),
        DestinationReservation::AlreadyApplied {
            receipt_digest: receipt
        }
    );
    replay.commit().await.expect("replay commit");
}

#[tokio::test]
async fn terminal_outbox_gc_never_resurrects_operation_identity() {
    let root = TempDir::new().expect("tempdir");
    let store = store(&root).await;
    store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("prepare");
    let lease = store
        .claim_outbox(&identity(), &stable_id("worker:one"), generation(1), 1_000)
        .await
        .expect("claim");
    store
        .mark_dispatch_started(&lease)
        .await
        .expect("dispatch");
    let evidence = Digest32::of_bytes(b"terminal");
    store
        .observe_terminal(
            &identity(),
            generation(1),
            &stable_id("observer:one"),
            ReconciliationOutcome::Applied,
            evidence,
        )
        .await
        .expect("terminal");
    assert!(store.prune_terminal_outbox(0, 0).await.expect("prune") <= 1);
    assert!(store.outbox_status(&identity()).await.expect("status").is_none());
    let operation = store
        .operation_status(&identity())
        .await
        .expect("status")
        .expect("operation retained");
    assert_eq!(operation.state, DurableOperationState::Applied);
    assert!(matches!(
        store.prepare_intent(&intent(b"changed")).await,
        Err(DurableOperationError::Conflict(_))
    ));
}

#[tokio::test]
async fn corrupt_database_fails_closed_on_reopen() {
    let root = TempDir::new().expect("tempdir");
    let path = root.path().join("operations.sqlite");
    let store = DurableOperationStore::open(&path).await.expect("open");
    store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("prepare");
    store.close().await;
    let _ = std::fs::remove_file(format!("{}-wal", path.display()));
    let _ = std::fs::remove_file(format!("{}-shm", path.display()));
    std::fs::write(&path, b"not-a-sqlite-database").expect("corrupt database");
    assert!(DurableOperationStore::open(&path).await.is_err());
}

struct AppliedAdapter {
    calls: Arc<AtomicUsize>,
}

impl DestinationEffectAdapter for AppliedAdapter {
    fn dispatch(&self, envelope: &DispatchEnvelope) -> DispatchResult {
        self.calls.fetch_add(1, Ordering::SeqCst);
        DispatchResult::Terminal {
            observer_id: stable_id("observer:adapter"),
            observer_generation: envelope.lease.owner_generation,
            outcome: ReconciliationOutcome::Applied,
            evidence_digest: Digest32::of_bytes(b"adapter-terminal-receipt"),
        }
    }
}

#[cfg(unix)]
#[tokio::test]
async fn dispatcher_consumes_real_final_use_authority_at_effect_boundary() {
    use std::os::unix::fs::PermissionsExt;

    let root = TempDir::new().expect("tempdir");
    let store = store(&root).await;
    let prepared = store
        .prepare_intent(&intent(b"payload"))
        .await
        .expect("prepare");

    let key = SigningKey::from_bytes(&[7_u8; 32]);
    let authority_dir = root.path().join("authority");
    std::fs::create_dir(&authority_dir).expect("authority dir");
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
        .expect("authority permissions");
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "issuer:test".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");

    let dummy = DispatchLease {
        identity: prepared.intent.identity.clone(),
        destination_id: prepared.intent.destination_id.clone(),
        payload_digest: prepared.intent.payload_digest,
        semantic_digest: prepared.semantic_digest,
        worker_id: stable_id("worker:dispatcher"),
        owner_generation: generation(1),
        fence: 1,
        attempts: 1,
        expires_at_ms: i64::MAX,
    };
    let binding = DispatchEnvelope::from_lease(dummy).final_use_binding();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "issuer:test".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:test:operations".to_owned(),
        nonce: [11_u8; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = key.sign(&grant.signing_bytes().expect("signing bytes"));
    let signed = SignedFinalUseGrant {
        grant,
        signature: signature.to_bytes().to_vec(),
    };
    let calls = Arc::new(AtomicUsize::new(0));
    let adapter = AppliedAdapter {
        calls: Arc::clone(&calls),
    };
    let dispatcher = DurableDispatcher::new(&store, &authority);
    let status = dispatcher
        .dispatch_once(
            &identity(),
            &stable_id("worker:dispatcher"),
            generation(1),
            10_000,
            &signed,
            &adapter,
        )
        .await
        .expect("dispatch");
    assert_eq!(status.state, DurableOperationState::Applied);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}
