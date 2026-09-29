#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_types::Digest32;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use sqlx::sqlite::SqliteSynchronous;

struct Paths {
    _root: tempfile::TempDir,
    database: PathBuf,
    checkpoint: PathBuf,
}

fn private_paths() -> Paths {
    let root = tempfile::tempdir().expect("temporary root");
    let database_root = root.path().join("database");
    let checkpoint_root = root.path().join("checkpoint");
    std::fs::create_dir_all(&database_root).expect("database root");
    std::fs::create_dir_all(&checkpoint_root).expect("checkpoint root");
    std::fs::set_permissions(&database_root, std::fs::Permissions::from_mode(0o700))
        .expect("database permissions");
    std::fs::set_permissions(&checkpoint_root, std::fs::Permissions::from_mode(0o700))
        .expect("checkpoint permissions");
    Paths {
        database: database_root.join("authority.sqlite"),
        checkpoint: checkpoint_root.join("authority-checkpoint.json"),
        _root: root,
    }
}

#[tokio::test]
async fn clean_accumulator_and_dirty_clear_are_guarded_by_sqlite() {
    let paths = private_paths();
    let owner_id = "frontier-integrity-owner";
    let host = AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), owner_id)
        .await
        .expect("bootstrap authority owner");
    drop(host);

    let options = SqliteConnectOptions::new()
        .filename(&paths.database)
        .create_if_missing(false)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5));
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await
        .expect("open authority database");

    let original_root: Vec<u8> = sqlx::query_scalar(
        "SELECT root_digest FROM authbus_frontier_accumulator WHERE singleton = 1",
    )
    .fetch_one(&pool)
    .await
    .expect("load accumulator root");
    let forged = Digest32::of_bytes(b"forged-clean-frontier-root");
    assert_ne!(original_root.as_slice(), forged.as_array().as_slice());

    let clean_update =
        sqlx::query("UPDATE authbus_frontier_accumulator SET root_digest = ? WHERE singleton = 1")
            .bind(forged.as_array().as_slice())
            .execute(&pool)
            .await;
    assert!(
        clean_update.is_err(),
        "clean accumulator drift was accepted"
    );

    sqlx::query("UPDATE authbus_authority_checkpoint_dirty SET dirty = 1 WHERE singleton = 1")
        .execute(&pool)
        .await
        .expect("simulate a dirty frontier");
    sqlx::query("UPDATE authbus_frontier_accumulator SET root_digest = ? WHERE singleton = 1")
        .bind(forged.as_array().as_slice())
        .execute(&pool)
        .await
        .expect("dirty accumulator may advance before external publication");

    let premature_clear =
        sqlx::query("UPDATE authbus_authority_checkpoint_dirty SET dirty = 0 WHERE singleton = 1")
            .execute(&pool)
            .await;
    assert!(
        premature_clear.is_err(),
        "dirty frontier cleared without exact checkpoint promotion"
    );

    let delete = sqlx::query("DELETE FROM authbus_frontier_accumulator WHERE singleton = 1")
        .execute(&pool)
        .await;
    assert!(
        delete.is_err(),
        "frontier accumulator deletion was accepted"
    );
    pool.close().await;
}
