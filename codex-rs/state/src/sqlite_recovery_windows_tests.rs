use super::*;
use crate::runtime::test_support::unique_temp_dir;
use codex_utils_absolute_path::test_support::PathExt;
use codex_utils_path::windows_private::Access;
use codex_utils_path::windows_private::PrivateSqliteDirectory;
use pretty_assertions::assert_eq;
use std::fs;
use std::io::Write;
use std::process::Command;

const DATABASE_NAME: &str = "recovery.sqlite3";

struct Fixture {
    home: PathBuf,
    path: PathBuf,
    config: SqliteConfig,
}

impl Fixture {
    fn new() -> anyhow::Result<Self> {
        let home = unique_temp_dir();
        PrivateSqliteDirectory::prepare(&home)?;
        let path = home.join(DATABASE_NAME);
        let config = SqliteConfig::new_for_testing(home.as_path().abs());
        let fixture = Self { home, path, config };
        fixture.write_private_new(DATABASE_NAME, b"source database bytes")?;
        Ok(fixture)
    }

    fn write_private_new(&self, name: &str, bytes: &[u8]) -> anyhow::Result<()> {
        // These synthetic fixtures exercise retained-file recovery. Establish
        // their required owner at creation: an inherited DACL alone does not
        // make the default token owner equal to the token user.
        let directory = PrivateSqliteDirectory::open_writable(&self.home)?;
        let mut file = directory.open(name, Access::CreateNew)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        directory.sync_all()?;
        Ok(())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.home);
    }
}

#[tokio::test]
async fn native_source_inspection_is_read_only_and_filename_writer_entries_stay_unavailable()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    for suffix in ["-wal", "-shm", "-journal"] {
        fixture.write_private_new(&format!("{DATABASE_NAME}{suffix}"), suffix.as_bytes())?;
    }
    let directory = PrivateSqliteDirectory::inspect(&fixture.home)?;
    let before = directory.snapshot()?;
    let original = fs::read(&fixture.path)?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.path)?;
    guard.verify_inspection_unchanged()?;
    assert_eq!(directory.snapshot()?, before);
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
    assert_eq!(fs::read(&fixture.path)?, original);
    guard.verify_inspection_unchanged()?;
    Ok(())
}

#[test]
fn native_guard_rejects_replacements_links_sidecars_and_permission_drift() -> anyhow::Result<()> {
    for attack in [
        "replacement",
        "hardlink",
        "sidecar",
        "permission",
        "content",
    ] {
        let fixture = Fixture::new()?;
        let guard = fixture
            .config
            .bind_existing_recovery_database(&fixture.path)?;
        match attack {
            "replacement" => {
                fs::rename(&fixture.path, fixture.home.join("retained.sqlite3"))?;
                fixture.write_private_new(DATABASE_NAME, b"source database bytes")?;
            }
            "hardlink" => fs::hard_link(&fixture.path, fixture.home.join("alias.sqlite3"))?,
            "sidecar" => fixture.write_private_new(&format!("{DATABASE_NAME}-wal"), b"")?,
            "permission" => {
                let output = Command::new("icacls")
                    .arg(&fixture.path)
                    .args(["/grant", "*S-1-1-0:(R)"])
                    .output()?;
                assert!(
                    output.status.success(),
                    "synthetic ACL mutation: {output:?}"
                );
            }
            "content" => fs::write(&fixture.path, b"changed database bytes with different size")?,
            _ => unreachable!("fixed attack cases"),
        }
        assert_eq!(
            guard.verify_inspection_unchanged(),
            Err(SqliteRecoveryError::Indeterminate),
            "attack={attack}"
        );
    }
    Ok(())
}

#[test]
fn native_guard_rejects_reparse_roots_without_creating_or_repairing_them() -> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    let junction = unique_temp_dir();
    let output = Command::new("cmd")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&junction)
        .arg(&fixture.home)
        .output()?;
    assert!(output.status.success(), "synthetic junction: {output:?}");
    let config = SqliteConfig::new_for_testing(junction.as_path().abs());
    assert!(matches!(
        config.bind_existing_recovery_database(&junction.join("recovery.sqlite3")),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert_eq!(fs::read(&fixture.path)?, b"source database bytes");
    fs::remove_dir(&junction)?;
    let missing = unique_temp_dir();
    let config = SqliteConfig::new_for_testing(missing.as_path().abs());
    assert!(matches!(
        config.bind_existing_recovery_database(&missing.join("absent.sqlite3")),
        Err(SqliteRecoveryError::Indeterminate)
    ));
    assert!(!missing.exists());
    Ok(())
}

#[test]
fn native_materialization_copies_only_retained_replay_files_and_never_overwrites_a_candidate()
-> anyhow::Result<()> {
    let fixture = Fixture::new()?;
    for suffix in ["-wal", "-shm", "-journal"] {
        fixture.write_private_new(&format!("{DATABASE_NAME}{suffix}"), suffix.as_bytes())?;
    }
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.path)?;
    let candidate = fixture.home.join("new.sqlite3");
    fixture
        .config
        .materialize_identity_bound_recovery_copy(&guard, &candidate)?;
    assert_eq!(fs::read(&candidate)?, b"source database bytes");
    assert_eq!(fs::read(sqlite_sidecar_path(&candidate, "-wal"))?, b"-wal");
    assert_eq!(
        fs::read(sqlite_sidecar_path(&candidate, "-journal"))?,
        b"-journal"
    );
    assert!(!sqlite_sidecar_path(&candidate, "-shm").exists());
    assert_eq!(fs::read(&fixture.path)?, b"source database bytes");
    let directory = PrivateSqliteDirectory::inspect(&fixture.home)?;
    for name in ["new.sqlite3", "new.sqlite3-wal", "new.sqlite3-journal"] {
        directory.open(name, Access::Read)?;
    }
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.path)?;
    assert_eq!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&guard, &candidate),
        Err(SqliteRecoveryError::Indeterminate)
    );
    assert_eq!(fs::read(&candidate)?, b"source database bytes");
    let failed = fixture.home.join("failed.sqlite3");
    let occupied_wal = sqlite_sidecar_path(&failed, "-wal");
    fixture.write_private_new("failed.sqlite3-wal", b"preexisting WAL must survive")?;
    let guard = fixture
        .config
        .bind_existing_recovery_database(&fixture.path)?;
    assert_eq!(
        fixture
            .config
            .materialize_identity_bound_recovery_copy(&guard, &failed),
        Err(SqliteRecoveryError::Indeterminate)
    );
    assert!(
        !failed.exists(),
        "new database is removed by its retained handle"
    );
    assert_eq!(fs::read(&occupied_wal)?, b"preexisting WAL must survive");
    assert!(!sqlite_sidecar_path(&failed, "-journal").exists());
    Ok(())
}
