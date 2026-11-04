use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::IssuerPurpose;
use crate::IssuerSpec;

#[tokio::test]
async fn pq_profile_key_rotation_and_revocation_survive_reopen_without_downgrade() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("authority.sqlite");
    let store = AuthBusAuthorityStore::open_pq(&path).await.unwrap();
    let spki = PqNativeSigningKey::public_spki_from_seed(&[47; 32].into());
    let pin = ml_dsa_65_key_id_from_spki(&spki).unwrap();
    let key = PqNativeSigningKey::from_owned_seed([47; 32].into(), pin).unwrap();
    let spec = IssuerSpec {
        issuer_id: StableId::new("issuer:pq").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: AuthBusVerifyingKey::from_pq_spki(key.public_spki()).unwrap(),
    };
    store
        .enroll_issuer(IssuerPurpose::Message, spec.clone())
        .await
        .unwrap();
    let snapshot = store
        .message_issuer(&spec.issuer_id, spec.key_epoch)
        .await
        .unwrap();
    assert_eq!(snapshot.verifying_key, spec.verifying_key);
    let mut classic = spec.clone();
    classic.issuer_id = StableId::new("issuer:classic").unwrap();
    classic.verifying_key = SigningKey::from_bytes(&[19; 32]).verifying_key().into();
    assert!(matches!(
        store.enroll_issuer(IssuerPurpose::Message, classic).await,
        Err(AuthBusAuthorityError::CryptoProfileMismatch)
    ));
    let mut next = spec.clone();
    next.key_epoch = Generation::new(2).unwrap();
    store
        .rotate_issuer(IssuerPurpose::Message, next.clone(), spec.key_epoch, 1)
        .await
        .unwrap();
    store.pool.close().await;
    assert!(matches!(
        AuthBusAuthorityStore::open(&path).await,
        Err(AuthBusAuthorityError::CryptoProfileMismatch)
    ));
    let reopened = AuthBusAuthorityStore::open_pq(&path).await.unwrap();
    assert!(
        reopened
            .message_issuer(&spec.issuer_id, spec.key_epoch)
            .await
            .unwrap()
            .revoked
    );
    assert!(
        !reopened
            .message_issuer(&next.issuer_id, next.key_epoch)
            .await
            .unwrap()
            .revoked
    );
    reopened
        .revoke_issuer(IssuerPurpose::Message, &next.issuer_id, next.key_epoch, 1)
        .await
        .unwrap();
    reopened.pool.close().await;
    let recovered = AuthBusAuthorityStore::open_pq(&path).await.unwrap();
    assert!(
        recovered
            .message_issuer(&next.issuer_id, next.key_epoch)
            .await
            .unwrap()
            .revoked
    );
}

#[tokio::test]
async fn authority_profile_is_persistent_and_binds_the_recovery_frontier() {
    let root = tempfile::tempdir().unwrap();
    let classic_path = root.path().join("classic.sqlite");
    let classic = AuthBusAuthorityStore::open(&classic_path).await.unwrap();
    let pq = AuthBusAuthorityStore::open_pq(&root.path().join("pq.sqlite"))
        .await
        .unwrap();
    assert_ne!(
        classic.authority_frontier_digest().await.unwrap(),
        pq.authority_frontier_digest().await.unwrap()
    );
    assert!(
        sqlx::query("UPDATE authbus_crypto_profile SET auth_version = 1")
            .execute(&pq.pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM authbus_crypto_profile")
            .execute(&pq.pool)
            .await
            .is_err()
    );
    classic.pool.close().await;
    assert!(matches!(
        AuthBusAuthorityStore::open_pq(&classic_path).await,
        Err(AuthBusAuthorityError::CryptoProfileMismatch)
    ));
}
