use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

fn prepare_home(path: &std::path::Path) -> anyhow::Result<()> {
    #[cfg(unix)]
    {
        std::fs::create_dir(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    #[cfg(windows)]
    codex_utils_path::windows_private::PrivateSqliteDirectory::prepare(path)?;
    Ok(())
}

fn verify_private_file(path: &std::path::Path) -> anyhow::Result<()> {
    #[cfg(unix)]
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    #[cfg(windows)]
    {
        use codex_utils_path::windows_private::Access;
        use codex_utils_path::windows_private::PrivateSqliteDirectory;
        PrivateSqliteDirectory::inspect(path.parent().expect("parent"))?.open(
            path.file_name()
                .and_then(|name| name.to_str())
                .expect("leaf"),
            Access::Read,
        )?;
    }
    Ok(())
}

fn write_private_new(path: &std::path::Path, bytes: &[u8]) -> anyhow::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        file.write_all(bytes)?;
        file.sync_all()?;
    }
    #[cfg(windows)]
    {
        use anyhow::Context;
        use codex_utils_path::windows_private::Access;
        use codex_utils_path::windows_private::PrivateSqliteDirectory;
        // An inherited owner-only DACL does not determine the new file's owner.
        // Keep each synthetic replacement valid before testing its identity.
        let parent = path.parent().context("synthetic database parent")?;
        let name = path
            .file_name()
            .and_then(|name| name.to_str())
            .context("synthetic database leaf")?;
        let directory = PrivateSqliteDirectory::open_writable(parent)?;
        let mut file = directory.open(name, Access::CreateNew)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        directory.sync_all()?;
    }
    verify_private_file(path)
}

#[tokio::test]
async fn cold_image_is_immutable_and_reconnects_to_same_copy() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    prepare_home(&home)?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("cold.sqlite3");
    let source = config.open_durable_evidence_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('original')")
        .execute(&source)
        .await?;
    source.close().await;
    verify_private_file(&path)?;
    let guard = config.bind_existing_recovery_database(&path)?;
    let original = std::fs::read(&path)?;
    let pool = config.open_cold_image_read_only_pool(&guard).await?;
    assert_eq!(std::fs::read(&path)?, original);
    sqlx::query("PRAGMA query_only = OFF")
        .execute(&pool)
        .await?;
    assert!(
        sqlx::query("UPDATE fact SET value = 'mutated'")
            .execute(&pool)
            .await
            .is_err()
    );
    // Destroy the original source after capture and force a real connection
    // replacement: neither a stale filename reopen nor mutable source is used.
    std::fs::write(&path, b"replaced source bytes")?;
    pool.acquire().await?.close().await?;
    let fact: String = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&pool)
        .await?;
    assert_eq!(fact, "original");
    pool.close().await;
    drop(guard);
    std::fs::remove_dir_all(home)?;
    Ok(())
}

#[tokio::test]
async fn cold_image_rejects_wrong_guard_replacement_sidecars_and_size() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    prepare_home(&home)?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("cold.sqlite3");
    let source = config.open_durable_evidence_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value TEXT)")
        .execute(&source)
        .await?;
    source.close().await;
    verify_private_file(&path)?;
    let guard = config.bind_existing_recovery_database(&path)?;
    let wrong = SqliteConfig::new_for_testing(home.join("other").as_path().abs());
    assert!(matches!(
        wrong.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    let original = std::fs::read(&path)?;
    std::fs::rename(&path, home.join("retained.sqlite3"))?;
    write_private_new(&path, &original)?;
    assert!(matches!(
        config.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    drop(guard);
    for suffix in ["-wal", "-shm", "-journal"] {
        let sidecar = super::super::sqlite_sidecar_path(&path, suffix);
        write_private_new(&sidecar, b"")?;
        let guard = config.bind_existing_recovery_database(&path)?;
        assert!(matches!(
            config.open_cold_image_read_only_pool(&guard).await,
            Err(SqliteRecoveryError::Indeterminate)
        ));
        std::fs::remove_file(sidecar)?;
    }
    std::fs::OpenOptions::new()
        .write(true)
        .open(&path)?
        .set_len(128 * 1024 * 1024 + 1)?;
    let guard = config.bind_existing_recovery_database(&path)?;
    assert!(matches!(
        config.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    drop(guard);
    std::fs::remove_dir_all(home)?;
    Ok(())
}
