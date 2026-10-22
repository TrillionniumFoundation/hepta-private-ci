use super::*;
use crate::runtime::test_support::unique_temp_dir;
use anyhow::Context;
use codex_utils_absolute_path::test_support::PathExt;
use codex_utils_path::create_private_recovery_copy;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_private_state_directory;
use pretty_assertions::assert_eq;
use std::fs;
use std::io::Write;

struct Fixture {
    home: PathBuf,
    database: PathBuf,
    config: SqliteConfig,
}

impl Fixture {
    fn new() -> anyhow::Result<Self> {
        let home = unique_temp_dir();
        drop(open_private_state_directory(&home).context("create private source directory")?);
        let home = home.canonicalize()?;
        let database = home.join("source.sqlite3");
        let config = SqliteConfig::new_for_testing(home.as_path().abs());
        Ok(Self {
            home,
            database,
            config,
        })
    }

    fn source(&self, bytes: &[u8]) -> anyhow::Result<()> {
        write_private(&self.database, bytes)
    }

    fn complete(&self) -> anyhow::Result<()> {
        self.source(b"database bytes")?;
        for (suffix, bytes) in [
            ("-wal", b"wal bytes".as_slice()),
            ("-shm", b"shared memory bytes".as_slice()),
            ("-journal", b"journal bytes".as_slice()),
        ] {
            write_private(&sqlite_sidecar_path(&self.database, suffix), bytes)?;
        }
        Ok(())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.home);
    }
}

fn write_private(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let parent = path.parent().context("file parent")?;
    let name = path.file_name().context("file name")?;
    let directory = open_existing_private_state_directory(parent)?;
    let mut file = create_private_recovery_copy(&directory, name)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

#[tokio::test]
async fn valid_bundle_still_refuses_path_based_sqlite_recovery() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.complete()?;
    let before = fs::read(&fixture.database)?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
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
    assert!(
        fixture
            .config
            .open_existing_durable_evidence_pool(&fixture.database)
            .await
            .is_err()
    );
    assert_eq!(fs::read(&fixture.database)?, before);
    guard.verify_inspection_unchanged()?;
    Ok(())
}

#[test]
fn retained_sources_deny_same_size_write_and_byte_identical_replacement() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.source(b"original")?;
    let replacement = fixture.home.join("replacement.sqlite3");
    write_private(&replacement, b"original")?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let clone = guard.clone();
    let write_denied = fs::write(&fixture.database, b"mutation").is_err();
    let replace_denied = fs::rename(&replacement, &fixture.database).is_err();
    eprintln!(
        "WINDOWS_RECOVERY source_pin write_denied={write_denied} replace_denied={replace_denied}"
    );
    assert_eq!((write_denied, replace_denied), (true, true));
    assert_eq!(fs::read(&fixture.database)?, b"original");
    guard.verify_inspection_unchanged()?;
    drop(guard);
    assert!(
        fs::write(&fixture.database, b"mutation").is_err(),
        "a clone retains the same protection"
    );
    drop(clone);
    fs::write(&fixture.database, b"mutation")?;
    assert_eq!(fs::read(&fixture.database)?, b"mutation");
    Ok(())
}

#[test]
fn every_present_sidecar_is_pinned_and_absent_sidecar_appearance_is_indeterminate()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.complete()?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    for suffix in ["-wal", "-shm", "-journal"] {
        let path = sqlite_sidecar_path(&fixture.database, suffix);
        let before = fs::read(&path)?;
        assert!(fs::write(&path, b"changed").is_err());
        assert!(fs::remove_file(&path).is_err());
        assert_eq!(fs::read(&path)?, before);
    }
    guard.verify_inspection_unchanged()?;
    drop(guard);
    for suffix in ["-wal", "-shm", "-journal"] {
        fs::remove_file(sqlite_sidecar_path(&fixture.database, suffix))?;
    }
    for suffix in ["-wal", "-shm", "-journal"] {
        let guard = fixture
            .config
            .bind_existing_recovery_database(&fixture.database)?;
        let path = sqlite_sidecar_path(&fixture.database, suffix);
        write_private(&path, b"appeared")?;
        assert_eq!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate)
        );
        drop(guard);
        fs::remove_file(path)?;
    }
    Ok(())
}

#[test]
fn attributes_are_part_of_the_complete_retained_identity() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.source(b"immutable bytes")?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let original = fs::metadata(&fixture.database)?.permissions();
    let mut changed = original.clone();
    changed.set_readonly(true);
    fs::set_permissions(&fixture.database, changed)?;
    assert!(fs::metadata(&fixture.database)?.permissions().readonly());
    let rejected = guard.verify_inspection_unchanged() == Err(SqliteRecoveryError::Indeterminate);
    // Restore the fixture even on an assertion failure, without repairing any
    // production input or letting the reversion become the observed result.
    fs::set_permissions(&fixture.database, original)?;
    eprintln!("WINDOWS_RECOVERY metadata changed=true rejected={rejected}");
    assert!(rejected, "a retained handle does not excuse metadata drift");
    Ok(())
}

#[test]
fn missing_inputs_are_not_created_and_live_writers_cannot_be_admitted() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    assert!(matches!(
        fixture
            .config
            .bind_existing_recovery_database(&fixture.database),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert!(!fixture.database.try_exists()?);
    fixture.source(b"original")?;
    let writer = fs::OpenOptions::new().write(true).open(&fixture.database)?;
    assert!(matches!(
        fixture
            .config
            .bind_existing_recovery_database(&fixture.database),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    drop(writer);
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    guard.verify_inspection_unchanged()?;
    let absent = fixture.home.join("missing");
    let wrong = SqliteConfig::new_for_testing(absent.as_path().abs());
    assert!(matches!(
        wrong.bind_existing_recovery_database(&absent.join("source.sqlite3")),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert!(!absent.try_exists()?);
    Ok(())
}

#[test]
fn hardlinked_database_and_each_sidecar_are_rejected_without_mutation() -> anyhow::Result<()> {
    for suffix in ["", "-wal", "-shm", "-journal"] {
        let fixture = Fixture::new()?;
        fixture.complete()?;
        let path = sqlite_sidecar_path(&fixture.database, suffix);
        let before = fs::read(&path)?;
        fs::hard_link(&path, fixture.home.join("alias"))?;
        assert!(matches!(
            fixture
                .config
                .bind_existing_recovery_database(&fixture.database),
            Err(SqliteRecoveryError::Indeterminate)
        ));
        assert_eq!(fs::read(&path)?, before);
        assert_eq!(fs::read(fixture.home.join("alias"))?, before);
    }
    Ok(())
}

#[test]
fn junction_parent_is_rejected_without_creating_or_mutating_a_source() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.source(b"original")?;
    let alias = unique_temp_dir();
    let output = std::process::Command::new("cmd")
        .args(["/C", "mklink", "/J"])
        .arg(&alias)
        .arg(&fixture.home)
        .output()?;
    anyhow::ensure!(
        output.status.success(),
        "junction fixture failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let config = SqliteConfig::new_for_testing(alias.as_path().abs());
    let rejected = matches!(
        config.bind_existing_recovery_database(&alias.join("source.sqlite3")),
        Err(SqliteRecoveryError::Indeterminate)
    );
    fs::remove_dir(&alias)?;
    assert!(rejected);
    assert_eq!(fs::read(&fixture.database)?, b"original");
    Ok(())
}

#[test]
fn materialized_copy_is_private_complete_bounded_and_create_new() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.complete()?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let ordinary_source = fixture.config.home().join("source.sqlite3");
    assert_ne!(ordinary_source, fixture.database);
    assert!(windows::same_recovery_path(
        &ordinary_source,
        &fixture.database
    ));
    assert_eq!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&guard, &ordinary_source),
        Err(SqliteRecoveryError::Indeterminate)
    );
    assert_eq!(fs::read(&fixture.database)?, b"database bytes");
    let target = fixture.home.join("candidate.sqlite3");
    fixture
        .config
        .materialize_identity_bound_recovery_copy(&guard, &target)?;
    assert_eq!(fs::read(&target)?, b"database bytes");
    assert_eq!(
        fs::read(sqlite_sidecar_path(&target, "-wal"))?,
        b"wal bytes"
    );
    assert_eq!(
        fs::read(sqlite_sidecar_path(&target, "-journal"))?,
        b"journal bytes"
    );
    assert!(!sqlite_sidecar_path(&target, "-shm").try_exists()?);
    assert_eq!(fs::read(&fixture.database)?, b"database bytes");
    drop(guard);
    let fresh = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    assert!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&fresh, &target)
            .is_err()
    );
    assert_eq!(fs::read(&target)?, b"database bytes");
    drop(fresh);
    let copied = fixture.config.bind_existing_recovery_database(&target)?;
    copied.verify_inspection_unchanged()?;
    drop(copied);
    let partial = fixture.home.join("partial.sqlite3");
    let occupied_wal = sqlite_sidecar_path(&partial, "-wal");
    write_private(&occupied_wal, b"pre-existing destination")?;
    let fresh = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    assert!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&fresh, &partial)
            .is_err()
    );
    assert!(
        !partial.try_exists()?,
        "clean up only our just-created database handle"
    );
    assert_eq!(fs::read(&occupied_wal)?, b"pre-existing destination");
    assert_eq!(fs::read(&fixture.database)?, b"database bytes");
    drop(fresh);
    fs::OpenOptions::new()
        .write(true)
        .open(&fixture.database)?
        .set_len(128 * 1024 * 1024 + 1)?;
    let oversized = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let never_created = fixture.home.join("oversized.sqlite3");
    assert_eq!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&oversized, &never_created),
        Err(SqliteRecoveryError::Unavailable)
    );
    assert!(!never_created.try_exists()?);
    Ok(())
}

#[tokio::test]
async fn cold_image_is_immutable_and_reconnects_to_the_captured_bytes() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    fixture.source(b"")?;
    let source = fixture
        .config
        .open_durable_evidence_pool(&fixture.database)
        .await?;
    sqlx::query("CREATE TABLE fact(value TEXT); INSERT INTO fact VALUES ('original')")
        .execute(&source)
        .await?;
    source.close().await;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.database)?;
    let original = fs::read(&fixture.database)?;
    let pool = fixture
        .config
        .open_cold_image_read_only_pool(&guard)
        .await?;
    assert_eq!(fs::read(&fixture.database)?, original);
    sqlx::query("PRAGMA query_only = OFF")
        .execute(&pool)
        .await?;
    assert!(
        sqlx::query("UPDATE fact SET value = 'mutated'")
            .execute(&pool)
            .await
            .is_err()
    );
    assert!(fs::write(&fixture.database, b"replacement").is_err());
    drop(guard);
    fs::write(&fixture.database, b"replacement")?;
    pool.acquire().await?.close().await?;
    let value: String = sqlx::query_scalar("SELECT value FROM fact")
        .fetch_one(&pool)
        .await?;
    assert_eq!(value, "original");
    pool.close().await;
    Ok(())
}

#[test]
fn namespace_aliases_preserve_exact_absolute_components() {
    for (ordinary, verbatim) in [
        (r"C:\private\state", r"\\?\C:\private\state"),
        (r"C:\", r"\\?\C:\"),
        (r"\\server\share\private", r"\\?\UNC\server\share\private"),
        (r"\\server\share\", r"\\?\UNC\server\share\"),
    ] {
        assert!(windows::same_recovery_path(
            Path::new(ordinary),
            Path::new(verbatim)
        ));
        assert!(windows::same_recovery_path(
            Path::new(verbatim),
            Path::new(ordinary)
        ));
    }
    for (left, right) in [
        (r"C:\private", r"\\?\D:\private"),
        (r"C:\private", r"\\?\C:\Private"),
        (r"C:\private\..\state", r"\\?\C:\state"),
        (r"\\server\share\private", r"\\?\UNC\other\share\private"),
        (r"\\server\share\private", r"\\?\UNC\server\other\private"),
        (r"C:private", r"C:private"),
        (r"private\state", r"private\state"),
        (r"\\.\C:\private", r"C:\private"),
        (
            r"\\?\GLOBALROOT\Device\private",
            r"\\?\GLOBALROOT\Device\private",
        ),
    ] {
        assert!(!windows::same_recovery_path(
            Path::new(left),
            Path::new(right)
        ));
    }
}
