use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use super::*;

fn issuer(seed: u8, epoch: u64) -> IssuerRegistration {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    IssuerRegistration {
        issuer_id: StableId::new("issuer:floor").unwrap(),
        key_epoch: Generation::new(epoch).unwrap(),
        verifying_key: AuthBusVerifyingKey::from_pq_spki(&spki).unwrap(),
        revoked: false,
    }
}

#[tokio::test]
async fn pq_owner_key_substitution_rotation_revocation_and_clock_rollback_are_fenced() {
    let temp = tempfile::tempdir().unwrap();
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
    );
    let store = HeptaEvidenceStore::open(&config).await.unwrap();
    store
        .bind_authbus_profile(AuthBusAlgorithm::MlDsa65V2)
        .await
        .unwrap();
    let old = issuer(73, 1);
    store.pin_authbus_issuer(&old).await.unwrap();
    let before = store.authbus_replay_frontier_digest().await.unwrap();
    assert!(matches!(
        store.pin_authbus_issuer(&issuer(79, 1)).await,
        Err(AuthBusAdmissionError::IssuerFloorMismatch)
    ));
    let mut next = issuer(79, 2);
    store.pin_authbus_issuer(&next).await.unwrap();
    assert_ne!(
        store.authbus_replay_frontier_digest().await.unwrap(),
        before
    );
    assert!(matches!(
        store.pin_authbus_issuer(&old).await,
        Err(AuthBusAdmissionError::IssuerFloorMismatch)
    ));
    let mut tx = store.pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
    assert!(matches!(
        require_current_issuer(&mut tx, &old).await,
        Err(AuthBusAdmissionError::IssuerFloorMismatch)
    ));
    tx.rollback().await.unwrap();
    next.revoked = true;
    store.pin_authbus_issuer(&next).await.unwrap();
    store.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&config).await.unwrap();
    next.revoked = false;
    assert!(matches!(
        reopened.pin_authbus_issuer(&next).await,
        Err(AuthBusAdmissionError::IssuerFloorMismatch)
    ));
    next.revoked = true;
    sqlx::query("UPDATE authbus_issuer_floor SET wall_time_floor_ms = ?")
        .bind(now_millis().unwrap() + 60_000)
        .execute(&reopened.pool)
        .await
        .unwrap();
    assert!(matches!(
        reopened.pin_authbus_issuer(&next).await,
        Err(AuthBusAdmissionError::IssuerFloorMismatch)
    ));
    assert!(
        sqlx::query("UPDATE authbus_issuer_floor SET revoked = 0")
            .execute(&reopened.pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM authbus_issuer_floor")
            .execute(&reopened.pool)
            .await
            .is_err()
    );
}
