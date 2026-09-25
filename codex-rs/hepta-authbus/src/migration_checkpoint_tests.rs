use super::*;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;
use crate::AuthorityCheckpoint;
use crate::IssuerPurpose;
use crate::IssuerSpec;
use crate::authority_store::begin;
use crate::host_checkpoint::AuthorityCheckpointFile;
use crate::recovery::FrontierVersion;
use crate::recovery::authority_frontier_digest_for_version;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

const OWNER: &str = "authbus-owner:migration";

async fn legacy_owner(
    external_generation: u64,
) -> (tempfile::TempDir, PathBuf, PathBuf, AuthorityCheckpoint) {
    let root = tempfile::tempdir().unwrap();
    let database_root = root.path().join("database");
    let witness_root = root.path().join("witness");
    for path in [&database_root, &witness_root] {
        std::fs::create_dir(path).unwrap();
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    let database = database_root.join("authority.sqlite");
    let witness = witness_root.join("authority.json");
    let pool = codex_state::open_durable_sqlite_pool(&database, 1)
        .await
        .unwrap();
    TEST_MIGRATOR.run_to(4, &pool).await.unwrap();
    let mut tx = begin(&pool).await.unwrap();
    let initial = AuthorityCheckpoint {
        generation: 1,
        digest: authority_frontier_digest_for_version(&mut tx, FrontierVersion::LegacyV4)
            .await
            .unwrap(),
    };
    tx.commit().await.unwrap();
    sqlx::query("INSERT INTO authbus_authority_checkpoint (singleton, generation, checkpoint_digest) VALUES (1, ?, ?)")
        .bind(u64_blob(1)).bind(initial.digest.as_array().as_slice()).execute(&pool).await.unwrap();
    sqlx::query("INSERT INTO authbus_issuer_registry (issuer_id, purpose, key_epoch, public_key, state, revision) VALUES (?, 'message', ?, ?, 'active', ?)")
        .bind("issuer:migration").bind(u64_blob(1))
        .bind(SigningKey::from_bytes(&[77; 32]).verifying_key().to_bytes().as_slice())
        .bind(u64_blob(1)).execute(&pool).await.unwrap();
    let mut tx = begin(&pool).await.unwrap();
    let published = AuthorityCheckpoint {
        generation: 2,
        digest: authority_frontier_digest_for_version(&mut tx, FrontierVersion::LegacyV4)
            .await
            .unwrap(),
    };
    tx.commit().await.unwrap();
    let external = match external_generation {
        1 => initial,
        2 => published,
        _ => panic!("invalid fixture generation"),
    };
    AuthorityCheckpointFile::create(witness.clone(), &database, OWNER, external).unwrap();
    pool.close().await;
    (root, database, witness, external)
}

#[tokio::test]
async fn upgrade_recovers_both_sides_of_legacy_external_publication() {
    for generation in [1, 2] {
        let (_root, database, witness, external) = legacy_owner(generation).await;
        let host = AuthBusAuthorityHost::open(&database, witness.clone(), OWNER)
            .await
            .unwrap();
        let (_, current) = AuthorityCheckpointFile::open(witness, &database, OWNER).unwrap();
        assert_eq!(current.generation, external.generation + 1);
        assert_ne!(current.digest, external.digest);
        assert_eq!(
            host.message_issuer(&id("issuer:migration"), Generation::new(1).unwrap())
                .await
                .unwrap()
                .verifying_key,
            SigningKey::from_bytes(&[77; 32]).verifying_key()
        );
        host.sync_checkpoint().await.unwrap();
    }
}

#[tokio::test]
async fn upgrade_reopens_after_legacy_promotion_before_new_publication() {
    let (_root, database, witness, external) = legacy_owner(2).await;
    let store = AuthBusAuthorityStore::open(&database).await.unwrap();
    let next = store
        .reconcile_authority_checkpoint(external)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(next.generation, 3);
    assert_eq!(store.authority_checkpoint().await.unwrap(), Some(external));
    store.pool.close().await;
    let host = AuthBusAuthorityHost::open(&database, witness.clone(), OWNER)
        .await
        .unwrap();
    assert_eq!(
        AuthorityCheckpointFile::open(witness, &database, OWNER)
            .unwrap()
            .1,
        next
    );
    host.sync_checkpoint().await.unwrap();
}

#[tokio::test]
async fn migrated_owner_rejects_a_legacy_digest_downgrade() {
    let (_root, database, witness, _) = legacy_owner(2).await;
    let host = AuthBusAuthorityHost::open(&database, witness, OWNER)
        .await
        .unwrap();
    let store = AuthBusAuthorityStore::open(&database).await.unwrap();
    let current = store.authority_checkpoint().await.unwrap().unwrap();
    store
        .enroll_issuer(
            IssuerPurpose::Message,
            IssuerSpec {
                issuer_id: id("issuer:after-upgrade"),
                key_epoch: Generation::new(1).unwrap(),
                verifying_key: SigningKey::from_bytes(&[78; 32]).verifying_key(),
            },
        )
        .await
        .unwrap();
    let mut tx = begin(&store.pool).await.unwrap();
    let legacy = authority_frontier_digest_for_version(&mut tx, FrontierVersion::LegacyV4)
        .await
        .unwrap();
    tx.commit().await.unwrap();
    let forged_dialect = AuthorityCheckpoint {
        generation: current.generation + 1,
        digest: legacy,
    };
    assert!(matches!(
        store.reconcile_authority_checkpoint(forged_dialect).await,
        Err(AuthBusAuthorityError::RollbackDetected)
    ));
    host.sync_checkpoint().await.unwrap();
}
