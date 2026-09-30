use super::*;

use std::collections::BTreeSet;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("test generation")
}

fn authbus_intent(payload: &[u8]) -> DurableOperationIntentV1 {
    DurableOperationIntentV1 {
        scope_id: stable_id("scope:authbus:test"),
        operation_id: stable_id("operation:authbus:test"),
        expected_predecessor: None,
        destination: stable_id("provider:heptabao"),
        payload_digest: Digest32::of_bytes(payload),
        owner_generation: generation(1),
    }
}

#[cfg(unix)]
fn authority_fixture(
    operation: &DurableOperationIntentV1,
    nonce: u8,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    SignedFinalUseGrant,
    tempfile::TempDir,
) {
    use std::os::unix::fs::PermissionsExt;

    let signing = SigningKey::from_bytes(&[53; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authbus-operation-owner".to_owned(),
        authority_epoch: 11,
        grant_id: format!("authbus-grant-{nonce}"),
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
        "authbus-operation-owner".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 11,
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
async fn authbus_handoff_consumes_exact_durable_identity_before_effect() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    let operation = authbus_intent(b"exact-bao-request");
    store.prepare_intent(&operation).await.expect("prepare");

    let handle = store
        .claim_authbus_operation(
            &operation.scope_id,
            &operation.operation_id,
            &operation.destination,
            operation.payload_digest,
            &stable_id("worker:authbus"),
            generation(1),
            Duration::from_secs(30),
        )
        .await
        .expect("claim")
        .expect("exact operation handle");
    assert_eq!(handle.operation_id(), &operation.operation_id);
    assert_eq!(handle.owner_generation(), generation(1));
    assert_eq!(handle.payload_digest(), operation.payload_digest);

    let (authority, grant, _authority_dir) = authority_fixture(&operation, 19);
    let entered = store
        .enter_authbus_operation(&authority, &grant, handle)
        .await
        .expect("enter AuthBus path");
    assert_eq!(entered.operation_id(), &operation.operation_id);
    assert_eq!(entered.owner_generation(), generation(1));
    assert_eq!(entered.payload_digest(), operation.payload_digest);

    let current = store
        .validate_entered_authbus_operation(&entered)
        .await
        .expect("validate immediately before provider I/O");
    assert_eq!(current.state, DurableOperationState::Indeterminate);
    assert_eq!(current.intent.operation_id, operation.operation_id);
    assert_eq!(current.intent.payload_digest, operation.payload_digest);

    assert!(
        store
            .claim_authbus_operation(
                &operation.scope_id,
                &operation.operation_id,
                &operation.destination,
                operation.payload_digest,
                &stable_id("worker:retry"),
                generation(1),
                Duration::from_secs(30),
            )
            .await
            .expect("retry query")
            .is_none()
    );
}

#[cfg(unix)]
#[tokio::test]
async fn authbus_recovery_reuses_identity_and_fences_stale_generation() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    let operation = authbus_intent(b"recoverable-bao-request");
    store.prepare_intent(&operation).await.expect("prepare");
    let handle = store
        .claim_authbus_operation(
            &operation.scope_id,
            &operation.operation_id,
            &operation.destination,
            operation.payload_digest,
            &stable_id("worker:first"),
            generation(1),
            Duration::from_secs(30),
        )
        .await
        .expect("claim")
        .expect("handle");
    let (authority, grant, _authority_dir) = authority_fixture(&operation, 23);
    let stale = store
        .enter_authbus_operation(&authority, &grant, handle)
        .await
        .expect("enter");

    let recovered = store
        .recover_entered_authbus_operation(
            &operation.scope_id,
            &operation.operation_id,
            generation(2),
        )
        .await
        .expect("recover exact identity");
    assert_eq!(recovered.operation_id(), stale.operation_id());
    assert_eq!(recovered.semantic_digest(), stale.semantic_digest());
    assert_eq!(recovered.owner_generation(), generation(2));
    assert!(recovered.writer_fence() > stale.writer_fence());
    assert!(matches!(
        store.validate_entered_authbus_operation(&stale).await,
        Err(DurableOperationError::StaleGeneration | DurableOperationError::StaleLease)
    ));

    let terminal = store
        .reconcile_entered_authbus_operation(
            &recovered,
            &ReconciliationReceiptV1 {
                outcome: ReconciliationOutcome::Applied,
                evidence_digest: Digest32::of_bytes(b"bao-observer-terminal-evidence"),
                observer_id: stable_id("observer:bao"),
                observer_generation: generation(2),
            },
        )
        .await
        .expect("terminal reconciliation");
    assert_eq!(terminal.state, DurableOperationState::Applied);
}

#[tokio::test]
async fn authbus_handle_rejects_payload_drift_and_missing_identity() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let store = DurableOperationStore::open(&path).await.expect("open");
    let operation = authbus_intent(b"bound-request");
    store.prepare_intent(&operation).await.expect("prepare");

    assert!(matches!(
        store
            .claim_authbus_operation(
                &operation.scope_id,
                &operation.operation_id,
                &operation.destination,
                Digest32::of_bytes(b"different-request"),
                &stable_id("worker:authbus"),
                generation(1),
                Duration::from_secs(30),
            )
            .await,
        Err(DurableOperationError::Conflict(_))
    ));
    assert!(matches!(
        store
            .recover_entered_authbus_operation(
                &operation.scope_id,
                &stable_id("operation:authbus:fresh-retry"),
                generation(2),
            )
            .await,
        Err(DurableOperationError::Missing(_))
    ));
}
