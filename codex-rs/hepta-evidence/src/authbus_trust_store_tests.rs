use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::ReplayCheckpoint;
use codex_hepta_authbus::TrustedTime;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

use crate::*;

fn config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(temp.path().to_path_buf()).unwrap())
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn time(now_ms: u64) -> TrustedTime {
    TrustedTime {
        source_id: id("clock:trust"),
        generation: 1,
        now_ms,
        uncertainty_ms: 0,
    }
}

fn issuer(revoked: bool) -> IssuerRegistration {
    let key = SigningKey::from_bytes(&[73; 32]);
    IssuerRegistration {
        issuer_id: id("issuer:managed"),
        key_epoch: Generation::new(7).unwrap(),
        verifying_key: key.verifying_key(),
        revoked,
    }
}

#[tokio::test]
async fn trust_revisions_are_append_only_and_revocation_is_monotone() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let active = issuer(false);
    store
        .publish_authbus_trust(&active, 1, &time(1_000))
        .await
        .unwrap();
    let (resolved, revision) = store
        .resolve_authbus_trust(&active.issuer_id, active.key_epoch)
        .await
        .unwrap();
    assert!(!resolved.revoked);
    assert_eq!(resolved.verifying_key.to_bytes(), active.verifying_key.to_bytes());
    assert_eq!(revision.revision, 1);

    let revoked = issuer(true);
    store
        .publish_authbus_trust(&revoked, 2, &time(2_000))
        .await
        .unwrap();
    let (resolved, revision) = store
        .resolve_authbus_trust(&active.issuer_id, active.key_epoch)
        .await
        .unwrap();
    assert!(resolved.revoked);
    assert_eq!(revision.revision, 2);

    assert!(matches!(
        store
            .publish_authbus_trust(&active, 3, &time(3_000))
            .await,
        Err(AuthBusAuthorityError::StaleRevision)
    ));
}

#[tokio::test]
async fn independent_checkpoint_detects_restored_replay_frontier() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    sqlx::query(
        "INSERT INTO authbus_replay_sequences
         (issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest)
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind("issuer:checkpoint")
    .bind(1_u64.to_be_bytes().as_slice())
    .bind("subject:checkpoint")
    .bind(Digest32::of_bytes(b"scope").as_array().as_slice())
    .bind(10_u64.to_be_bytes().as_slice())
    .bind(Digest32::of_bytes(b"message-10").as_array().as_slice())
    .execute(&store.pool)
    .await
    .unwrap();

    let checkpoint = ReplayCheckpoint {
        checkpoint_id: id("checkpoint:10"),
        generation: 1,
        replay_root: store.authbus_replay_root().await.unwrap(),
        observed_at_ms: 1_000,
    };
    store
        .record_authbus_replay_checkpoint(&checkpoint)
        .await
        .unwrap();

    sqlx::query(
        "UPDATE authbus_replay_sequences SET sequence = ?, envelope_digest = ?
         WHERE issuer_id = 'issuer:checkpoint'",
    )
    .bind(9_u64.to_be_bytes().as_slice())
    .bind(Digest32::of_bytes(b"message-9").as_array().as_slice())
    .execute(&store.pool)
    .await
    .unwrap();

    assert!(matches!(
        store.verify_authbus_replay_checkpoint(&checkpoint).await,
        Err(AuthBusAuthorityError::Conflict)
    ));
}

#[tokio::test]
async fn replay_retirement_requires_revoked_epoch_and_exact_checkpoint() {
    let temp = TempDir::new().unwrap();
    let store = HeptaEvidenceStore::open(&config(&temp)).await.unwrap();
    let scope = Digest32::of_bytes(b"retire-scope");
    let subject = id("subject:retire");
    let revoked = issuer(true);
    sqlx::query(
        "INSERT INTO authbus_replay_sequences
         (issuer_id, key_epoch, subject_id, scope_digest, sequence, envelope_digest)
         VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(revoked.issuer_id.as_str())
    .bind(revoked.key_epoch.get().to_be_bytes().as_slice())
    .bind(subject.as_str())
    .bind(scope.as_array().as_slice())
    .bind(5_u64.to_be_bytes().as_slice())
    .bind(Digest32::of_bytes(b"retire-envelope").as_array().as_slice())
    .execute(&store.pool)
    .await
    .unwrap();
    let root = store.authbus_replay_root().await.unwrap();
    let checkpoint = ReplayCheckpoint {
        checkpoint_id: id("checkpoint:retire"),
        generation: 1,
        replay_root: root,
        observed_at_ms: 1_000,
    };
    let next_root = store
        .retire_authbus_replay_key(&revoked, &subject, scope, &checkpoint)
        .await
        .unwrap();
    assert_ne!(next_root, root);
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM authbus_replay_sequences")
        .fetch_one(&store.pool)
        .await
        .unwrap();
    assert_eq!(count, 0);
}
