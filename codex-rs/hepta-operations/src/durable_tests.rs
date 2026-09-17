use std::collections::BTreeSet;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::*;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("nonzero generation")
}

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn intent(operation: &str, payload: &[u8], writer_generation: u64) -> DurableOperationIntent {
    DurableOperationIntent {
        scope_id: stable_id("scope:test"),
        operation_id: stable_id(operation),
        scope_digest: Digest32::of_bytes(b"scope:test"),
        request_digest: Digest32::of_bytes(format!("request:{operation}").as_bytes()),
        payload_digest: Digest32::of_bytes(payload),
        destination_id: stable_id("destination:test"),
        expected_predecessor: None,
        writer_generation: generation(writer_generation),
        authority_epoch: generation(9),
    }
}

#[tokio::test]
async fn atomic_intent_and_outbox_survive_reopen() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    let expected = intent("operation:reopen", b"payload", 3);
    let record = store
        .prepare_intent(expected.clone())
        .await
        .expect("prepare intent");
    assert_eq!(record.state, DurableOperationState::Pending);
    let outbox = store
        .outbox(
            &expected.scope_id,
            &expected.operation_id,
            &expected.destination_id,
        )
        .await
        .expect("read outbox")
        .expect("outbox present");
    assert_eq!(outbox.state, DurableOutboxState::Queued);
    drop(store);

    let reopened = DurableOperationStore::open(&sqlite)
        .await
        .expect("reopen store");
    assert_eq!(
        reopened
            .operation(&expected.scope_id, &expected.operation_id)
            .await
            .expect("read operation")
            .expect("operation present")
            .intent,
        expected
    );
    assert!(
        reopened
            .outbox(
                &stable_id("scope:test"),
                &stable_id("operation:reopen"),
                &stable_id("destination:test"),
            )
            .await
            .expect("read outbox")
            .is_some()
    );
}

#[tokio::test]
async fn identity_reuse_with_payload_drift_conflicts_durably() {
    let temp = TempDir::new().expect("temp dir");
    let store = DurableOperationStore::open(&sqlite_config(&temp))
        .await
        .expect("open store");
    let original = intent("operation:conflict", b"one", 2);
    store
        .prepare_intent(original.clone())
        .await
        .expect("prepare original");
    let changed = intent("operation:conflict", b"two", 2);
    assert_eq!(
        store.prepare_intent(changed).await,
        Err(OperationError::Conflict(original.operation_id))
    );
}

#[tokio::test]
async fn expired_pre_dispatch_lease_allows_higher_generation_takeover() {
    let temp = TempDir::new().expect("temp dir");
    let store = DurableOperationStore::open(&sqlite_config(&temp))
        .await
        .expect("open store");
    let prepared = intent("operation:takeover", b"payload", 3);
    store
        .prepare_intent(prepared.clone())
        .await
        .expect("prepare");
    let first = store
        .claim_outbox(
            &prepared.scope_id,
            &prepared.operation_id,
            &prepared.destination_id,
            stable_id("worker:old"),
            generation(3),
            1,
        )
        .await
        .expect("first claim");
    tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    let second = store
        .claim_outbox(
            &prepared.scope_id,
            &prepared.operation_id,
            &prepared.destination_id,
            stable_id("worker:new"),
            generation(4),
            5_000,
        )
        .await
        .expect("take over expired lease");
    assert!(second.lease.fence > first.lease.fence);
    assert_eq!(second.lease.writer_generation, generation(4));
    assert_eq!(
        store.renew_claim(&first.lease, 5_000).await,
        Err(OperationError::StaleLease)
    );
}

#[tokio::test]
async fn armed_dispatch_is_never_reclaimed_after_lease_expiry() {
    let temp = TempDir::new().expect("temp dir");
    let store = DurableOperationStore::open(&sqlite_config(&temp))
        .await
        .expect("open store");
    let prepared = intent("operation:armed", b"payload", 3);
    store
        .prepare_intent(prepared.clone())
        .await
        .expect("prepare");
    let claim = store
        .claim_outbox(
            &prepared.scope_id,
            &prepared.operation_id,
            &prepared.destination_id,
            stable_id("worker:one"),
            generation(3),
            2,
        )
        .await
        .expect("claim");
    store
        .arm_dispatch(&claim.lease, Digest32::of_bytes(b"dispatch-attempt"))
        .await
        .expect("arm dispatch");
    tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    assert!(
        store
            .ready_outbox(&prepared.destination_id, 10)
            .await
            .expect("list ready")
            .is_empty()
    );
    assert_eq!(
        store
            .claim_outbox(
                &prepared.scope_id,
                &prepared.operation_id,
                &prepared.destination_id,
                stable_id("worker:two"),
                generation(4),
                5_000,
            )
            .await,
        Err(OperationError::LeaseUnavailable)
    );
}

#[tokio::test]
async fn transport_acknowledgement_is_not_terminal_success() {
    let temp = TempDir::new().expect("temp dir");
    let store = DurableOperationStore::open(&sqlite_config(&temp))
        .await
        .expect("open store");
    let prepared = intent("operation:ack", b"payload", 3);
    store
        .prepare_intent(prepared.clone())
        .await
        .expect("prepare");
    let claim = store
        .claim_outbox(
            &prepared.scope_id,
            &prepared.operation_id,
            &prepared.destination_id,
            stable_id("worker:one"),
            generation(3),
            5_000,
        )
        .await
        .expect("claim");
    let armed = store
        .arm_dispatch(&claim.lease, Digest32::of_bytes(b"dispatch"))
        .await
        .expect("arm");
    store
        .acknowledge_dispatch(&armed, Digest32::of_bytes(b"transport-accepted"))
        .await
        .expect("ack");
    let operation = store
        .operation(&prepared.scope_id, &prepared.operation_id)
        .await
        .expect("read operation")
        .expect("operation present");
    assert_eq!(operation.state, DurableOperationState::Dispatched);
    let outbox = store
        .outbox(
            &prepared.scope_id,
            &prepared.operation_id,
            &prepared.destination_id,
        )
        .await
        .expect("read outbox")
        .expect("outbox present");
    assert_eq!(outbox.state, DurableOutboxState::Acknowledged);
}

#[tokio::test]
async fn terminal_reconciliation_survives_reopen_and_prunes_to_tombstone() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let config = DurableStoreConfig {
        terminal_retention_ms: 0,
        terminal_retained_rows: 0,
        ..DurableStoreConfig::default()
    };
    let store = DurableOperationStore::open_with_config(&sqlite, config.clone())
        .await
        .expect("open store");
    let prepared = intent("operation:terminal", b"payload", 3);
    store
        .prepare_intent(prepared.clone())
        .await
        .expect("prepare");
    let claim = store
        .claim_outbox(
            &prepared.scope_id,
            &prepared.operation_id,
            &prepared.destination_id,
            stable_id("worker:one"),
            generation(3),
            5_000,
        )
        .await
        .expect("claim");
    store
        .arm_dispatch(&claim.lease, Digest32::of_bytes(b"dispatch"))
        .await
        .expect("arm");
    store
        .observe_terminal(
            &prepared.scope_id,
            &prepared.operation_id,
            generation(4),
            ReconciliationOutcome::Applied,
            Digest32::of_bytes(b"destination-applied"),
            None,
        )
        .await
        .expect("settle terminal");
    drop(store);

    let reopened = DurableOperationStore::open_with_config(&sqlite, config)
        .await
        .expect("reopen store");
    let terminal = reopened
        .operation(&prepared.scope_id, &prepared.operation_id)
        .await
        .expect("read operation")
        .expect("operation present");
    assert_eq!(terminal.state, DurableOperationState::Applied);
    assert_eq!(reopened.prune_terminal(10).await.expect("prune"), 1);
    assert!(
        reopened
            .operation(&prepared.scope_id, &prepared.operation_id)
            .await
            .expect("read pruned operation")
            .is_none()
    );
    assert_eq!(
        reopened.prepare_intent(prepared.clone()).await,
        Err(OperationError::TerminalPruned(prepared.operation_id))
    );
    assert_eq!(reopened.metrics().await.expect("metrics").tombstones, 1);
}

#[tokio::test]
async fn independent_store_handles_serialize_same_operation_writer() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = DurableOperationStore::open(&sqlite).await.expect("first open");
    let second = DurableOperationStore::open(&sqlite).await.expect("second open");
    let value = intent("operation:multiwriter", b"payload", 3);
    let (left, right) = tokio::join!(
        first.prepare_intent(value.clone()),
        second.prepare_intent(value.clone())
    );
    assert!(left.is_ok());
    assert!(right.is_ok());
    assert_eq!(
        first
            .operation(&value.scope_id, &value.operation_id)
            .await
            .expect("read operation")
            .expect("operation present")
            .intent
            .payload_digest,
        value.payload_digest
    );
}

#[cfg(unix)]
#[tokio::test]
async fn final_use_token_is_consumed_at_durable_dispatch_boundary() {
    use std::os::unix::fs::PermissionsExt;

    struct AppliedAdapter;
    impl EffectAdapter for AppliedAdapter {
        fn dispatch(&mut self, _dispatch: &ArmedDispatch) -> DispatchObservation {
            DispatchObservation::Terminal {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: Digest32::of_bytes(b"destination-dedupe-receipt"),
                acknowledgement_digest: Some(Digest32::of_bytes(b"ack")),
            }
        }
    }

    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let store = DurableOperationStore::open(&sqlite).await.expect("open store");
    let prepared = intent("operation:authority", b"payload", 3);
    store
        .prepare_intent(prepared.clone())
        .await
        .expect("prepare");
    let claim = store
        .claim_outbox(
            &prepared.scope_id,
            &prepared.operation_id,
            &prepared.destination_id,
            stable_id("worker:authority"),
            generation(3),
            5_000,
        )
        .await
        .expect("claim");

    let issuer = SigningKey::from_bytes(&[47; 32]);
    let binding = FinalUseBinding {
        subject_id: "agent-one".into(),
        destination_id: prepared.destination_id.as_str().into(),
        request_sha256: *prepared.request_digest.as_array(),
        scope_sha256: *prepared.scope_digest.as_array(),
        payload_sha256: *prepared.payload_digest.as_array(),
    };
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "operation-authority".into(),
        nonce: [5; 32],
        binding: binding.clone(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let signed = SignedFinalUseGrant { grant, signature };
    let authority_dir = TempDir::new().expect("authority dir");
    std::fs::set_permissions(
        authority_dir.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("private authority dir");
    let authority = FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "security-owner".into(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("open authority");
    let observation = store
        .dispatch_with_final_use(
            claim,
            &authority,
            &signed,
            &binding,
            Digest32::of_bytes(b"dispatch-attempt"),
            &mut AppliedAdapter,
        )
        .await
        .expect("authorized dispatch");
    assert!(matches!(
        observation,
        DispatchObservation::Terminal {
            outcome: ReconciliationOutcome::Applied,
            ..
        }
    ));
    assert_eq!(
        store
            .operation(&prepared.scope_id, &prepared.operation_id)
            .await
            .expect("read operation")
            .expect("operation present")
            .state,
        DurableOperationState::Applied
    );
}
