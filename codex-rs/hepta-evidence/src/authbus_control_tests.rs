use std::time::Duration;

use codex_hepta_authbus::AuthBusTrustHead;
use codex_hepta_authbus::AuthPolicyRule;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_authbus::EffectAdmissionRequest;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::QuotaRegistryEntry;
use codex_hepta_authbus::ReservationReconcileOutcome;
use codex_hepta_authbus::ReservationState;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::AuthBusControlError;
use crate::HeptaEvidenceStore;
use crate::store::now_millis;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn scope() -> Digest32 {
    Digest32::of_bytes(b"authbus-control-test-scope")
}

async fn provision(
    store: &HeptaEvidenceStore,
    capacity: u64,
) -> (StableId, StableId, StableId, u64) {
    let principal = id("principal:test");
    let action = id("action:provider-effect");
    let quota = id("quota:test");
    store
        .put_auth_policy(&AuthPolicyRule {
            principal_id: principal.clone(),
            action_id: action.clone(),
            scope_digest: scope(),
            revision: 1,
            effect: PolicyEffect::Allow,
        })
        .await
        .unwrap();
    let now = u64::try_from(now_millis().unwrap()).unwrap();
    let end = now + 60_000;
    store
        .put_quota_registry(&QuotaRegistryEntry {
            quota_key: quota.clone(),
            revision: 1,
            capacity,
            period_start_ms: now.saturating_sub(1_000),
            period_end_ms: end,
        })
        .await
        .unwrap();
    (principal, action, quota, end)
}

fn request(
    operation: &str,
    principal: &StableId,
    action: &StableId,
    quota: &StableId,
    amount: u64,
    expires_at_ms: u64,
) -> EffectAdmissionRequest {
    EffectAdmissionRequest {
        operation_id: id(operation),
        principal_id: principal.clone(),
        action_id: action.clone(),
        scope_digest: scope(),
        policy_revision: 1,
        quota_key: quota.clone(),
        quota_revision: 1,
        amount,
        expires_at_ms,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn bus_01_simultaneous_last_unit_reservations_cannot_both_succeed() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let (principal, action, quota, end) = provision(&first, 1).await;
    let left = request(
        "operation:last-unit-left",
        &principal,
        &action,
        &quota,
        1,
        end - 1,
    );
    let right = request(
        "operation:last-unit-right",
        &principal,
        &action,
        &quota,
        1,
        end - 1,
    );

    let (left, right) = tokio::join!(
        first.authorize_and_reserve(&left),
        second.authorize_and_reserve(&right)
    );
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let rejected = left.err().or_else(|| right.err()).unwrap();
    assert!(matches!(rejected, AuthBusControlError::QuotaExceeded));
    let snapshot = first.quota_snapshot(&quota).await.unwrap();
    assert_eq!((snapshot.capacity, snapshot.reserved, snapshot.consumed), (1, 1, 0));
}

#[tokio::test]
async fn bus_02_duplicate_settlement_is_idempotent_and_changed_cost_conflicts() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let (principal, action, quota, end) = provision(&store, 10).await;
    let request = request(
        "operation:settlement",
        &principal,
        &action,
        &quota,
        10,
        end - 1,
    );
    let admitted = store.authorize_and_reserve(&request).await.unwrap();
    store
        .begin_reserved_effect(admitted.reservation.reservation_id, &request.operation_id)
        .await
        .unwrap();
    let evidence = Digest32::of_bytes(b"provider:completed:operation:settlement");
    let first = store
        .settle_reservation(admitted.reservation.reservation_id, 7, evidence)
        .await
        .unwrap();
    let duplicate = store
        .settle_reservation(admitted.reservation.reservation_id, 7, evidence)
        .await
        .unwrap();
    assert_eq!(first, duplicate);
    assert!(matches!(
        store
            .settle_reservation(
                admitted.reservation.reservation_id,
                8,
                Digest32::of_bytes(b"different-terminal-evidence")
            )
            .await,
        Err(AuthBusControlError::ReservationConflict)
    ));
    let snapshot = store.quota_snapshot(&quota).await.unwrap();
    assert_eq!((snapshot.reserved, snapshot.consumed, snapshot.available()), (0, 7, 3));
}

#[tokio::test]
async fn bus_03_expiry_racing_terminal_result_never_double_refunds() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let (principal, action, quota, _) = provision(&store, 10).await;
    let now = u64::try_from(now_millis().unwrap()).unwrap();
    let request = request(
        "operation:expiry-race",
        &principal,
        &action,
        &quota,
        10,
        now + 2,
    );
    let admitted = store.authorize_and_reserve(&request).await.unwrap();
    store
        .begin_reserved_effect(admitted.reservation.reservation_id, &request.operation_id)
        .await
        .unwrap();
    std::thread::sleep(Duration::from_millis(4));
    assert_eq!(store.expire_reservations().await.unwrap(), 0);
    store
        .settle_reservation(
            admitted.reservation.reservation_id,
            6,
            Digest32::of_bytes(b"terminal-after-expiry"),
        )
        .await
        .unwrap();
    assert_eq!(store.expire_reservations().await.unwrap(), 0);
    let snapshot = store.quota_snapshot(&quota).await.unwrap();
    assert_eq!((snapshot.reserved, snapshot.consumed, snapshot.available()), (0, 6, 4));
}

#[tokio::test]
async fn bus_04_stale_or_denied_policy_cannot_cross_effect_boundary() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let (principal, action, quota, end) = provision(&store, 10).await;
    let request = request(
        "operation:revoked-policy",
        &principal,
        &action,
        &quota,
        10,
        end - 1,
    );
    let admitted = store.authorize_and_reserve(&request).await.unwrap();
    store
        .put_auth_policy(&AuthPolicyRule {
            principal_id: principal,
            action_id: action,
            scope_digest: scope(),
            revision: 2,
            effect: PolicyEffect::Deny,
        })
        .await
        .unwrap();

    assert!(matches!(
        store
            .begin_reserved_effect(admitted.reservation.reservation_id, &request.operation_id)
            .await,
        Err(AuthBusControlError::StalePolicyRevision)
    ));
    let reservation = store
        .reservation(admitted.reservation.reservation_id)
        .await
        .unwrap();
    assert_eq!(reservation.state, ReservationState::Cancelled);
    let snapshot = store.quota_snapshot(&quota).await.unwrap();
    assert_eq!((snapshot.reserved, snapshot.consumed), (0, 0));
}

#[tokio::test]
async fn in_flight_reservation_survives_reopen_and_requires_reconciliation() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let (principal, action, quota, end) = provision(&store, 10).await;
    let request = request(
        "operation:crash-reopen",
        &principal,
        &action,
        &quota,
        10,
        end - 1,
    );
    let admitted = store.authorize_and_reserve(&request).await.unwrap();
    store
        .begin_reserved_effect(admitted.reservation.reservation_id, &request.operation_id)
        .await
        .unwrap();
    store.pool.close().await;

    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let uncertainty = Digest32::of_bytes(b"crash-before-terminal-observation");
    let quarantined = reopened
        .quarantine_reservation(admitted.reservation.reservation_id, uncertainty)
        .await
        .unwrap();
    assert_eq!(quarantined.state, ReservationState::Quarantined);
    let reconciled = reopened
        .reconcile_reservation(
            quarantined.reservation_id,
            ReservationReconcileOutcome::NotApplied {
                terminal_evidence: Digest32::of_bytes(b"provider-status:not-applied"),
            },
        )
        .await
        .unwrap();
    assert_eq!(reconciled.state, ReservationState::Cancelled);
    let snapshot = reopened.quota_snapshot(&quota).await.unwrap();
    assert_eq!((snapshot.reserved, snapshot.consumed), (0, 0));
}


fn replay_message(
    key: &SigningKey,
    issuer_id: &StableId,
    epoch: u64,
    sequence: u64,
) -> (IssuerRegistration, SignedMessage) {
    let registration = IssuerRegistration {
        issuer_id: issuer_id.clone(),
        key_epoch: Generation::new(epoch).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer_id.clone(),
        key_epoch: registration.key_epoch,
        message_id: id(&format!("message:checkpoint:{epoch}:{sequence}")),
        subject_id: id("subject:checkpoint"),
        scope_digest: Digest32::of_bytes(b"checkpoint-scope"),
        payload_digest: Digest32::of_bytes(b"checkpoint-payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (registration, SignedMessage { claims, signature })
}

#[tokio::test]
async fn replay_checkpoint_detects_restore_before_latest_external_anchor() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let key = SigningKey::from_bytes(&[77; 32]);
    let issuer_id = id("issuer:checkpoint");
    let (issuer, first) = replay_message(&key, &issuer_id, 1, 10);
    store
        .admit_authbus_message(
            &issuer,
            &first,
            first.claims.scope_digest,
            first.claims.payload_digest,
        )
        .await
        .unwrap();
    let first_checkpoint = store.advance_authbus_replay_checkpoint(0).await.unwrap();

    let (_, second) = replay_message(&key, &issuer_id, 1, 11);
    store
        .admit_authbus_message(
            &issuer,
            &second,
            second.claims.scope_digest,
            second.claims.payload_digest,
        )
        .await
        .unwrap();
    // Legitimate replay growth after an anchor does not invalidate that anchor.
    store
        .verify_authbus_replay_checkpoint(&first_checkpoint)
        .await
        .unwrap();

    let latest = store
        .advance_authbus_replay_checkpoint(first_checkpoint.generation)
        .await
        .unwrap();
    store.verify_authbus_replay_checkpoint(&latest).await.unwrap();

    // Simulate restoring checkpoint metadata from the predecessor snapshot while
    // the independently retained latest checkpoint remains outside the restore.
    sqlx::query(
        "UPDATE authbus_replay_checkpoint
         SET generation = ?, replay_digest = ? WHERE singleton = 1",
    )
    .bind(first_checkpoint.generation.to_be_bytes().as_slice())
    .bind(first_checkpoint.replay_digest.as_array().as_slice())
    .execute(&store.pool)
    .await
    .unwrap();

    assert!(matches!(
        store.verify_authbus_replay_checkpoint(&latest).await,
        Err(AuthBusControlError::RollbackDetected)
    ));
}

#[tokio::test]
async fn retired_replay_epoch_stays_revoked_after_safe_compaction() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let key = SigningKey::from_bytes(&[78; 32]);
    let issuer_id = id("issuer:retirement");
    let (issuer_v1, message_v1) = replay_message(&key, &issuer_id, 1, 1);
    store
        .admit_authbus_message(
            &issuer_v1,
            &message_v1,
            message_v1.claims.scope_digest,
            message_v1.claims.payload_digest,
        )
        .await
        .unwrap();
    let checkpoint = store.advance_authbus_replay_checkpoint(0).await.unwrap();
    let key_digest = Digest32::of_bytes(key.verifying_key().as_bytes());
    store
        .observe_authbus_trust_head(&AuthBusTrustHead {
            issuer_id: issuer_id.clone(),
            revision: 2,
            key_epoch: 2,
            verifying_key_digest: key_digest,
            registration_digest: Digest32::of_bytes(b"trust-head:epoch-2"),
            revoked: false,
        })
        .await
        .unwrap();

    let compacted = store
        .retire_authbus_replay_epoch(&issuer_id, 1, &checkpoint)
        .await
        .unwrap();
    assert_eq!(compacted.generation, checkpoint.generation + 1);
    store
        .verify_authbus_replay_checkpoint(&compacted)
        .await
        .unwrap();

    let (_, replay_after_compaction) = replay_message(&key, &issuer_id, 1, 2);
    assert!(matches!(
        store
            .admit_authbus_message(
                &issuer_v1,
                &replay_after_compaction,
                replay_after_compaction.claims.scope_digest,
                replay_after_compaction.claims.payload_digest,
            )
            .await,
        Err(crate::AuthBusAdmissionError::Authentication(
            codex_hepta_authbus::Error::Revoked
        ))
    ));
}
