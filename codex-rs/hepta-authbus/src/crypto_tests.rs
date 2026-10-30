use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use crate::AuthBusAlgorithm;
use crate::AuthBusSignature;
use crate::AuthBusVerifyingKey;
use crate::IssuerRegistration;
use crate::SignedMessage;
use crate::SignedMessageClaims;

pub(crate) fn pq_key(seed: u8) -> PqNativeSigningKey {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    let pin = super::ml_dsa_65_key_id_from_spki(&spki).unwrap();
    PqNativeSigningKey::from_owned_seed([seed; 32].into(), pin).unwrap()
}

#[test]
fn trusted_key_selects_exact_algorithm_and_message_domain() {
    let key = pq_key(47);
    let verifier = AuthBusVerifyingKey::from_pq_spki(key.public_spki()).unwrap();
    let claims = SignedMessageClaims {
        issuer_id: StableId::new("issuer").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        message_id: StableId::new("message").unwrap(),
        subject_id: StableId::new("subject").unwrap(),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence: 1,
        expires_at_ms: 100,
    };
    let issuer = IssuerRegistration {
        issuer_id: claims.issuer_id.clone(),
        key_epoch: claims.key_epoch,
        verifying_key: verifier,
        revoked: false,
    };
    let valid = key
        .sign_exact_message(&claims.signing_bytes_for(AuthBusAlgorithm::MlDsa65V2))
        .unwrap();
    let mut message = SignedMessage {
        claims,
        signature: valid.into(),
    };
    assert!(
        message
            .authenticate(
                &issuer,
                message.claims.scope_digest,
                message.claims.payload_digest,
                10
            )
            .is_ok()
    );
    message.signature = key
        .sign_exact_message(&message.claims.signing_bytes())
        .unwrap()
        .into();
    assert!(
        message
            .authenticate(
                &issuer,
                message.claims.scope_digest,
                message.claims.payload_digest,
                10
            )
            .is_err()
    );
    let classic = SigningKey::from_bytes(&[19; 32]);
    message.signature = classic
        .sign(&message.claims.signing_bytes())
        .to_bytes()
        .into();
    assert!(
        message
            .authenticate(
                &issuer,
                message.claims.scope_digest,
                message.claims.payload_digest,
                10
            )
            .is_err()
    );
    assert!(
        AuthBusSignature::from_bytes(AuthBusAlgorithm::MlDsa65V2, &valid[..valid.len() - 1])
            .is_err()
    );
    assert_eq!(
        issuer.verifying_key.algorithm(),
        AuthBusAlgorithm::MlDsa65V2
    );
}
