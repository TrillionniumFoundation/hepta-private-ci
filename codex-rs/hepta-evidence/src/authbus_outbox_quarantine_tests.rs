use std::time::Duration;

use codex_hepta_authbus::Error;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::*;

fn config(path: &std::path::Path) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(path.to_path_buf()).unwrap())
}

async fn enqueue(
    store: &HeptaEvidenceStore,
    sequence: u64,
) -> (IssuerRegistration, AuthBusDeliveryStatus) {
    let key = SigningKey::from_bytes(&[43; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:relay").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!("message:{sequence}")).unwrap(),
        subject_id: StableId::new("subject:relay").unwrap(),
        scope_digest: Digest32::of_bytes(b"relay route"),
        payload_digest: Digest32::of_bytes(b"relay payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    let message = SignedMessage { claims, signature };
    let status = store
        .enqueue_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"relay payload",
        )
        .await
        .unwrap();
    (issuer, status)
}

async fn claim(
    store: &HeptaEvidenceStore,
    issuer: &IssuerRegistration,
    delivery_id: Digest32,
    lease_ms: i64,
) -> Result<AuthBusDelivery, AuthBusOutboxError> {
    store
        .claim_authbus_delivery(
            issuer,
            AuthBusClaimRequest {
                delivery_id,
                subject_id: &StableId::new("subject:relay").unwrap(),
                scope_digest: Digest32::of_bytes(b"relay route"),
                worker_id: &StableId::new("worker:relay").unwrap(),
                lease_ms,
            },
        )
        .await
}

#[tokio::test]
async fn quarantine_requires_current_fence_and_survives_reopen_without_acknowledgement() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let (issuer, queued) = enqueue(&store, /*sequence*/ 1).await;
    let (_, other) = enqueue(&store, /*sequence*/ 2).await;
    let delivery = claim(
        &store,
        &issuer,
        queued.delivery_id,
        /*lease_ms*/ 60_000,
    )
    .await
    .unwrap();
    assert_eq!(delivery.attempts, 1);
    let renewed = store
        .renew_authbus_delivery(&issuer, &delivery.lease, /*lease_ms*/ 60_000)
        .await
        .unwrap();
    let mut expected = store
        .authbus_delivery_status(queued.delivery_id)
        .await
        .unwrap();
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await,
        Err(AuthBusOutboxError::StaleLease)
    ));
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
    store
        .quarantine_authbus_delivery(&issuer, &renewed)
        .await
        .unwrap();
    expected.state = AuthBusDeliveryState::Quarantined;
    expected.fence += 1;
    expected.lease_until_ms = None;
    store.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    assert_eq!(
        reopened
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
    assert_eq!(
        reopened
            .authbus_delivery_status(other.delivery_id)
            .await
            .unwrap(),
        other
    );
    assert_eq!(enqueue(&reopened, /*sequence*/ 1).await.1, expected);
    assert!(matches!(
        claim(
            &reopened,
            &issuer,
            queued.delivery_id,
            /*lease_ms*/ 60_000
        )
        .await,
        Err(AuthBusOutboxError::Unavailable)
    ));
    assert!(matches!(
        reopened
            .ack_authbus_delivery(&issuer, &renewed, Digest32::of_bytes(b"late ack"))
            .await,
        Err(AuthBusOutboxError::Unavailable)
    ));
}

#[tokio::test]
async fn recovered_claim_reports_attempt_and_fences_expired_quarantine_worker() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(temp.path());
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let (issuer, queued) = enqueue(&store, /*sequence*/ 1).await;
    let original = claim(&store, &issuer, queued.delivery_id, /*lease_ms*/ 1)
        .await
        .unwrap();
    assert_eq!(original.attempts, 1);
    store.pool.close().await;
    tokio::time::sleep(Duration::from_millis(3)).await;
    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    assert!(matches!(
        reopened
            .quarantine_authbus_delivery(&issuer, &original.lease)
            .await,
        Err(AuthBusOutboxError::StaleLease)
    ));
    let recovered = claim(
        &reopened,
        &issuer,
        queued.delivery_id,
        /*lease_ms*/ 60_000,
    )
    .await
    .unwrap();
    assert_eq!(
        (recovered.lease.delivery_id(), recovered.attempts),
        (original.lease.delivery_id(), 2)
    );
    let mut expected = reopened
        .authbus_delivery_status(queued.delivery_id)
        .await
        .unwrap();
    assert!(matches!(
        reopened
            .quarantine_authbus_delivery(&issuer, &original.lease)
            .await,
        Err(AuthBusOutboxError::StaleLease)
    ));
    assert_eq!(
        reopened
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
    reopened
        .quarantine_authbus_delivery(&issuer, &recovered.lease)
        .await
        .unwrap();
    expected.state = AuthBusDeliveryState::Quarantined;
    expected.fence += 1;
    expected.lease_until_ms = None;
    assert_eq!(
        reopened
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
}

#[tokio::test]
async fn quarantine_rechecks_current_issuer_and_does_not_retire_other_messages() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(temp.path()))
        .await
        .unwrap();
    let (mut issuer, queued) = enqueue(&store, /*sequence*/ 1).await;
    let (_, other) = enqueue(&store, /*sequence*/ 2).await;
    let delivery = claim(
        &store,
        &issuer,
        queued.delivery_id,
        /*lease_ms*/ 60_000,
    )
    .await
    .unwrap();
    let mut expected = store
        .authbus_delivery_status(queued.delivery_id)
        .await
        .unwrap();
    issuer.key_epoch = Generation::new(2).unwrap();
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::IssuerMismatch)
        ))
    ));
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
    issuer.key_epoch = queued.key_epoch;
    issuer.revoked = true;
    assert!(matches!(
        store
            .quarantine_authbus_delivery(&issuer, &delivery.lease)
            .await,
        Err(AuthBusOutboxError::Admission(
            AuthBusAdmissionError::Authentication(Error::Revoked)
        ))
    ));
    expected.state = AuthBusDeliveryState::Quarantined;
    expected.fence += 1;
    expected.lease_until_ms = None;
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        expected
    );
    assert_eq!(
        store
            .authbus_delivery_status(other.delivery_id)
            .await
            .unwrap(),
        other
    );
}
