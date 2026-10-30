use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

use super::*;
use crate::AuthBusClaimRequest;
use crate::AuthBusDeliveryState;

#[tokio::test]
async fn pq_outbox_requires_explicit_profile_and_recovers_exact_signature_without_downgrade() {
    let temp = tempfile::tempdir().unwrap();
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
    );
    let store = HeptaEvidenceStore::open(&config).await.unwrap();
    let spki = PqNativeSigningKey::public_spki_from_seed(&[61; 32].into());
    let key = PqNativeSigningKey::from_owned_seed(
        [61; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki).unwrap(),
    )
    .unwrap();
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:pq-outbox").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: AuthBusVerifyingKey::from_pq_spki(key.public_spki()).unwrap(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new("message:pq").unwrap(),
        subject_id: StableId::new("subject:pq").unwrap(),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence: 1,
        expires_at_ms: crate::store::now_millis().unwrap() as u64 + 60_000,
    };
    let signature = key
        .sign_exact_message(&claims.signing_bytes_for(AuthBusAlgorithm::MlDsa65V2))
        .unwrap()
        .into();
    let message = SignedMessage { claims, signature };
    assert!(
        store
            .enqueue_authbus_message(
                &issuer,
                &message,
                &message.claims.subject_id,
                message.claims.scope_digest,
                b"payload"
            )
            .await
            .is_err()
    );
    store
        .bind_authbus_profile(AuthBusAlgorithm::MlDsa65V2)
        .await
        .unwrap();
    store.pin_authbus_issuer(&issuer).await.unwrap();
    let queued = store
        .enqueue_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"payload",
        )
        .await
        .unwrap();
    let other_spki = PqNativeSigningKey::public_spki_from_seed(&[67; 32].into());
    let mut revoked = IssuerRegistration {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        verifying_key: ed25519_dalek::SigningKey::from_bytes(&[61; 32])
            .verifying_key()
            .into(),
        revoked: true,
    };
    assert!(store.quarantine_authbus_issuer(&revoked).await.is_err());
    revoked.verifying_key = AuthBusVerifyingKey::from_pq_spki(&other_spki).unwrap();
    assert!(store.quarantine_authbus_issuer(&revoked).await.is_err());
    revoked.verifying_key = issuer.verifying_key.clone();
    // Even the right key cannot assert revocation without the owner's pin.
    assert!(store.quarantine_authbus_issuer(&revoked).await.is_err());
    assert_eq!(
        store
            .authbus_delivery_status(queued.delivery_id)
            .await
            .unwrap(),
        queued
    );
    store.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&config).await.unwrap();
    assert!(matches!(
        reopened
            .bind_authbus_profile(AuthBusAlgorithm::Ed25519V1)
            .await,
        Err(AuthBusAdmissionError::CryptoProfileMismatch)
    ));
    let same = reopened
        .enqueue_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            b"payload",
        )
        .await
        .unwrap();
    assert_eq!(same, queued);
    let worker = StableId::new("worker:pq").unwrap();
    let delivery = reopened
        .claim_authbus_delivery(
            &issuer,
            AuthBusClaimRequest {
                delivery_id: queued.delivery_id,
                subject_id: &message.claims.subject_id,
                scope_digest: message.claims.scope_digest,
                worker_id: &worker,
                lease_ms: 30_000,
            },
        )
        .await
        .unwrap();
    assert_eq!(delivery.message.signature, message.signature);
    assert_eq!(delivery.message.signature.len(), 3309);
    reopened
        .ack_authbus_delivery(
            &issuer,
            &delivery.lease,
            Digest32::of_bytes(b"queue-accepted"),
        )
        .await
        .unwrap();
    let mut next_claims = message.claims.clone();
    next_claims.sequence = 2;
    next_claims.message_id = StableId::new("message:pq:2").unwrap();
    let next = SignedMessage {
        signature: key
            .sign_exact_message(&next_claims.signing_bytes_for(AuthBusAlgorithm::MlDsa65V2))
            .unwrap()
            .into(),
        claims: next_claims,
    };
    let next_queued = reopened
        .enqueue_authbus_message(
            &issuer,
            &next,
            &next.claims.subject_id,
            next.claims.scope_digest,
            b"payload",
        )
        .await
        .unwrap();
    reopened.pin_authbus_issuer(&revoked).await.unwrap();
    assert_eq!(
        reopened.quarantine_authbus_issuer(&revoked).await.unwrap(),
        1
    );
    assert_eq!(
        reopened
            .authbus_delivery_status(next_queued.delivery_id)
            .await
            .unwrap()
            .state,
        AuthBusDeliveryState::Quarantined
    );
}

#[tokio::test]
async fn missing_profile_barrier_trigger_is_rejected_on_reopen() {
    let temp = tempfile::tempdir().unwrap();
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
    );
    let store = HeptaEvidenceStore::open(&config).await.unwrap();
    store
        .bind_authbus_profile(AuthBusAlgorithm::MlDsa65V2)
        .await
        .unwrap();
    sqlx::query("DROP TRIGGER authbus_profile_immutable")
        .execute(&store.pool)
        .await
        .unwrap();
    store.pool.close().await;
    assert!(matches!(
        HeptaEvidenceStore::open(&config).await,
        Err(EvidenceError::Corrupt(_))
    ));
}
