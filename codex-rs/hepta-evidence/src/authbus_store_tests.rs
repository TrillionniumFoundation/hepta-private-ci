use codex_hepta_authbus::Error;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use super::*;

fn fixture(sequence: u64) -> (IssuerRegistration, SignedMessage) {
    let key = SigningKey::from_bytes(&[19; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:durable").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new(format!("message:{sequence}")).unwrap(),
        subject_id: StableId::new("subject:durable").unwrap(),
        scope_digest: Digest32::of_bytes(b"scope"),
        payload_digest: Digest32::of_bytes(b"payload"),
        sequence,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    (issuer, SignedMessage { claims, signature })
}

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

async fn admit(
    store: &HeptaEvidenceStore,
    sequence: u64,
) -> Result<VerificationReceipt, AuthBusAdmissionError> {
    let (issuer, message) = fixture(sequence);
    store
        .admit_authbus_message(
            &issuer,
            &message,
            message.claims.scope_digest,
            message.claims.payload_digest,
        )
        .await
}

#[tokio::test]
async fn replay_fence_survives_reopen_and_preserves_full_unsigned_sequence() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let store = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    admit(&store, u64::MAX - 1).await.unwrap();
    store.pool.close().await;
    let reopened = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    assert!(matches!(
        admit(&reopened, u64::MAX - 1).await,
        Err(AuthBusAdmissionError::Authentication(Error::Replay))
    ));
    let receipt = admit(&reopened, u64::MAX).await.unwrap();
    assert_eq!(receipt.sequence, u64::MAX);
    assert!(matches!(
        admit(&reopened, 1).await,
        Err(AuthBusAdmissionError::Authentication(Error::Replay))
    ));
}

#[tokio::test]
async fn independent_database_handles_cannot_both_admit_one_sequence() {
    let temp = TempDir::new().unwrap();
    let sqlite = config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let second = HeptaEvidenceStore::open(&sqlite).await.unwrap();
    let (left, right) = tokio::join!(admit(&first, 1), admit(&second, 1));
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let rejected = left.err().or_else(|| right.err()).unwrap();
    assert!(matches!(
        rejected,
        AuthBusAdmissionError::Authentication(Error::Replay)
    ));
}

#[tokio::test]
async fn rejected_authentication_does_not_consume_sequence() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let (issuer, mut message) = fixture(1);
    message.signature[0] ^= 1;
    let result = store
        .admit_authbus_message(
            &issuer,
            &message,
            message.claims.scope_digest,
            message.claims.payload_digest,
        )
        .await;
    assert!(matches!(
        result,
        Err(AuthBusAdmissionError::Authentication(
            Error::InvalidSignature
        ))
    ));
    admit(&store, 1).await.unwrap();
}

#[tokio::test]
async fn capacity_failure_does_not_burn_a_new_replay_key() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    sqlx::query(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x < 16384)
        INSERT INTO authbus_replay_sequences SELECT 'fixture:' || x, zeroblob(8),
        'fixture', zeroblob(32), zeroblob(8), zeroblob(32) FROM n",
    )
    .execute(&store.pool)
    .await
    .unwrap();
    assert!(matches!(
        admit(&store, 1).await,
        Err(AuthBusAdmissionError::Authentication(
            Error::CapacityExceeded
        ))
    ));
    sqlx::query("DELETE FROM authbus_replay_sequences WHERE issuer_id = 'fixture:1'")
        .execute(&store.pool)
        .await
        .unwrap();
    admit(&store, 1).await.unwrap();
}
