use codex_hepta_authbus::AuthBusAlgorithm;
use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use super::*;
use crate::AuthBusRecoveryError;
use crate::HeptaEvidenceStore;
use crate::ReplayCheckpoint;

fn issuer() -> IssuerRegistration {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[71; 32].into());
    IssuerRegistration {
        issuer_id: StableId::new("issuer:policy").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: AuthBusVerifyingKey::from_pq_spki(&spki).unwrap(),
        revoked: false,
    }
}

#[tokio::test]
async fn owner_policy_reopens_pending_checkpoint_and_cannot_bless_later_policy_drift() {
    let temp = tempfile::tempdir().unwrap();
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
    );
    let store = HeptaEvidenceStore::open(&config).await.unwrap();
    store
        .bind_authbus_profile(AuthBusAlgorithm::MlDsa65V2)
        .await
        .unwrap();
    let initial = ReplayCheckpoint {
        generation: 1,
        digest: store.authbus_replay_frontier_digest().await.unwrap(),
    };
    store
        .initialize_authbus_restore_checkpoint(initial)
        .await
        .unwrap();
    let old = Digest32::of_bytes(b"owner-policy-with-thread");
    let current = Digest32::of_bytes(b"owner-policy-without-thread");
    store
        .pin_authbus_issuer_with_owner_policy(&issuer(), Generation::new(1).unwrap(), old)
        .await
        .unwrap();
    let pending = store
        .pending_authbus_restore_checkpoint()
        .await
        .unwrap()
        .unwrap();
    store.close().await;

    let reopened = HeptaEvidenceStore::open(&config).await.unwrap();
    assert_eq!(
        reopened
            .reconcile_authbus_restore_checkpoint(initial)
            .await
            .unwrap(),
        Some(pending)
    );
    reopened
        .advance_authbus_restore_checkpoint(initial.generation, pending)
        .await
        .unwrap();
    reopened
        .pin_authbus_issuer_with_owner_policy(&issuer(), Generation::new(2).unwrap(), current)
        .await
        .unwrap();
    let external = reopened
        .pending_authbus_restore_checkpoint()
        .await
        .unwrap()
        .unwrap();
    reopened
        .advance_authbus_restore_checkpoint(pending.generation, external)
        .await
        .unwrap();
    let before = reopened.authbus_replay_frontier_digest().await.unwrap();
    for (revision, digest) in [(1, old), (2, old)] {
        assert!(matches!(
            reopened
                .pin_authbus_issuer_with_owner_policy(
                    &issuer(),
                    Generation::new(revision).unwrap(),
                    digest
                )
                .await,
            Err(AuthBusAdmissionError::OwnerPolicyMismatch)
        ));
        assert_eq!(
            reopened.authbus_replay_frontier_digest().await.unwrap(),
            before
        );
        assert_eq!(
            reopened.pending_authbus_restore_checkpoint().await.unwrap(),
            None
        );
    }
    // A direct database edit that passes the monotonic SQL trigger still must
    // match the retained semantic checkpoint before any new policy can commit.
    sqlx::query("UPDATE authbus_owner_policy_floor SET policy_revision = ?")
        .bind(3_u64.to_be_bytes().as_slice())
        .execute(&reopened.pool)
        .await
        .unwrap();
    assert!(matches!(
        reopened
            .pin_authbus_issuer_with_owner_policy(&issuer(), Generation::new(3).unwrap(), current)
            .await,
        Err(AuthBusAdmissionError::Storage(EvidenceError::Corrupt(_)))
    ));
    assert!(matches!(
        reopened
            .reconcile_authbus_restore_checkpoint(external)
            .await,
        Err(AuthBusRecoveryError::RollbackDetected)
    ));
}

#[tokio::test]
async fn existing_pq_checkpoint_cannot_bootstrap_a_missing_owner_policy() {
    let temp = tempfile::tempdir().unwrap();
    let config = SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap(),
    );
    let store = HeptaEvidenceStore::open(&config).await.unwrap();
    store
        .bind_authbus_profile(AuthBusAlgorithm::MlDsa65V2)
        .await
        .unwrap();
    // This is the pre-policy owner lifecycle: an issuer has already been used
    // and checkpointed, while the newly introduced policy table is empty.
    store.pin_authbus_issuer(&issuer()).await.unwrap();
    let external = ReplayCheckpoint {
        generation: 1,
        digest: store.authbus_replay_frontier_digest().await.unwrap(),
    };
    store
        .initialize_authbus_restore_checkpoint(external)
        .await
        .unwrap();
    // Build the actual pre-0015 schema while retaining its original issuer and
    // external checkpoint. Only the unused new schema and its ledger row are
    // absent, as on an older installation; normal open must perform the upgrade.
    sqlx::raw_sql(
        "DROP TRIGGER authbus_owner_policy_monotonic;
        DROP TRIGGER authbus_owner_policy_no_delete;
        DROP TABLE authbus_owner_policy_floor;
        DELETE FROM _sqlx_migrations WHERE version = 15;",
    )
    .execute(&store.pool)
    .await
    .unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT MAX(version) FROM _sqlx_migrations")
            .fetch_one(&store.pool)
            .await
            .unwrap(),
        14
    );
    store.close().await;
    let reopened = HeptaEvidenceStore::open(&config).await.unwrap();
    assert_eq!(
        sqlx::query_scalar::<_, i64>("SELECT MAX(version) FROM _sqlx_migrations")
            .fetch_one(&reopened.pool)
            .await
            .unwrap(),
        15
    );
    assert!(matches!(
        reopened
            .pin_authbus_issuer_with_owner_policy(
                &issuer(),
                Generation::new(1).unwrap(),
                Digest32::of_bytes(b"unproven-current-policy")
            )
            .await,
        Err(AuthBusAdmissionError::OwnerPolicyInitializationRequired)
    ));
    assert_eq!(
        reopened.authbus_replay_frontier_digest().await.unwrap(),
        external.digest
    );
    assert_eq!(
        reopened.pending_authbus_restore_checkpoint().await.unwrap(),
        None
    );
}
