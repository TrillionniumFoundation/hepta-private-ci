use std::sync::Arc;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::sync::RwLock;

use super::*;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::VerifiedIssuerHandle;

async fn issuer(
    key: &SigningKey,
    epoch: u64,
    state: IssuerLifecycleState,
    purpose: IssuerPurpose,
) -> VerifiedIssuerHandle {
    let guard = Arc::new(RwLock::new(())).read_owned().await;
    VerifiedIssuerHandle::from_record(
        IssuerRecord {
            issuer_id: StableId::new("issuer:one").unwrap(),
            purpose,
            key_epoch: Generation::new(epoch).unwrap(),
            verifying_key: key.verifying_key(),
            state,
            revision: 1,
        },
        guard,
    )
}

async fn fixture() -> (SigningKey, VerifiedIssuerHandle, SignedMessage) {
    let key = SigningKey::from_bytes(&[7; 32]);
    let issuer = issuer(
        &key,
        1,
        IssuerLifecycleState::Active,
        IssuerPurpose::Message,
    )
    .await;
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new("message:one").unwrap(),
        subject_id: StableId::new("subject:one").unwrap(),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence: 1,
        expires_at_ms: 2_000,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (key, issuer, SignedMessage { claims, signature })
}

#[tokio::test]
async fn signed_admission_rejects_payload_and_replay_identity_substitution() {
    let (_key, issuer, message) = fixture().await;
    let scope = message.claims.scope_digest;
    let payload = message.claims.payload_digest;
    assert!(
        message
            .authenticate(&issuer, scope, payload, /*now_ms*/ 1_000)
            .is_ok()
    );
    for field in 0..7 {
        let (_key, _unused, mut substituted) = fixture().await;
        match field {
            0 => substituted.claims.payload_digest = Digest32::of_bytes(b"other"),
            1 => substituted.claims.scope_digest = Digest32::of_bytes(b"other"),
            2 => substituted.claims.subject_id = StableId::new("other").unwrap(),
            3 => substituted.claims.message_id = StableId::new("other").unwrap(),
            4 => substituted.claims.sequence += 1,
            5 => substituted.claims.expires_at_ms += 1,
            6 => substituted.signature[0] ^= 1,
            _ => unreachable!(),
        }
        assert!(matches!(
            substituted.authenticate(&issuer, scope, payload, /*now_ms*/ 1_000),
            Err(Error::InvalidSignature)
        ));
    }
}

#[tokio::test]
async fn registry_sealed_handle_rejects_forged_revoked_epoch_and_purpose_substitution() {
    let (key, valid, message) = fixture().await;
    let scope = message.claims.scope_digest;
    let payload = message.claims.payload_digest;

    let epoch_substitution = issuer(
        &key,
        2,
        IssuerLifecycleState::Active,
        IssuerPurpose::Message,
    )
    .await;
    assert!(matches!(
        message.authenticate(&epoch_substitution, scope, payload, 1_000),
        Err(Error::IssuerMismatch)
    ));

    let revoked = issuer(
        &key,
        1,
        IssuerLifecycleState::Revoked,
        IssuerPurpose::Message,
    )
    .await;
    assert!(matches!(
        message.authenticate(&revoked, scope, payload, 1_000),
        Err(Error::Revoked)
    ));

    let wrong_purpose = issuer(
        &key,
        1,
        IssuerLifecycleState::Active,
        IssuerPurpose::Settlement,
    )
    .await;
    assert!(matches!(
        message.authenticate(&wrong_purpose, scope, payload, 1_000),
        Err(Error::IssuerMismatch)
    ));

    let forged_key = SigningKey::from_bytes(&[8; 32]);
    let forged = issuer(
        &forged_key,
        1,
        IssuerLifecycleState::Active,
        IssuerPurpose::Message,
    )
    .await;
    assert!(matches!(
        message.authenticate(&forged, scope, payload, 1_000),
        Err(Error::InvalidSignature)
    ));

    assert!(matches!(
        message.authenticate(&valid, scope, payload, /*now_ms*/ 2_000),
        Err(Error::Expired)
    ));
    assert!(matches!(
        message.authenticate(
            &valid,
            Digest32::of_bytes(b"other"),
            payload,
            /*now_ms*/ 1_000
        ),
        Err(Error::ScopeMismatch)
    ));
}
