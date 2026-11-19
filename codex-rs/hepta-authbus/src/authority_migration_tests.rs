use std::collections::BTreeSet;

use sqlx::SqlitePool;
use sqlx::migrate::Migrator;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;

static MIGRATOR: Migrator = sqlx::migrate!("./migrations");

type MigrationRow = (i64, String, Vec<u8>);
type IssuerRow = (String, String, Vec<u8>, Vec<u8>, String, Vec<u8>);

async fn migration_rows(pool: &SqlitePool) -> Vec<MigrationRow> {
    sqlx::query_as(
        "SELECT version, description, checksum
         FROM _sqlx_migrations ORDER BY version",
    )
    .fetch_all(pool)
    .await
    .unwrap()
}

async fn issuer_row(pool: &SqlitePool) -> IssuerRow {
    sqlx::query_as(
        "SELECT issuer_id, purpose, key_epoch, public_key, state, revision
         FROM authbus_issuer_registry WHERE issuer_id = 'issuer:legacy'",
    )
    .fetch_one(pool)
    .await
    .unwrap()
}

#[tokio::test]
async fn canonical_five_upgrade_preserves_data_checksums_and_issuer_tombstones() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("legacy.sqlite");
    let pool = crate::sqlite::open_durable_pool(&path).await.unwrap();
    // Apply the actual immutable canonical history using SQLx, not synthetic
    // migration records or a reconstructed schema.
    MIGRATOR.run_to(/*target*/ 5, &pool).await.unwrap();
    let old_rows = migration_rows(&pool).await;
    assert_eq!(
        old_rows.iter().map(|row| row.0).collect::<Vec<_>>(),
        [1, 2, 3, 4, 5]
    );
    let key = ed25519_dalek::SigningKey::from_bytes(&[91; 32]);
    let epoch = 1_u64.to_be_bytes();
    let revision = 9_u64.to_be_bytes();
    sqlx::query(
        "INSERT INTO authbus_issuer_registry
         (issuer_id, purpose, key_epoch, public_key, state, revision)
         VALUES ('issuer:legacy', 'settlement', ?, ?, 'revoked', ?)",
    )
    .bind(epoch.as_slice())
    .bind(key.verifying_key().to_bytes().as_slice())
    .bind(revision.as_slice())
    .execute(&pool)
    .await
    .unwrap();
    let wall_time = 1_000_u64.to_be_bytes();
    let source_digest = [44_u8; 32];
    sqlx::query(
        "INSERT INTO authbus_trusted_time
         (singleton, wall_time_ms, source_revision, source_digest)
         VALUES (1, ?, ?, ?)",
    )
    .bind(wall_time.as_slice())
    .bind(revision.as_slice())
    .bind(source_digest.as_slice())
    .execute(&pool)
    .await
    .unwrap();
    let old_issuer = issuer_row(&pool).await;
    pool.close().await;

    let mut upgraded_rows = None;
    for _ in 0..2 {
        let store = AuthBusAuthorityStore::open(&path).await.unwrap();
        assert_eq!(issuer_row(&store.pool).await, old_issuer);
        let algorithm: i64 = sqlx::query_scalar(
            "SELECT auth_version FROM authbus_crypto_profile WHERE singleton = 1",
        )
        .fetch_one(&store.pool)
        .await
        .unwrap();
        assert_eq!(algorithm, 1);
        let time: (Vec<u8>, Vec<u8>, Vec<u8>, Option<Vec<u8>>) = sqlx::query_as(
            "SELECT wall_time_ms, source_revision, source_digest, valid_until_ms
             FROM authbus_trusted_time WHERE singleton = 1",
        )
        .fetch_one(&store.pool)
        .await
        .unwrap();
        assert_eq!(
            time,
            (
                wall_time.to_vec(),
                revision.to_vec(),
                source_digest.to_vec(),
                None
            )
        );
        let error =
            sqlx::query("DELETE FROM authbus_issuer_registry WHERE issuer_id = 'issuer:legacy'")
                .execute(&store.pool)
                .await
                .unwrap_err();
        assert_eq!(
            error.as_database_error().unwrap().message(),
            "AuthBus issuer tombstones cannot be deleted"
        );
        assert_eq!(issuer_row(&store.pool).await, old_issuer);

        let rows = migration_rows(&store.pool).await;
        assert_eq!(
            rows.iter()
                .filter(|row| row.0 <= 5)
                .cloned()
                .collect::<Vec<_>>(),
            old_rows
        );
        let versions: Vec<_> = rows.iter().map(|row| row.0).collect();
        assert_eq!(versions, [1, 2, 3, 4, 5, 6, 7, 8]);
        assert_eq!(
            versions.iter().copied().collect::<BTreeSet<_>>().len(),
            versions.len()
        );
        if let Some(expected) = &upgraded_rows {
            assert_eq!(&rows, expected);
        } else {
            upgraded_rows = Some(rows);
        }
        store.pool.close().await;
    }
}

#[tokio::test]
async fn foreign_crypto_version_five_is_rejected_without_rewriting_its_ledger() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("foreign-history.sqlite");
    let pool = crate::sqlite::open_durable_pool(&path).await.unwrap();
    let mut foreign: Vec<_> = MIGRATOR
        .iter()
        .filter(|migration| migration.version <= 4)
        .cloned()
        .collect();
    // This is the incoming branch's original SQL/checksum at its original
    // version. SQLx performs every migration and writes its real ledger.
    let mut crypto = MIGRATOR
        .iter()
        .find(|migration| migration.description.as_ref() == "crypto profile")
        .unwrap()
        .clone();
    crypto.version = 5;
    foreign.push(crypto);
    foreign.push(
        MIGRATOR
            .iter()
            .find(|migration| migration.version == 6)
            .unwrap()
            .clone(),
    );
    Migrator::with_migrations(foreign).run(&pool).await.unwrap();
    let before = migration_rows(&pool).await;
    pool.close().await;

    match AuthBusAuthorityStore::open(&path).await {
        Err(AuthBusAuthorityError::Storage(message)) => {
            assert_eq!(
                message,
                "migration 5 was previously applied but has been modified"
            );
        }
        Err(error) => panic!("unexpected history rejection: {error}"),
        Ok(_) => panic!("a foreign version-five checksum was accepted"),
    }

    let pool = crate::sqlite::open_durable_pool(&path).await.unwrap();
    assert_eq!(migration_rows(&pool).await, before);
    pool.close().await;
}
