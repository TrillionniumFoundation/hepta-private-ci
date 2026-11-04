use super::*;
use crate::runtime::test_support::unique_temp_dir;
use anyhow::Context;
use codex_utils_absolute_path::test_support::PathExt;
use codex_utils_path::create_new_private_state_child;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_private_state_directory;
use pretty_assertions::assert_eq;
use std::io::Write;

struct Fixture {
    home: PathBuf,
    database: PathBuf,
    config: SqliteConfig,
}

impl Fixture {
    fn new() -> anyhow::Result<Self> {
        let home = unique_temp_dir();
        let directory = open_private_state_directory(&home)?;
        drop(create_new_private_state_child(&directory, "cold.sqlite3")?);
        let database = home.join("cold.sqlite3");
        let config = SqliteConfig::new_for_testing(home.as_path().abs());
        Ok(Self {
            home,
            database,
            config,
        })
    }

    fn write_sidecar(&self, suffix: &str) -> anyhow::Result<()> {
        let directory = open_existing_private_state_directory(&self.home)?;
        let mut file =
            create_new_private_state_child(&directory, &format!("cold.sqlite3{suffix}"))?;
        file.write_all(b"retained sidecar")?;
        file.sync_all()?;
        Ok(())
    }

    async fn initialize(&self) -> anyhow::Result<()> {
        let pool = self
            .config
            .open_durable_evidence_pool(&self.database)
            .await?;
        sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('original')")
            .execute(&pool)
            .await?;
        pool.close().await;
        Ok(())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.home);
    }
}

#[test]
fn windows_guard_never_creates_missing_sources_and_rejects_live_writers() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    assert!(matches!(
        fixture
            .config
            .bind_existing_recovery_database(&fixture.home.join("missing.sqlite3")),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert!(!fixture.home.join("missing.sqlite3").exists());
    let live = std::fs::OpenOptions::new()
        .write(true)
        .open(&fixture.database)?;
    assert!(matches!(
        fixture
            .config
            .bind_existing_recovery_database(&fixture.database),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    drop(live);
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    guard.verify_inspection_unchanged()?;
    assert!(
        std::fs::OpenOptions::new()
            .write(true)
            .open(&fixture.database)
            .is_err()
    );
    assert!(std::fs::rename(&fixture.database, fixture.home.join("replacement")).is_err());
    assert!(std::fs::remove_file(&fixture.database).is_err());
    guard.verify_inspection_unchanged()?;
    Ok(())
}

#[test]
fn windows_sidecar_appearance_refuses_before_any_candidate_is_created() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    fixture.write_sidecar("-wal")?;
    assert_eq!(
        guard.verify_inspection_unchanged(),
        Err(SqliteRecoveryError::Indeterminate)
    );
    let target = fixture.home.join("candidate.sqlite3");
    assert_eq!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&guard, &target),
        Err(SqliteRecoveryError::Indeterminate)
    );
    assert!(!target.exists());
    Ok(())
}

#[test]
fn windows_retains_each_sidecar_and_rejects_hard_links_for_every_role() -> anyhow::Result<()> {
    for suffix in ["", "-wal", "-shm", "-journal"] {
        let fixture = Fixture::new()?;
        for sidecar in ["-wal", "-shm", "-journal"] {
            fixture.write_sidecar(sidecar)?;
        }
        let path = sqlite_sidecar_path(&fixture.database, suffix);
        let guard = fixture
            .config
            .bind_existing_recovery_database(&fixture.database)?;
        assert!(std::fs::OpenOptions::new().write(true).open(&path).is_err());
        assert!(std::fs::remove_file(&path).is_err());
        guard.verify_inspection_unchanged()?;
        drop(guard);
        std::fs::hard_link(&path, fixture.home.join("alias"))?;
        assert!(matches!(
            fixture
                .config
                .bind_existing_recovery_database(&fixture.database),
            Err(SqliteRecoveryError::Indeterminate)
        ));
    }
    Ok(())
}

#[tokio::test]
async fn windows_cold_image_is_read_only_and_reconnects_from_the_retained_copy()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.initialize().await?;
    let before = std::fs::read(&fixture.database)?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let image = fixture
        .config
        .open_cold_image_read_only_pool(&guard)
        .await?;
    guard.verify_inspection_unchanged()?;
    assert_eq!(std::fs::read(&fixture.database)?, before);
    sqlx::query("PRAGMA query_only = OFF")
        .execute(&image)
        .await?;
    assert!(
        sqlx::query("UPDATE fact SET value = 'mutated'")
            .execute(&image)
            .await
            .is_err()
    );
    assert!(matches!(
        fixture.config.open_immutable_recovery_pool(&guard).await,
        Err(SqliteRecoveryError::Unavailable)
    ));
    assert!(matches!(
        fixture
            .config
            .open_identity_bound_durable_evidence_pool(guard.clone())
            .await,
        Err(SqliteRecoveryError::Unavailable)
    ));
    // The image owns bytes, not a reconnectable path. Release the source guard,
    // replace its bytes and force the pool to establish a new real connection.
    drop(guard);
    std::fs::write(&fixture.database, b"replaced source")?;
    image.acquire().await?.close().await?;
    let fact: String = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&image)
        .await?;
    assert_eq!(fact, "original");
    image.close().await;
    Ok(())
}

#[tokio::test]
async fn windows_materializes_only_fresh_private_bytes_and_never_copies_shm() -> anyhow::Result<()>
{
    let fixture = Fixture::new()?;
    fixture.initialize().await?;
    for suffix in ["-wal", "-shm", "-journal"] {
        fixture.write_sidecar(suffix)?;
    }
    let original = std::fs::read(&fixture.database)?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let target = fixture.home.join("candidate.sqlite3");
    fixture
        .config
        .materialize_identity_bound_recovery_copy(&guard, &target)
        .context("copy retained bytes and perform real directory synchronization")?;
    assert_eq!(std::fs::read(&fixture.database)?, original);
    assert_eq!(std::fs::read(&target)?, original);
    assert_eq!(
        std::fs::read(sqlite_sidecar_path(&target, "-wal"))?,
        b"retained sidecar"
    );
    assert_eq!(
        std::fs::read(sqlite_sidecar_path(&target, "-journal"))?,
        b"retained sidecar"
    );
    assert!(!sqlite_sidecar_path(&target, "-shm").exists());
    drop(guard);
    let before = std::fs::read(&target)?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    assert!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&guard, &target)
            .is_err()
    );
    assert_eq!(std::fs::read(&target)?, before);
    Ok(())
}

#[tokio::test]
async fn windows_native_and_verbatim_homes_bind_without_admitting_another_directory()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.initialize().await?;
    let original = std::fs::read(&fixture.database)?;
    let native = fixture.config.home().to_path_buf();
    let verbatim = native.canonicalize()?;
    assert_ne!(native.as_os_str(), verbatim.as_os_str());
    assert!(same_recovery_home(&native, &verbatim));
    assert!(same_recovery_home(&verbatim, &native));

    for home in [&native, &verbatim] {
        let database = home.join("cold.sqlite3");
        let guard = fixture.config.bind_existing_recovery_database(&database)?;
        guard.verify_inspection_unchanged()?;
        let image = fixture
            .config
            .open_cold_image_read_only_pool(&guard)
            .await?;
        let fact: String = sqlx::query_scalar("SELECT value FROM fact")
            .fetch_one(&image)
            .await?;
        assert_eq!(fact, "original");
        image.close().await;
        guard.verify_inspection_unchanged()?;
    }

    let other = Fixture::new()?;
    assert!(!same_recovery_home(&other.home, &native));
    assert!(matches!(
        fixture
            .config
            .bind_existing_recovery_database(&other.database),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let outside = other.home.join("outside.sqlite3");
    assert!(matches!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&guard, &outside),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert!(!outside.exists());
    let target = verbatim.join("candidate.sqlite3");
    fixture
        .config
        .materialize_identity_bound_recovery_copy(&guard, &target)?;
    assert_eq!(std::fs::read(&target)?, original);
    assert_eq!(std::fs::read(&fixture.database)?, original);
    guard.verify_inspection_unchanged()?;
    Ok(())
}

#[test]
fn windows_home_spelling_reconciliation_rejects_other_roots_and_namespaces() {
    assert!(same_recovery_home(
        Path::new(r"C:\private\owner"),
        Path::new(r"\\?\C:\private\owner")
    ));
    for other in [
        r"D:\private\owner",
        r"\\?\D:\private\owner",
        r"C:\private\another",
        r"C:\Private\owner",
        r"\\server\share\private\owner",
        r"\\?\UNC\server\share\private\owner",
        r"\\.\C:\private\owner",
        r"private\owner",
    ] {
        assert!(!same_recovery_home(
            Path::new(other),
            Path::new(r"C:\private\owner")
        ));
    }
}
