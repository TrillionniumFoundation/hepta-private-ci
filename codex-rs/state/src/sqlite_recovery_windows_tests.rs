//! Exercise the public recovery boundary on actual Windows files and SQLite.

use super::super::SqliteConfig;
use super::super::SqliteRecoveryError;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use codex_utils_path::PrivateFileAccess;
use codex_utils_path::open_private_state_child;
use codex_utils_path::open_private_state_directory;
use pretty_assertions::assert_eq;
use std::fs;
use std::io;
use std::io::Write;
use std::path::Path;

fn write_private(root: &Path, name: &str, bytes: &[u8]) -> io::Result<()> {
    let directory = open_private_state_directory(root)?;
    let mut file = open_private_state_child(&directory, name, PrivateFileAccess::Create)?;
    file.write_all(bytes)?;
    file.sync_all()
}

#[tokio::test]
async fn materialization_copies_retained_inputs_without_shm_or_writer_admission()
-> anyhow::Result<()> {
    let home = unique_temp_dir();
    let _cleanup = scopeguard::guard(home.clone(), |path| {
        let _ = fs::remove_dir_all(path);
    });
    write_private(&home, "source.sqlite3", b"retained database bytes")?;
    write_private(&home, "source.sqlite3-wal", b"retained WAL bytes")?;
    write_private(&home, "source.sqlite3-shm", b"SHM must never be copied")?;
    write_private(&home, "source.sqlite3-journal", b"retained journal bytes")?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let source = home.join("source.sqlite3");
    let original = ["", "-wal", "-shm", "-journal"]
        .map(|suffix| fs::read(home.join(format!("source.sqlite3{suffix}"))));
    let guard = config.bind_existing_recovery_database(&source)?;
    guard.verify_inspection_unchanged()?;
    assert!(matches!(
        config.open_immutable_recovery_pool(&guard).await,
        Err(SqliteRecoveryError::Unavailable)
    ));
    assert!(matches!(
        config
            .open_identity_bound_durable_evidence_pool(guard.clone())
            .await,
        Err(SqliteRecoveryError::Unavailable)
    ));

    let target = home.join("candidate.sqlite3");
    config.materialize_identity_bound_recovery_copy(&guard, &target)?;
    assert_eq!(fs::read(&target)?, b"retained database bytes");
    assert_eq!(
        fs::read(home.join("candidate.sqlite3-wal"))?,
        b"retained WAL bytes"
    );
    assert_eq!(
        fs::read(home.join("candidate.sqlite3-journal"))?,
        b"retained journal bytes"
    );
    assert!(!home.join("candidate.sqlite3-shm").try_exists()?);
    for (suffix, before) in ["", "-wal", "-shm", "-journal"].into_iter().zip(original) {
        assert_eq!(
            fs::read(home.join(format!("source.sqlite3{suffix}")))?,
            before?
        );
    }
    // Acquiring the result exercises its real owner/DACL and single-link check.
    config.bind_existing_recovery_database(&target)?;
    Ok(())
}

#[test]
fn missing_inputs_and_new_sidecars_fail_without_creating_source_state() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    let _cleanup = scopeguard::guard(home.clone(), |path| {
        let _ = fs::remove_dir_all(path);
    });
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let source = home.join("source.sqlite3");
    assert!(matches!(
        config.bind_existing_recovery_database(&source),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert!(!home.try_exists()?);
    drop(open_private_state_directory(&home)?);
    assert!(config.bind_existing_recovery_database(&source).is_err());
    assert!(!source.try_exists()?);
    write_private(&home, "source.sqlite3", b"original")?;
    let guard = config.bind_existing_recovery_database(&source)?;
    write_private(&home, "source.sqlite3-wal", b"new sidecar")?;
    assert!(matches!(
        guard.verify_inspection_unchanged(),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    let target = home.join("candidate.sqlite3");
    assert!(
        config
            .materialize_identity_bound_recovery_copy(&guard, &target)
            .is_err()
    );
    assert!(!target.try_exists()?);
    assert_eq!(fs::read(&source)?, b"original");
    assert_eq!(fs::read(home.join("source.sqlite3-wal"))?, b"new sidecar");
    Ok(())
}

#[test]
fn candidate_collisions_and_wrong_homes_are_rejected_without_overwrite() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    let _cleanup = scopeguard::guard(home.clone(), |path| {
        let _ = fs::remove_dir_all(path);
    });
    write_private(&home, "source.sqlite3", b"source")?;
    write_private(&home, "candidate.sqlite3", b"existing candidate")?;
    write_private(&home, "other.sqlite3-shm", b"existing sidecar")?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let source = home.join("source.sqlite3");
    let guard = config.bind_existing_recovery_database(&source)?;
    for target in [
        &source,
        &home.join("candidate.sqlite3"),
        &home.join("other.sqlite3"),
        &home.join("elsewhere").join("candidate.sqlite3"),
    ] {
        assert!(
            config
                .materialize_identity_bound_recovery_copy(&guard, target)
                .is_err()
        );
    }
    guard.verify_inspection_unchanged()?;
    assert_eq!(fs::read(&source)?, b"source");
    assert_eq!(
        fs::read(home.join("candidate.sqlite3"))?,
        b"existing candidate"
    );
    assert_eq!(
        fs::read(home.join("other.sqlite3-shm"))?,
        b"existing sidecar"
    );
    assert!(!home.join("other.sqlite3").try_exists()?);
    assert!(!home.join("elsewhere").try_exists()?);
    Ok(())
}

#[tokio::test]
async fn cold_image_remains_read_only_and_reconnects_after_source_replacement() -> anyhow::Result<()>
{
    let home = unique_temp_dir();
    let _cleanup = scopeguard::guard(home.clone(), |path| {
        let _ = fs::remove_dir_all(path);
    });
    write_private(&home, "source.sqlite3", b"")?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("source.sqlite3");
    let source = config.open_durable_evidence_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('original')")
        .execute(&source)
        .await?;
    source.close().await;
    let before = fs::read(&path)?;
    let guard = config.bind_existing_recovery_database(&path)?;
    let wrong = SqliteConfig::new_for_testing(home.join("other").as_path().abs());
    assert!(matches!(
        wrong.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    let image = config.open_cold_image_read_only_pool(&guard).await?;
    guard.verify_inspection_unchanged()?;
    assert_eq!(fs::read(&path)?, before);
    sqlx::query("PRAGMA query_only = OFF")
        .execute(&image)
        .await?;
    assert!(
        sqlx::query("UPDATE fact SET value = 'mutated'")
            .execute(&image)
            .await
            .is_err()
    );
    drop(guard);
    // Windows retention prevents replacement until guard release. The in-memory
    // connection must still reconnect to its immutable copy after that release.
    fs::write(&path, b"replaced source bytes")?;
    image.acquire().await?.close().await?;
    let fact: String = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&image)
        .await?;
    assert_eq!(fact, "original");
    image.close().await;
    Ok(())
}

#[tokio::test]
async fn cold_image_rejects_sidecars_and_oversized_retained_database() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    let _cleanup = scopeguard::guard(home.clone(), |path| {
        let _ = fs::remove_dir_all(path);
    });
    write_private(&home, "source.sqlite3", &[0; 100])?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("source.sqlite3");
    for suffix in ["-wal", "-shm", "-journal"] {
        let name = format!("source.sqlite3{suffix}");
        write_private(&home, &name, b"")?;
        let guard = config.bind_existing_recovery_database(&path)?;
        assert!(matches!(
            config.open_cold_image_read_only_pool(&guard).await,
            Err(SqliteRecoveryError::Indeterminate)
        ));
        drop(guard);
        fs::remove_file(home.join(name))?;
    }
    fs::OpenOptions::new()
        .write(true)
        .open(&path)?
        .set_len(128 * 1024 * 1024 + 1)?;
    let guard = config.bind_existing_recovery_database(&path)?;
    assert!(matches!(
        config.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert!(matches!(
        config.materialize_identity_bound_recovery_copy(&guard, &home.join("candidate.sqlite3")),
        Err(SqliteRecoveryError::Unavailable)
    ));
    assert!(!home.join("candidate.sqlite3").try_exists()?);
    Ok(())
}
