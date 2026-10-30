use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;
use crate::AuthBusVerifyingKey;
use crate::IssuerPurpose;
use crate::IssuerSpec;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeAttestationClaims;

fn sign(
    key: &PqNativeSigningKey,
    challenge: TrustedTimeChallenge,
    revision: u64,
    time: u64,
) -> SignedTrustedTimeAttestation {
    let claims = TrustedTimeAttestationClaims {
        issuer_id: StableId::new("issuer:pq-time").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        wall_time_ms: time,
        source_revision: revision,
        source_digest: Digest32::of_bytes(b"independent-time-source"),
        challenge: Some(challenge),
    };
    let signature = key
        .sign_exact_message(&claims.signing_bytes_for(AuthBusAlgorithm::MlDsa65V2))
        .unwrap()
        .into();
    SignedTrustedTimeAttestation { claims, signature }
}

#[tokio::test]
async fn pq_time_requires_a_fresh_one_use_challenge_and_persists_its_deadline() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("authority.sqlite");
    let store = AuthBusAuthorityStore::open_pq(&path).await.unwrap();
    let spki = PqNativeSigningKey::public_spki_from_seed(&[53; 32].into());
    let key = PqNativeSigningKey::from_owned_seed(
        [53; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki).unwrap(),
    )
    .unwrap();
    store
        .enroll_issuer(
            IssuerPurpose::TrustedTime,
            IssuerSpec {
                issuer_id: StableId::new("issuer:pq-time").unwrap(),
                key_epoch: Generation::new(1).unwrap(),
                verifying_key: AuthBusVerifyingKey::from_pq_spki(key.public_spki()).unwrap(),
            },
        )
        .await
        .unwrap();
    let challenge = store.trusted_time_challenge().await.unwrap().unwrap();
    let signed = sign(&key, challenge.clone(), 1, wall_clock_ms().unwrap());
    let sample = store
        .observe_trusted_time_attestation(&signed)
        .await
        .unwrap();
    assert!(matches!(
        store.observe_trusted_time_attestation(&signed).await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness)
    ));
    store.pool.close().await;
    let reopened = AuthBusAuthorityStore::open_pq(&path).await.unwrap();
    assert_eq!(
        reopened.last_trusted_time().await.unwrap(),
        Some(sample.clone())
    );
    assert!(matches!(
        reopened.observe_trusted_time_attestation(&signed).await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness)
    ));
    let mut stale = sample.clone();
    stale.valid_until_ms = Some(wall_clock_ms().unwrap());
    assert!(matches!(
        reopened.observe_time(stale).await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness)
    ));
    let naked_floor = TrustedTimeSample::new(
        sample.wall_time_ms,
        sample.source_revision,
        sample.source_digest,
    )
    .unwrap();
    assert!(matches!(
        reopened.observe_time(naked_floor).await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness)
    ));
    let challenge = reopened.trusted_time_challenge().await.unwrap().unwrap();
    let future = sign(
        &key,
        challenge.clone(),
        2,
        wall_clock_ms().unwrap() + CLOCK_SKEW_MS + 1000,
    );
    assert!(matches!(
        reopened.observe_trusted_time_attestation(&future).await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness)
    ));
    let fresh = sign(&key, challenge, 2, wall_clock_ms().unwrap());
    reopened
        .observe_trusted_time_attestation(&fresh)
        .await
        .unwrap();
    let now = wall_clock_ms().unwrap();
    let expired = TrustedTimeChallenge {
        nonce: Digest32::of_bytes(b"expired-test-challenge"),
        issued_at_ms: now - ROUND_TRIP_MS - 1,
        expires_at_ms: now - 1,
    };
    sqlx::query("INSERT INTO authbus_time_challenge VALUES (?, ?, ?)")
        .bind(expired.nonce.as_array().as_slice())
        .bind(u64_bytes(expired.issued_at_ms).as_slice())
        .bind(u64_bytes(expired.expires_at_ms).as_slice())
        .execute(&reopened.pool)
        .await
        .unwrap();
    let expired = sign(&key, expired, 3, wall_clock_ms().unwrap());
    assert!(matches!(
        reopened.observe_trusted_time_attestation(&expired).await,
        Err(AuthBusAuthorityError::InvalidTrustedTimeFreshness)
    ));
}
