use codex_hepta_authbus::AuthBusAlgorithm;
use codex_hepta_authbus::AuthBusAuthorityStore;
use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

use super::*;
use crate::AuthBusAdmissionError;

#[tokio::test]
async fn pq_retirement_requires_the_exact_pinned_revoked_key_and_profile() {
    let temp = tempfile::tempdir().unwrap();
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
    );
    let store = HeptaEvidenceStore::open(&config).await.unwrap();
    store
        .bind_authbus_profile(AuthBusAlgorithm::MlDsa65V2)
        .await
        .unwrap();
    let spki = PqNativeSigningKey::public_spki_from_seed(&[101; 32].into());
    let mut issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:retirement").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: AuthBusVerifyingKey::from_pq_spki(&spki).unwrap(),
        revoked: false,
    };
    store.pin_authbus_issuer(&issuer).await.unwrap();
    issuer.revoked = true;
    store.pin_authbus_issuer(&issuer).await.unwrap();
    let external = ReplayCheckpoint {
        generation: 1,
        digest: store.authbus_replay_frontier_digest().await.unwrap(),
    };
    store
        .initialize_authbus_restore_checkpoint(external)
        .await
        .unwrap();
    let other = PqNativeSigningKey::public_spki_from_seed(&[103; 32].into());
    let keys = [
        ed25519_dalek::SigningKey::from_bytes(&[101; 32])
            .verifying_key()
            .into(),
        AuthBusVerifyingKey::from_pq_spki(&other).unwrap(),
        issuer.verifying_key.clone(),
    ];
    for (index, verifying_key) in keys.into_iter().enumerate() {
        let path = temp.path().join(format!("authority-{index}.sqlite"));
        let authority = match verifying_key.algorithm() {
            AuthBusAlgorithm::Ed25519V1 => AuthBusAuthorityStore::open(&path).await.unwrap(),
            AuthBusAlgorithm::MlDsa65V2 => AuthBusAuthorityStore::open_pq(&path).await.unwrap(),
        };
        authority
            .enroll_issuer(
                IssuerPurpose::Message,
                IssuerSpec {
                    issuer_id: issuer.issuer_id.clone(),
                    key_epoch: issuer.key_epoch,
                    verifying_key,
                },
            )
            .await
            .unwrap();
        authority
            .revoke_issuer(
                IssuerPurpose::Message,
                &issuer.issuer_id,
                issuer.key_epoch,
                1,
            )
            .await
            .unwrap();
        let retirement = authority
            .retire_issuer_epoch(
                IssuerPurpose::Message,
                &issuer.issuer_id,
                issuer.key_epoch,
                2,
            )
            .await
            .unwrap();
        let result = store
            .retire_authbus_replay_epoch(&retirement, external)
            .await;
        match index {
            0 => assert!(matches!(
                result,
                Err(AuthBusRecoveryError::Admission(
                    AuthBusAdmissionError::CryptoProfileMismatch
                ))
            )),
            1 => assert!(matches!(
                result,
                Err(AuthBusRecoveryError::Admission(
                    AuthBusAdmissionError::IssuerFloorMismatch
                ))
            )),
            2 => {
                let pending = result.unwrap();
                assert_eq!(pending.generation, external.generation + 1);
                store
                    .advance_authbus_restore_checkpoint(external.generation, pending)
                    .await
                    .unwrap();
            }
            _ => unreachable!(),
        }
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_retired_epochs")
            .fetch_one(&store.pool)
            .await
            .unwrap();
        assert_eq!(count, i64::from(index == 2));
        if index != 2 {
            assert_eq!(
                store.pending_authbus_restore_checkpoint().await.unwrap(),
                None
            );
            assert_eq!(
                store
                    .reconcile_authbus_restore_checkpoint(external)
                    .await
                    .unwrap(),
                None
            );
        }
    }
}
