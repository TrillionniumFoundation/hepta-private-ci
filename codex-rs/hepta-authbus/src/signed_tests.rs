use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

fn fixture() -> (IssuerRegistration, SignedMessage) {
    let key = SigningKey::from_bytes(&[7; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:one").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
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
    (issuer, SignedMessage { claims, signature })
}

#[test]
fn signed_admission_rejects_payload_and_replay_identity_substitution() {
    let (issuer, message) = fixture();
    let scope = message.claims.scope_digest;
    let payload = message.claims.payload_digest;
    assert!(
        message
            .authenticate(&issuer, scope, payload, /*now_ms*/ 1_000)
            .is_ok()
    );
    for field in 0..7 {
        let (_, mut substituted) = fixture();
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
    let (mut issuer, message) = fixture();
    let scope = message.claims.scope_digest;
    let payload = message.claims.payload_digest;
    issuer.key_epoch = Generation::new(2).unwrap();
    assert!(matches!(
        message.authenticate(&issuer, scope, payload, /*now_ms*/ 1_000),
        Err(Error::IssuerMismatch)
    ));
    issuer.key_epoch = message.claims.key_epoch;
    issuer.revoked = true;
    assert!(matches!(
        message.authenticate(&issuer, scope, payload, /*now_ms*/ 1_000),
        Err(Error::Revoked)
    ));
    issuer.revoked = false;
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
