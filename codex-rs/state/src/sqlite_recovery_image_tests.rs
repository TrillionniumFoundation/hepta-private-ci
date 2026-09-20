use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

#[tokio::test]
async fn cold_image_is_immutable_and_reconnects_to_same_copy() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    std::fs::create_dir(&home)?;
    std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("cold.sqlite3");
    let source = config.open_durable_evidence_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('original')")
        .execute(&source)
        .await?;
    source.close().await;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
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
    std::fs::remove_dir_all(home)?;
    Ok(())
}

#[tokio::test]
async fn cold_image_rejects_wrong_guard_replacement_sidecars_and_size() -> anyhow::Result<()> {
    let home = unique_temp_dir();
    std::fs::create_dir(&home)?;
    std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    let path = home.join("cold.sqlite3");
    let source = config.open_durable_evidence_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value TEXT)")
        .execute(&source)
        .await?;
    source.close().await;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let guard = config.bind_existing_recovery_database(&path)?;
    let wrong = SqliteConfig::new_for_testing(home.join("other").as_path().abs());
    assert!(matches!(
        wrong.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    let original = std::fs::read(&path)?;
    std::fs::rename(&path, home.join("retained.sqlite3"))?;
    std::fs::write(&path, &original)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    assert!(matches!(
        config.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    for suffix in ["-wal", "-shm", "-journal"] {
        let sidecar = super::super::sqlite_sidecar_path(&path, suffix);
        std::fs::write(&sidecar, b"")?;
        std::fs::set_permissions(&sidecar, std::fs::Permissions::from_mode(0o600))?;
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
    std::fs::remove_dir_all(home)?;
    Ok(())
}
