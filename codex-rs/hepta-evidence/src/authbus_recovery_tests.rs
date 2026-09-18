use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::*;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

fn message(sequence: u64) -> (IssuerRegistration, SignedMessage) {
    let key = SigningKey::from_bytes(&[77; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:retire").unwrap(),
        key_epoch: Generation::new(7).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!("message:{sequence}")).unwrap(),
        subject_id: StableId::new("subject:retire").unwrap(),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (issuer, SignedMessage { claims, signature })
}

#[tokio::test]
async fn external_restore_checkpoint_detects_old_database_generation() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let first = Digest32::of_bytes(b"checkpoint-one");
    let second = Digest32::of_bytes(b"checkpoint-two");
    store
        .initialize_authbus_restore_checkpoint(1, first)
        .await
        .unwrap();
    store
        .advance_authbus_restore_checkpoint(1, 2, second)
        .await
        .unwrap();
    assert!(matches!(
        store.verify_authbus_restore_checkpoint(1, first).await,
        Err(AuthBusControlError::RollbackDetected)
    ));
    store
        .verify_authbus_restore_checkpoint(2, second)
        .await
        .unwrap();
}

#[tokio::test]
async fn retired_epoch_tombstone_prevents_replay_window_reopening() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let checkpoint = Digest32::of_bytes(b"checkpoint");
    store
        .initialize_authbus_restore_checkpoint(1, checkpoint)
        .await
        .unwrap();
    let (issuer, signed) = message(1);
    store
        .admit_authbus_message(
            &issuer,
            &signed,
            signed.claims.scope_digest,
            signed.claims.payload_digest,
        )
        .await
        .unwrap();
    assert_eq!(
        store
            .retire_authbus_replay_epoch(&issuer.issuer_id, issuer.key_epoch, 1, checkpoint)
            .await
            .unwrap(),
        1
    );
    let (_, replacement) = message(2);
    assert!(matches!(
        store
            .admit_authbus_message(
                &issuer,
                &replacement,
                replacement.claims.scope_digest,
                replacement.claims.payload_digest,
            )
            .await,
        Err(AuthBusAdmissionError::Authentication(
            codex_hepta_authbus::Error::Revoked
        ))
    ));
}
