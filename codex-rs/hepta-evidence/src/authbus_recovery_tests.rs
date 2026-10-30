use codex_hepta_authbus::AuthBusAlgorithm;
use codex_hepta_authbus::AuthBusAuthorityStore;
use codex_hepta_authbus::AuthBusVerifyingKey;
use codex_hepta_authbus::Error;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::*;
use crate::AuthBusAdmissionError;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

#[tokio::test]
async fn unchanged_external_checkpoint_recomputes_clean_and_pending_replay_frontiers() {
    for algorithm in [AuthBusAlgorithm::Ed25519V1, AuthBusAlgorithm::MlDsa65V2] {
        for pending in [false, true] {
            let temp = TempDir::new().unwrap();
            let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
            let (_, mut issuer, mut message) = fixture(1);
            if algorithm == AuthBusAlgorithm::MlDsa65V2 {
                let spki = PqNativeSigningKey::public_spki_from_seed(&[97; 32].into());
                let key = PqNativeSigningKey::from_owned_seed(
                    [97; 32].into(),
                    ml_dsa_65_key_id_from_spki(&spki).unwrap(),
                )
                .unwrap();
                issuer.verifying_key = AuthBusVerifyingKey::from_pq_spki(&spki).unwrap();
                message.claims.expires_at_ms = now_millis().unwrap() as u64 + 60_000;
                message.signature = key
                    .sign_exact_message(&message.claims.signing_bytes_for(algorithm))
                    .unwrap()
                    .into();
                store.bind_authbus_profile(algorithm).await.unwrap();
                store.pin_authbus_issuer(&issuer).await.unwrap();
            }
            if !pending {
                admit(&store, &issuer, &message).await.unwrap();
            }
            let external = ReplayCheckpoint {
                generation: 1,
                digest: store.authbus_replay_frontier_digest().await.unwrap(),
            };
            store
                .initialize_authbus_restore_checkpoint(external)
                .await
                .unwrap();
            if pending {
                admit(&store, &issuer, &message).await.unwrap();
            }
            sqlx::query("UPDATE authbus_replay_sequences SET sequence = ?")
                .bind(0_u64.to_be_bytes().as_slice())
                .execute(&store.pool)
                .await
                .unwrap();
            let pending_before = store.pending_authbus_restore_checkpoint().await.unwrap();
            let drifted = store.authbus_replay_frontier_digest().await.unwrap();
            // Reusing the original valid signature must not restore the old
            // sequence and hide a second acceptance behind an identical digest.
            assert!(matches!(
                admit(&store, &issuer, &message).await,
                Err(AuthBusAdmissionError::Storage(EvidenceError::Corrupt(_)))
            ));
            assert!(matches!(
                store.pin_authbus_issuer(&issuer).await,
                Err(AuthBusAdmissionError::Storage(EvidenceError::Corrupt(_)))
            ));
            assert!(
                store
                    .enqueue_authbus_message(
                        &issuer,
                        &message,
                        &message.claims.subject_id,
                        message.claims.scope_digest,
                        b"payload"
                    )
                    .await
                    .is_err()
            );
            assert!(
                store
                    .pending_authbus_deliveries(
                        &message.claims.subject_id,
                        message.claims.scope_digest,
                        1
                    )
                    .await
                    .is_err()
            );
            assert_eq!(
                store.authbus_replay_frontier_digest().await.unwrap(),
                drifted
            );
            assert_eq!(
                store.pending_authbus_restore_checkpoint().await.unwrap(),
                pending_before
            );
            let queued: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_outbox")
                .fetch_one(&store.pool)
                .await
                .unwrap();
            assert_eq!(queued, 0);
            assert!(matches!(
                store.reconcile_authbus_restore_checkpoint(external).await,
                Err(AuthBusRecoveryError::RollbackDetected)
            ));
        }
    }
}

fn fixture(sequence: u64) -> (SigningKey, IssuerRegistration, SignedMessage) {
    let key = SigningKey::from_bytes(&[77; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:rollback").unwrap(),
        key_epoch: Generation::new(7).unwrap(),
        verifying_key: key.verifying_key().into(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!("message:{sequence}")).unwrap(),
        subject_id: StableId::new("subject:rollback").unwrap(),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (
        key,
        issuer,
        SignedMessage {
            claims,
            signature: signature.into(),
        },
    )
}

async fn admit(
    store: &HeptaEvidenceStore,
    issuer: &IssuerRegistration,
    message: &SignedMessage,
) -> Result<(), AuthBusAdmissionError> {
    store
        .admit_authbus_message(
            issuer,
            message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            message.claims.payload_digest,
        )
        .await
        .map(|_| ())
}

async fn initialize(store: &HeptaEvidenceStore, generation: u64) -> ReplayCheckpoint {
    let checkpoint = ReplayCheckpoint {
        generation,
        digest: store.authbus_replay_frontier_digest().await.unwrap(),
    };
    store
        .initialize_authbus_restore_checkpoint(checkpoint)
        .await
        .unwrap();
    checkpoint
}

#[tokio::test]
async fn every_replay_mutation_requires_exact_external_checkpoint_ack() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let first = initialize(&store, 1).await;

    let (_, issuer, message) = fixture(1);
    admit(&store, &issuer, &message).await.unwrap();
    let pending = store
        .pending_authbus_restore_checkpoint()
        .await
        .unwrap()
        .expect("replay mutation must stage a checkpoint");
    assert_eq!(pending.generation, 2);

    let (_, _, next) = fixture(2);
    assert!(matches!(
        admit(&store, &issuer, &next).await,
        Err(AuthBusAdmissionError::Authentication(
            Error::ExternalCheckpointRequired
        ))
    ));

    store
        .advance_authbus_restore_checkpoint(first.generation, pending)
        .await
        .unwrap();
    admit(&store, &issuer, &next).await.unwrap();
    assert_eq!(
        store
            .pending_authbus_restore_checkpoint()
            .await
            .unwrap()
            .expect("second mutation stages another checkpoint")
            .generation,
        3
    );
}

#[tokio::test]
async fn external_checkpoint_detects_real_old_database_restore() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let database = temp.path().join("hepta_evidence_2.sqlite");
    let backup = temp.path().join("authbus-old-backup.sqlite");

    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    initialize(&store, 1).await;
    sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
        .execute(&store.pool)
        .await
        .unwrap();
    store.pool.close().await;
    std::fs::copy(&database, &backup).unwrap();

    let current = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let (_, issuer, message) = fixture(1);
    admit(&current, &issuer, &message).await.unwrap();
    let external = current
        .pending_authbus_restore_checkpoint()
        .await
        .unwrap()
        .expect("new replay frontier");
    current
        .advance_authbus_restore_checkpoint(1, external)
        .await
        .unwrap();
    sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
        .execute(&current.pool)
        .await
        .unwrap();
    current.pool.close().await;

    let _ = std::fs::remove_file(temp.path().join("hepta_evidence_2.sqlite-wal"));
    let _ = std::fs::remove_file(temp.path().join("hepta_evidence_2.sqlite-shm"));
    std::fs::copy(&backup, &database).unwrap();

    let restored = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    assert!(matches!(
        restored
            .reconcile_authbus_restore_checkpoint(external)
            .await,
        Err(AuthBusRecoveryError::RollbackDetected)
    ));
}

#[tokio::test]
async fn issuer_retirement_proof_prunes_replay_rows_but_tombstone_prevents_resurrection() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let mut external = initialize(&store, 1).await;
    let (key, issuer, message) = fixture(1);
    admit(&store, &issuer, &message).await.unwrap();
    let pending = store
        .pending_authbus_restore_checkpoint()
        .await
        .unwrap()
        .unwrap();
    store
        .advance_authbus_restore_checkpoint(external.generation, pending)
        .await
        .unwrap();
    external = pending;

    let authority = AuthBusAuthorityStore::open(&temp.path().join("authbus-authority.sqlite"))
        .await
        .unwrap();
    authority
        .enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: issuer.issuer_id.clone(),
                key_epoch: issuer.key_epoch,
                verifying_key: key.verifying_key().into(),
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

    let retirement_pending = store
        .retire_authbus_replay_epoch(&retirement, external)
        .await
        .unwrap();
    store
        .advance_authbus_restore_checkpoint(external.generation, retirement_pending)
        .await
        .unwrap();

    let (_, stale_registration, replacement) = fixture(2);
    assert!(matches!(
        admit(&store, &stale_registration, &replacement).await,
        Err(AuthBusAdmissionError::Authentication(Error::Revoked))
    ));
}

#[tokio::test]
async fn altered_replay_checkpoint_schema_is_rejected_before_recovery() {
    for (table, drop_statement, recreate_statement) in [
        (
            "authbus_restore_checkpoint",
            "DROP TABLE authbus_restore_checkpoint",
            "CREATE TABLE authbus_restore_checkpoint (singleton INTEGER, generation BLOB)",
        ),
        (
            "authbus_restore_checkpoint_pending",
            "DROP TABLE authbus_restore_checkpoint_pending",
            "CREATE TABLE authbus_restore_checkpoint_pending (singleton INTEGER, generation BLOB)",
        ),
        (
            "authbus_retired_epochs",
            "DROP TABLE authbus_retired_epochs",
            "CREATE TABLE authbus_retired_epochs (singleton INTEGER, generation BLOB)",
        ),
    ] {
        let root = TempDir::new().unwrap();
        let settings = config(&root);
        let store = HeptaEvidenceStore::open(&settings).await.unwrap();
        sqlx::query(drop_statement)
            .execute(&store.pool)
            .await
            .unwrap();
        // Keep the name while removing all constraints. The migration ledger
        // remains valid, but this schema can no longer fence replay rollback.
        sqlx::query(recreate_statement)
            .execute(&store.pool)
            .await
            .unwrap();
        store.pool.close().await;
        assert!(
            matches!(
                HeptaEvidenceStore::open(&settings).await,
                Err(EvidenceError::Corrupt(_))
            ),
            "{table}"
        );
    }
}
