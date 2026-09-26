use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeAttestationClaims;
use codex_hepta_types::Digest32;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identifier")
}

async fn store() -> (TempDir, AuthBusAuthorityStore) {
    let root = TempDir::new().expect("temp dir");
    let store = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("open authority store");
    (root, store)
}

fn spec(issuer_id: &str, epoch: u64, key: &SigningKey) -> IssuerSpec {
    IssuerSpec {
        issuer_id: id(issuer_id),
        key_epoch: Generation::new(epoch).expect("generation"),
        verifying_key: key.verifying_key(),
    }
}

#[tokio::test]
async fn issuer_rotation_revocation_and_retirement_are_monotonic() {
    let (_root, store) = store().await;
    let old_key = SigningKey::from_bytes(&[11; 32]);
    let new_key = SigningKey::from_bytes(&[12; 32]);
    let issuer_id = id("issuer:operator");
    let first = store
        .enroll_issuer(IssuerPurpose::Message, spec("issuer:operator", 1, &old_key))
        .await
        .expect("enroll issuer");
    assert_eq!(first.state(), IssuerLifecycleState::Active);
    assert_eq!(
        store
            .issuer_record(
                IssuerPurpose::Message,
                &issuer_id,
                Generation::new(1).expect("generation"),
            )
            .await
            .expect("registration")
            .state(),
        IssuerLifecycleState::Active
    );

    let second = store
        .rotate_issuer(
            IssuerPurpose::Message,
            spec("issuer:operator", 2, &new_key),
            Generation::new(1).expect("generation"),
            /*expected_revision*/ 1,
        )
        .await
        .expect("rotate issuer");
    assert_eq!(second.key_epoch().get(), 2);
    assert_eq!(
        store
            .issuer_record(
                IssuerPurpose::Message,
                &issuer_id,
                Generation::new(1).expect("generation"),
            )
            .await
            .expect("old registration")
            .state(),
        IssuerLifecycleState::Revoked
    );

    let revoked = store
        .revoke_issuer(
            IssuerPurpose::Message,
            &issuer_id,
            Generation::new(2).expect("generation"),
            /*expected_revision*/ 1,
        )
        .await
        .expect("revoke current issuer");
    assert_eq!(revoked.state(), IssuerLifecycleState::Revoked);
    let retirement = store
        .retire_issuer_epoch(
            IssuerPurpose::Message,
            &issuer_id,
            Generation::new(1).expect("generation"),
            /*expected_revision*/ 2,
        )
        .await
        .expect("retire old epoch");
    assert_eq!(retirement.issuer_id(), &issuer_id);
    assert_eq!(retirement.key_epoch().get(), 1);
    assert_eq!(retirement.purpose(), IssuerPurpose::Message);
    assert!(!retirement.retirement_digest().is_zero());
    assert!(matches!(
        store
            .rotate_issuer(
                IssuerPurpose::Message,
                spec("issuer:operator", 1, &old_key),
                Generation::new(2).expect("generation"),
                /*expected_revision*/ 2,
            )
            .await,
        Err(AuthBusAuthorityError::IssuerMissing) | Err(AuthBusAuthorityError::KeyEpochRegression)
    ));
}

#[tokio::test]
async fn trusted_time_requires_an_active_registered_signer() {
    let (_root, store) = store().await;
    let key = SigningKey::from_bytes(&[13; 32]);
    store
        .enroll_issuer(IssuerPurpose::TrustedTime, spec("issuer:time", 1, &key))
        .await
        .expect("enroll time issuer");
    let claims = TrustedTimeAttestationClaims {
        issuer_id: id("issuer:time"),
        key_epoch: Generation::new(1).expect("generation"),
        wall_time_ms: 2_000,
        source_revision: 7,
        source_digest: Digest32::of_bytes(b"external-time-source"),
    };
    let signed = SignedTrustedTimeAttestation {
        signature: key.sign(&claims.signing_bytes()).to_bytes(),
        claims: claims.clone(),
    };
    let observed = store
        .observe_trusted_time_attestation(&signed)
        .await
        .expect("observe trusted time");
    assert_eq!(observed.wall_time_ms, 2_000);
    assert_eq!(
        store.last_trusted_time().await.expect("last trusted time"),
        Some(observed)
    );

    let mut tampered = SignedTrustedTimeAttestation {
        claims,
        signature: signed.signature,
    };
    tampered.claims.wall_time_ms = 2_001;
    assert!(matches!(
        store.observe_trusted_time_attestation(&tampered).await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeSignature)
    ));
    store
        .revoke_issuer(
            IssuerPurpose::TrustedTime,
            &id("issuer:time"),
            Generation::new(1).expect("generation"),
            /*expected_revision*/ 1,
        )
        .await
        .expect("revoke time issuer");
    assert!(matches!(
        store.observe_trusted_time_attestation(&signed).await,
        Err(AuthBusAuthorityError::TrustedTimeIssuerMismatch)
    ));
}
