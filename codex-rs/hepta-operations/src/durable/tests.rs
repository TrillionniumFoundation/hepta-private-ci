use std::time::Duration;

use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::*;
use crate::ReconciliationOutcome;

#[cfg(unix)]
use std::collections::BTreeSet;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
#[cfg(unix)]
use std::time::SystemTime;
#[cfg(unix)]
use std::time::UNIX_EPOCH;
#[cfg(unix)]
use codex_hepta_contracts::FinalUseAuthority;
#[cfg(unix)]
use codex_hepta_contracts::FinalUseGrant;
#[cfg(unix)]
use codex_hepta_contracts::FinalUseRevocations;
#[cfg(unix)]
use codex_hepta_contracts::SignedFinalUseGrant;
#[cfg(unix)]
use ed25519_dalek::Signer;
#[cfg(unix)]
use ed25519_dalek::SigningKey;

fn stable_id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(value) => value,
        Err(error) => panic!("test stable id rejected: {error}"),
    }
}

fn generation(value: u64) -> Generation {
    match Generation::new(value) {
        Ok(value) => value,
        Err(error) => panic!("test generation rejected: {error}"),
    }
}

fn config(temp: &TempDir) -> SqliteConfig {
    let home = match AbsolutePathBuf::try_from(temp.path().to_path_buf()) {
        Ok(value) => value,
        Err(error) => panic!("temporary path is not absolute: {error}"),
    };
    SqliteConfig::new_for_testing(home)
}

fn request(operation: &str, payload: &[u8]) -> PrepareOperationIntent {
    PrepareOperationIntent {
        scope: stable_id("scope:test"),
        operation_id: stable_id(operation),
        predecessor_digest: Some(Digest32::of_bytes(b"predecessor")),
        payload_digest: Digest32::of_bytes(payload),
        destination: stable_id("destination:test"),
        owner_generation: generation(3),
        authority_epoch: generation(9),
    }
}

async fn prepared_store() -> (TempDir, SqliteConfig, DurableOperationStore, PrepareOperationIntent) {
    let temp = tempfile::tempdir().expect("tempdir");
    let sqlite = config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    let request = request("operation:test:1", b"payload");
    store.prepare_intent(&request).await.expect("prepare intent");
    (temp, sqlite, store, request)
}

#[tokio::test]
async fn intent_and_outbox_commit_atomically_and_survive_reopen() {
    let temp = tempfile::tempdir().expect("tempdir");
    let sqlite = config(&temp);
    let request = request("operation:reopen", b"payload");
    let first = DurableOperationStore::open(&sqlite).await.expect("open first");
    let record = first.prepare_intent(&request).await.expect("prepare");
    assert_eq!(record.state, DurableOperationState::Pending);
    let outbox = first
        .outbox_status(&request.scope, &request.operation_id)
        .await
        .expect("outbox lookup")
        .expect("outbox exists");
    assert_eq!(outbox.state, DurableOutboxState::Queued);
    first.close().await;
    drop(first);

    let reopened = DurableOperationStore::open(&sqlite).await.expect("reopen");
    assert_eq!(
        reopened
            .get_operation(&request.scope, &request.operation_id)
            .await
            .expect("lookup")
            .expect("operation"),
        record
    );
    assert!(
        reopened
            .outbox_status(&request.scope, &request.operation_id)
            .await
            .expect("outbox lookup")
            .is_some()
    );
}

#[tokio::test]
async fn failed_outbox_insert_rolls_back_operation_insert() {
    let temp = tempfile::tempdir().expect("tempdir");
    let sqlite = config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    sqlx::query(
        "CREATE TRIGGER test_abort_outbox BEFORE INSERT ON cross_owner_outbox
         BEGIN SELECT RAISE(ABORT, 'forced outbox failure'); END",
    )
    .execute(&store.pool)
    .await
    .expect("install failpoint");
    let request = request("operation:atomic", b"payload");
    assert!(store.prepare_intent(&request).await.is_err());
    assert!(
        store
            .get_operation(&request.scope, &request.operation_id)
            .await
            .expect("lookup")
            .is_none()
    );
}

#[tokio::test]
async fn semantic_replay_is_idempotent_and_payload_drift_conflicts() {
    let (_temp, _sqlite, store, request) = prepared_store().await;
    let first = store.prepare_intent(&request).await.expect("first replay");
    let second = store.prepare_intent(&request).await.expect("second replay");
    assert_eq!(first, second);
    let mut changed = request.clone();
    changed.payload_digest = Digest32::of_bytes(b"changed");
    assert!(matches!(
        store.prepare_intent(&changed).await,
        Err(DurableOperationError::Conflict(_))
    ));
}

#[tokio::test]
async fn expired_lease_can_be_taken_over_by_higher_generation() {
    let (_temp, _sqlite, store, request) = prepared_store().await;
    let worker_one = stable_id("worker:one");
    let worker_two = stable_id("worker:two");
    let first = store
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &worker_one,
            generation(3),
            5,
        )
        .await
        .expect("first claim");
    assert!(matches!(
        store
            .claim_outbox(
                &request.scope,
                &request.operation_id,
                &worker_two,
                generation(4),
                100,
            )
            .await,
        Err(DurableOperationError::StaleLease)
    ));
    tokio::time::sleep(Duration::from_millis(15)).await;
    let second = store
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &worker_two,
            generation(4),
            100,
        )
        .await
        .expect("takeover");
    assert!(second.fence > first.fence);
    let record = store
        .get_operation(&request.scope, &request.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(record.owner_generation, generation(4));
    assert!(matches!(
        store.renew_outbox_lease(&first, 100).await,
        Err(DurableOperationError::StaleLease)
    ));
}

#[tokio::test]
async fn dispatch_ack_is_not_terminal_and_blind_retry_is_rejected() {
    let (_temp, _sqlite, store, request) = prepared_store().await;
    let lease = store
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &stable_id("worker:dispatch"),
            generation(3),
            1000,
        )
        .await
        .expect("claim");
    store
        .mark_dispatched(&lease, Digest32::of_bytes(b"transport-send"))
        .await
        .expect("mark dispatched");
    assert!(matches!(
        store
            .retry_outbox(&lease, 1, Digest32::of_bytes(b"retry"))
            .await,
        Err(DurableOperationError::ReconciliationRequired)
    ));
    store
        .acknowledge_outbox(&lease, Digest32::of_bytes(b"queue-ack"))
        .await
        .expect("ack");
    let record = store
        .get_operation(&request.scope, &request.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(record.state, DurableOperationState::Dispatched);
    assert!(!record.state.is_terminal());
}

#[tokio::test]
async fn indeterminate_effect_reconciles_from_destination_dedup() {
    let source_temp = tempfile::tempdir().expect("source tempdir");
    let source = DurableOperationStore::open(&config(&source_temp))
        .await
        .expect("source store");
    let destination_temp = tempfile::tempdir().expect("destination tempdir");
    let destination = DurableOperationStore::open(&config(&destination_temp))
        .await
        .expect("destination store");
    let request = request("operation:reconcile", b"payload");
    let prepared = source.prepare_intent(&request).await.expect("prepare");
    let lease = source
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &stable_id("worker:reconcile"),
            generation(3),
            1000,
        )
        .await
        .expect("claim");
    source
        .mark_dispatched(&lease, Digest32::of_bytes(b"dispatch"))
        .await
        .expect("dispatch");
    source
        .mark_indeterminate(&lease, Digest32::of_bytes(b"ack-lost"))
        .await
        .expect("indeterminate");
    let evidence = Digest32::of_bytes(b"destination-observation");
    destination
        .record_destination_outcome(
            &request.destination,
            &request.operation_id,
            prepared.semantic_digest,
            ReconciliationOutcome::Applied,
            evidence,
        )
        .await
        .expect("destination dedup");
    assert!(matches!(
        source
            .reconcile_from_destination(
                &destination,
                &request.scope,
                &request.operation_id,
                generation(2),
            )
            .await,
        Err(DurableOperationError::StaleLease)
    ));
    let terminal = source
        .reconcile_from_destination(
            &destination,
            &request.scope,
            &request.operation_id,
            generation(4),
        )
        .await
        .expect("higher-generation reconcile takeover");
    assert_eq!(terminal.owner_generation, generation(4));
    assert_eq!(terminal.state, DurableOperationState::Applied);
    assert_eq!(terminal.terminal_evidence_digest, Some(evidence));
    let outbox = source
        .outbox_status(&request.scope, &request.operation_id)
        .await
        .expect("outbox")
        .expect("outbox row");
    assert_eq!(outbox.state, DurableOutboxState::Settled);
}

#[tokio::test]
async fn destination_dedup_replay_is_exact_and_conflicting_outcome_fails() {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&config(&temp))
        .await
        .expect("open store");
    let destination = stable_id("destination:dedup");
    let operation = stable_id("operation:dedup");
    let semantic = Digest32::of_bytes(b"semantic");
    let evidence = Digest32::of_bytes(b"evidence");
    let first = store
        .record_destination_outcome(
            &destination,
            &operation,
            semantic,
            ReconciliationOutcome::Applied,
            evidence,
        )
        .await
        .expect("first");
    let replay = store
        .record_destination_outcome(
            &destination,
            &operation,
            semantic,
            ReconciliationOutcome::Applied,
            evidence,
        )
        .await
        .expect("replay");
    assert_eq!(first, replay);
    assert!(matches!(
        store
            .record_destination_outcome(
                &destination,
                &operation,
                semantic,
                ReconciliationOutcome::NotApplied,
                evidence,
            )
            .await,
        Err(DurableOperationError::Conflict(_))
    ));
}

#[cfg(unix)]
#[tokio::test]
async fn final_use_authority_is_bound_to_durable_operation_identity() {
    let (_temp, _sqlite, store, request) = prepared_store().await;
    let lease = store
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &stable_id("worker:authority"),
            generation(3),
            1000,
        )
        .await
        .expect("claim");
    let record = store
        .get_operation(&request.scope, &request.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    let binding = record.final_use_binding();
    let signing_key = SigningKey::from_bytes(&[37; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_string(),
        authority_epoch: 9,
        grant_id: "operation-grant".to_string(),
        nonce: [11; 32],
        binding: binding.clone(),
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing_key
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let authority_dir = tempfile::tempdir().expect("authority tempdir");
    std::fs::set_permissions(authority_dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("secure authority dir");
    let authority = FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "security-owner".to_string(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("open authority");
    let signed = SignedFinalUseGrant { grant, signature };
    let (token, expected) = store
        .claim_final_use(&authority, &signed, &lease)
        .await
        .expect("claim final use");
    assert_eq!(expected, binding);
    let mut called = false;
    authority
        .with_verified_use(token, &expected, || called = true)
        .expect("consume final use");
    assert!(called);
}

#[tokio::test]
async fn missing_required_schema_object_fails_reopen_closed() {
    let temp = tempfile::tempdir().expect("tempdir");
    let sqlite = config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    sqlx::query("DROP INDEX cross_owner_outbox_ready")
        .execute(&store.pool)
        .await
        .expect("drop required index");
    store.close().await;
    drop(store);
    assert!(matches!(
        DurableOperationStore::open(&sqlite).await,
        Err(DurableOperationError::Corrupt(_))
    ));
}

#[tokio::test]
async fn metrics_and_terminal_retention_are_bounded() {
    let source_temp = tempfile::tempdir().expect("source tempdir");
    let source = DurableOperationStore::open(&config(&source_temp))
        .await
        .expect("source store");
    let destination_temp = tempfile::tempdir().expect("destination tempdir");
    let destination = DurableOperationStore::open(&config(&destination_temp))
        .await
        .expect("destination store");
    let request = request("operation:metrics", b"payload");
    let prepared = source.prepare_intent(&request).await.expect("prepare");
    let lease = source
        .claim_outbox(
            &request.scope,
            &request.operation_id,
            &stable_id("worker:metrics"),
            generation(3),
            1000,
        )
        .await
        .expect("claim");
    source
        .mark_dispatched(&lease, Digest32::of_bytes(b"dispatch"))
        .await
        .expect("dispatch");
    destination
        .record_destination_outcome(
            &request.destination,
            &request.operation_id,
            prepared.semantic_digest,
            ReconciliationOutcome::NotApplied,
            Digest32::of_bytes(b"not-applied"),
        )
        .await
        .expect("destination outcome");
    source
        .reconcile_from_destination(
            &destination,
            &request.scope,
            &request.operation_id,
            generation(3),
        )
        .await
        .expect("reconcile");
    let metrics = source.metrics().await.expect("metrics");
    assert_eq!(metrics.total_operations, 1);
    assert_eq!(metrics.terminal_operations, 1);
    assert_eq!(source.prune_terminal(i64::MAX, 1).await.expect("prune"), 1);
    assert!(
        source
            .get_operation(&request.scope, &request.operation_id)
            .await
            .expect("lookup")
            .is_none()
    );
    assert!(matches!(
        source.prepare_intent(&request).await,
        Err(DurableOperationError::Retired(_))
    ));
    let mut changed = request.clone();
    changed.payload_digest = Digest32::of_bytes(b"resurrected-payload");
    assert!(matches!(
        source.prepare_intent(&changed).await,
        Err(DurableOperationError::Conflict(_))
    ));
}


#[tokio::test]
async fn pruned_destination_receipt_remains_a_dedupe_fence() {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&config(&temp))
        .await
        .expect("open store");
    let destination = stable_id("destination:retired-dedupe");
    let operation = stable_id("operation:retired-dedupe");
    let semantic = Digest32::of_bytes(b"retired-semantic");
    let evidence = Digest32::of_bytes(b"retired-evidence");
    let original = store
        .record_destination_outcome(
            &destination,
            &operation,
            semantic,
            ReconciliationOutcome::Applied,
            evidence,
        )
        .await
        .expect("record destination outcome");
    assert_eq!(
        store
            .prune_destination_receipts(i64::MAX, 1)
            .await
            .expect("prune destination receipt"),
        1
    );
    assert_eq!(
        store
            .destination_receipt(&destination, &operation)
            .await
            .expect("lookup tombstone"),
        Some(original.clone())
    );
    assert_eq!(
        store
            .record_destination_outcome(
                &destination,
                &operation,
                semantic,
                ReconciliationOutcome::Applied,
                evidence,
            )
            .await
            .expect("exact replay from tombstone"),
        original
    );
    assert!(matches!(
        store
            .record_destination_outcome(
                &destination,
                &operation,
                semantic,
                ReconciliationOutcome::Applied,
                Digest32::of_bytes(b"changed-retired-evidence"),
            )
            .await,
        Err(DurableOperationError::Conflict(_))
    ));
}
