use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use crate::IssuerLifecycleState;
use crate::IssuerPurpose;
use crate::IssuerRecord;

fn registration(key: &SigningKey, epoch: u64, state: IssuerLifecycleState) -> IssuerRegistration {
    IssuerRegistration::from_record(&IssuerRecord {
        issuer_id: StableId::new("issuer:one").unwrap(),
        purpose: IssuerPurpose::Message,
        key_epoch: Generation::new(epoch).unwrap(),
        verifying_key: key.verifying_key(),
        state,
        revision: 1,
    })
    .unwrap()
}

fn fixture() -> (SigningKey, IssuerRegistration, SignedMessage) {
    let key = SigningKey::from_bytes(&[7; 32]);
    let issuer = registration(&key, 1, IssuerLifecycleState::Active);
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

#[test]
fn signed_admission_rejects_payload_and_replay_identity_substitution() {
    let (_key, issuer, message) = fixture();
    let scope = message.claims.scope_digest;
    let payload = message.claims.payload_digest;
    assert!(
        message
            .authenticate(&issuer, scope, payload, /*now_ms*/ 1_000)
            .is_ok()
    );
    for field in 0..7 {
        let (_, issuer, mut substituted) = fixture();
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

#[test]
fn trusted_registration_and_current_expiry_are_required() {
    let (key, issuer, message) = fixture();
    let scope = message.claims.scope_digest;
    let payload = message.claims.payload_digest;
    let wrong_epoch = registration(&key, 2, IssuerLifecycleState::Active);
    assert!(matches!(
        message.authenticate(&wrong_epoch, scope, payload, /*now_ms*/ 1_000),
        Err(Error::IssuerMismatch)
    ));
    let revoked = registration(&key, 1, IssuerLifecycleState::Revoked);
    assert!(matches!(
        message.authenticate(&revoked, scope, payload, /*now_ms*/ 1_000),
        Err(Error::Revoked)
    ));
    assert!(matches!(
        message.authenticate(&issuer, scope, payload, /*now_ms*/ 2_000),
        Err(Error::Expired)
    ));
    assert!(matches!(
        message.authenticate(
            &issuer,
            Digest32::of_bytes(b"other"),
            payload,
            /*now_ms*/ 1_000
        ),
        Err(Error::ScopeMismatch)
    ));
}
