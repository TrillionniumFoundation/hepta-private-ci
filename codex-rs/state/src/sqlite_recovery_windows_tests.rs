use std::io::Write;
use std::path::PathBuf;

use codex_utils_absolute_path::test_support::PathExt;
use codex_utils_path::windows_private_fs::PrivateDirectory;
use codex_utils_path::windows_private_fs::snapshot_private_file;
use pretty_assertions::assert_eq;

use crate::SqliteConfig;
use crate::SqliteRecoveryError;

struct Fixture {
    _temp: tempfile::TempDir,
    home: PathBuf,
    directory: PrivateDirectory,
    config: SqliteConfig,
}

impl Fixture {
    fn new() -> anyhow::Result<Self> {
        let temp = tempfile::tempdir()?;
        let home = temp.path().join("recovery");
        let directory = PrivateDirectory::open_or_create(&home)?;
        let config = SqliteConfig::new_for_testing(home.as_path().abs());
        Ok(Self {
            _temp: temp,
            home,
            directory,
            config,
        })
    }

    fn write(&self, name: &str, bytes: &[u8]) -> anyhow::Result<()> {
        let mut file = self.directory.create_new(name)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        Ok(())
    }
}

#[tokio::test]
async fn windows_retained_file_set_never_grants_a_path_based_recovery_pool() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let names = [
        "source.sqlite3",
        "source.sqlite3-wal",
        "source.sqlite3-shm",
        "source.sqlite3-journal",
    ];
    for name in names {
        fixture.write(name, name.as_bytes())?;
    }
    fixture.directory.sync_all()?;
    let before_root = snapshot_private_file(fixture.directory.as_file())?;
    let before = names
        .iter()
        .map(|name| {
            let file = fixture.directory.open_read(name)?;
            Ok((
                snapshot_private_file(&file)?,
                std::fs::read(fixture.home.join(name))?,
            ))
        })
        .collect::<std::io::Result<Vec<_>>>()?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.home.join(names[0]))?;
    guard.verify_inspection_unchanged()?;
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
    assert!(matches!(
        fixture.config.open_cold_image_read_only_pool(&guard).await,
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert_eq!(
        snapshot_private_file(fixture.directory.as_file())?,
        before_root
    );
    for (name, expected) in names.iter().zip(before) {
        let file = fixture.directory.open_read(name)?;
        assert_eq!(
            (
                snapshot_private_file(&file)?,
                std::fs::read(fixture.home.join(name))?
            ),
            expected
        );
    }
    Ok(())
}

#[test]
fn windows_recovery_rejects_replaced_files_and_hard_links_for_every_role() -> anyhow::Result<()> {
    for selected in [
        "source.sqlite3",
        "source.sqlite3-wal",
        "source.sqlite3-shm",
        "source.sqlite3-journal",
    ] {
        let fixture = Fixture::new()?;
        for name in [
            "source.sqlite3",
            "source.sqlite3-wal",
            "source.sqlite3-shm",
            "source.sqlite3-journal",
        ] {
            fixture.write(name, b"retained")?;
        }
        let source = fixture.home.join("source.sqlite3");
        let guard = fixture.config.bind_existing_recovery_database(&source)?;
        std::fs::hard_link(fixture.home.join(selected), fixture.home.join("alias"))?;
        assert_eq!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate)
        );
        assert!(matches!(
            fixture.config.bind_existing_recovery_database(&source),
            Err(SqliteRecoveryError::Indeterminate)
        ));
        std::fs::remove_file(fixture.home.join("alias"))?;
        let guard = fixture.config.bind_existing_recovery_database(&source)?;
        std::fs::rename(fixture.home.join(selected), fixture.home.join("retained"))?;
        fixture.write(selected, b"retained")?;
        assert_eq!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate)
        );
        assert_eq!(std::fs::read(fixture.home.join("retained"))?, b"retained");
    }
    Ok(())
}

#[test]
fn windows_recovery_rejects_root_replacement_and_new_sidecars() -> anyhow::Result<()> {
    for suffix in ["-wal", "-shm", "-journal"] {
        let fixture = Fixture::new()?;
        fixture.write("source.sqlite3", b"retained")?;
        let guard = fixture
            .config
            .bind_existing_recovery_database(&fixture.home.join("source.sqlite3"))?;
        fixture.write(&format!("source.sqlite3{suffix}"), b"new")?;
        assert_eq!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate)
        );
    }
    let fixture = Fixture::new()?;
    fixture.write("source.sqlite3", b"retained")?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.home.join("source.sqlite3"))?;
    let old = fixture._temp.path().join("retained");
    std::fs::rename(&fixture.home, &old)?;
    let replacement = PrivateDirectory::open_or_create(&fixture.home)?;
    replacement.create_new("source.sqlite3")?.sync_all()?;
    assert_eq!(
        guard.verify_inspection_unchanged(),
        Err(SqliteRecoveryError::Indeterminate)
    );
    assert_eq!(std::fs::read(old.join("source.sqlite3"))?, b"retained");
    Ok(())
}

#[test]
fn windows_materialization_is_bounded_and_cleans_only_its_own_new_files() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.write("source.sqlite3", b"database")?;
    fixture.write("source.sqlite3-wal", b"wal")?;
    fixture.write("candidate.sqlite3-wal", b"pre-existing")?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.home.join("source.sqlite3"))?;
    assert!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(
                &guard,
                &fixture.home.join("candidate.sqlite3")
            )
            .is_err()
    );
    assert!(!fixture.home.join("candidate.sqlite3").exists());
    assert_eq!(
        std::fs::read(fixture.home.join("candidate.sqlite3-wal"))?,
        b"pre-existing"
    );
    assert_eq!(
        std::fs::read(fixture.home.join("source.sqlite3"))?,
        b"database"
    );

    let large = Fixture::new()?;
    for name in ["source.sqlite3", "source.sqlite3-wal"] {
        let file = large.directory.create_new(name)?;
        file.set_len(128 * 1024 * 1024)?;
        file.sync_all()?;
    }
    large.write("source.sqlite3-journal", b"one byte exceeds the aggregate")?;
    let guard = large
        .config
        .bind_existing_recovery_database(&large.home.join("source.sqlite3"))?;
    assert_eq!(
        large.config.materialize_identity_bound_recovery_copy(
            &guard,
            &large.home.join("candidate.sqlite3")
        ),
        Err(SqliteRecoveryError::Unavailable)
    );
    assert!(!large.home.join("candidate.sqlite3").exists());
    Ok(())
}

#[test]
fn windows_materialization_rejects_all_preexisting_candidate_sidecars() -> anyhow::Result<()> {
    for suffix in ["-wal", "-shm", "-journal"] {
        let fixture = Fixture::new()?;
        fixture.write("source.sqlite3", b"retained source")?;
        let name = format!("candidate.sqlite3{suffix}");
        fixture.write(&name, b"pre-existing sidecar")?;
        let before = snapshot_private_file(fixture.directory.as_file())?;
        let guard = fixture
            .config
            .bind_existing_recovery_database(&fixture.home.join("source.sqlite3"))?;
        assert_eq!(
            fixture.config.materialize_identity_bound_recovery_copy(
                &guard,
                &fixture.home.join("candidate.sqlite3")
            ),
            Err(SqliteRecoveryError::Indeterminate),
        );
        assert!(!fixture.home.join("candidate.sqlite3").exists());
        assert_eq!(
            std::fs::read(fixture.home.join(&name))?,
            b"pre-existing sidecar"
        );
        assert_eq!(snapshot_private_file(fixture.directory.as_file())?, before);
    }
    Ok(())
}

#[tokio::test]
async fn windows_cold_image_is_immutable_across_real_connection_replacement() -> anyhow::Result<()>
{
    let fixture = Fixture::new()?;
    let path = fixture.home.join("source.sqlite3");
    let source = fixture.config.open_durable_evidence_pool(&path).await?;
    sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('original')")
        .execute(&source)
        .await?;
    source.close().await;
    let original = std::fs::read(&path)?;
    let guard = fixture.config.bind_existing_recovery_database(&path)?;
    let pool = fixture
        .config
        .open_cold_image_read_only_pool(&guard)
        .await?;
    sqlx::query("PRAGMA query_only = OFF")
        .execute(&pool)
        .await?;
    assert!(
        sqlx::query("UPDATE fact SET value = 'mutated'")
            .execute(&pool)
            .await
            .is_err()
    );
    assert_eq!(std::fs::read(&path)?, original);
    std::fs::write(&path, b"changed original source")?;
    pool.acquire().await?.close().await?;
    let actual: String = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&pool)
        .await?;
    assert_eq!(actual, "original");
    pool.close().await;
    Ok(())
}

#[tokio::test]
async fn windows_materialized_database_replays_only_its_copied_wal() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let source_path = fixture.home.join("source.sqlite3");
    let source = fixture
        .config
        .open_durable_evidence_pool(&source_path)
        .await?;
    sqlx::query("PRAGMA wal_autocheckpoint = 0")
        .execute(&source)
        .await?;
    sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('retained')")
        .execute(&source)
        .await?;
    let original_database = std::fs::read(&source_path)?;
    let original_wal = std::fs::read(fixture.home.join("source.sqlite3-wal"))?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&source_path)?;
    let candidate = fixture.home.join("candidate.sqlite3");
    fixture
        .config
        .materialize_identity_bound_recovery_copy(&guard, &candidate)?;
    assert!(!fixture.home.join("candidate.sqlite3-shm").exists());
    let copy = fixture
        .config
        .open_durable_evidence_pool(&candidate)
        .await?;
    let actual: String = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&copy)
        .await?;
    assert_eq!(actual, "retained");
    assert_eq!(std::fs::read(&source_path)?, original_database);
    assert_eq!(
        std::fs::read(fixture.home.join("source.sqlite3-wal"))?,
        original_wal
    );
    copy.close().await;
    source.close().await;
    Ok(())
}
