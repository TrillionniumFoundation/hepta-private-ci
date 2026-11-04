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

fn materialize_fixture() -> anyhow::Result<(std::path::PathBuf, SqliteConfig)> {
    let home = unique_temp_dir();
    std::fs::create_dir(&home)?;
    std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))?;
    let home = home.canonicalize()?;
    let config = SqliteConfig::new_for_testing(home.as_path().abs());
    Ok((home, config))
}

fn materialize_private_file(path: &std::path::Path, size: u64) -> anyhow::Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    file.set_len(size)?;
    Ok(())
}

fn materialize_child(test: &str, key: &str) -> anyhow::Result<()> {
    use anyhow::Context;
    let module = module_path!()
        .split_once("::")
        .context("test module has crate prefix")?
        .1;
    let output = std::process::Command::new(std::env::current_exe()?)
        .args(["--exact", &format!("{module}::{test}"), "--nocapture"])
        .env(key, "1")
        .output()?;
    assert!(
        output.status.success(),
        "isolated native resource control failed: {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(())
}

#[test]
fn materialize_partial_write_failure_cleans_only_created_files_and_retries() -> anyhow::Result<()> {
    use std::io::Write;
    const CHILD: &str = "CODEX_SQLITE_MATERIALIZE_FSIZE_CHILD";
    if std::env::var_os(CHILD).is_none() {
        return materialize_child(
            "materialize_partial_write_failure_cleans_only_created_files_and_retries",
            CHILD,
        );
    }
    let (home, config) = materialize_fixture()?;
    let _cleanup = scopeguard::guard(home.clone(), |home| {
        let _ = std::fs::remove_dir_all(home);
    });
    let database = home.join("original.sqlite3");
    let wal = super::super::sqlite_sidecar_path(&database, "-wal");
    let journal = super::super::sqlite_sidecar_path(&database, "-journal");
    materialize_private_file(&database, 4096)?;
    materialize_private_file(&wal, 16384)?;
    materialize_private_file(&journal, 2048)?;
    let original = [
        std::fs::read(&database)?,
        std::fs::read(&wal)?,
        std::fs::read(&journal)?,
    ];
    let target = home.join("candidate.sqlite3");
    let target_wal = super::super::sqlite_sidecar_path(&target, "-wal");
    let target_journal = super::super::sqlite_sidecar_path(&target, "-journal");
    // This exact-test child owns the process-wide limit and signal handler.
    // Its parent and all other tests retain their original process settings.
    let mut previous = libc::rlimit {
        rlim_cur: 0,
        rlim_max: 0,
    };
    // SAFETY: previous is writable and the resource selector is valid.
    anyhow::ensure!(
        unsafe { libc::getrlimit(libc::RLIMIT_FSIZE, &mut previous) } == 0,
        "getrlimit failed: {}",
        std::io::Error::last_os_error()
    );
    anyhow::ensure!(
        previous.rlim_max >= 8192,
        "hard file-size limit cannot run control"
    );
    let limited = libc::rlimit {
        rlim_cur: 8192,
        rlim_max: previous.rlim_max,
    };
    // SAFETY: ignore the signal in this isolated child so write_all returns EFBIG.
    let prior_signal = unsafe { libc::signal(libc::SIGXFSZ, libc::SIG_IGN) };
    anyhow::ensure!(prior_signal != libc::SIG_ERR, "install SIGXFSZ handler");
    // SAFETY: limited preserves the existing hard limit.
    anyhow::ensure!(
        unsafe { libc::setrlimit(libc::RLIMIT_FSIZE, &limited) } == 0,
        "setrlimit failed: {}",
        std::io::Error::last_os_error()
    );

    let failed = (|| -> anyhow::Result<()> {
        let probe = home.join("native-efbig-probe");
        materialize_private_file(&probe, 0)?;
        let mut file = std::fs::OpenOptions::new().write(true).open(&probe)?;
        let error = match file.write_all(&original[1]) {
            Ok(()) => anyhow::bail!("native write did not exceed the file-size limit"),
            Err(error) => error,
        };
        assert_eq!(error.raw_os_error(), Some(libc::EFBIG));
        assert_eq!(file.metadata()?.len(), 8192);
        drop(file);
        std::fs::remove_file(probe)?;
        let guard = config.bind_existing_recovery_database(&database)?;
        assert_eq!(
            config.materialize_identity_bound_recovery_copy(&guard, &target),
            Err(SqliteRecoveryError::Indeterminate)
        );
        assert!(!target.exists(), "successful database copy must be removed");
        assert!(
            !target_wal.exists(),
            "partially written WAL must be removed"
        );
        assert!(
            !target_journal.exists(),
            "unstarted journal must remain absent"
        );
        Ok(())
    })();
    // SAFETY: restore this child's original soft limit before the retry.
    anyhow::ensure!(
        unsafe { libc::setrlimit(libc::RLIMIT_FSIZE, &previous) } == 0,
        "restore file-size limit: {}",
        std::io::Error::last_os_error()
    );
    // SAFETY: restore the handler returned by signal for this child process.
    anyhow::ensure!(
        unsafe { libc::signal(libc::SIGXFSZ, prior_signal) } != libc::SIG_ERR,
        "restore SIGXFSZ handler"
    );
    failed?;
    assert_eq!(
        [
            std::fs::read(&database)?,
            std::fs::read(&wal)?,
            std::fs::read(&journal)?
        ],
        original
    );
    // Candidate creation/removal legitimately changes the retained directory
    // snapshot. Rebind the unchanged source bytes for this same recovery cut.
    let guard = config.bind_existing_recovery_database(&database)?;
    config.materialize_identity_bound_recovery_copy(&guard, &target)?;
    assert_eq!(
        [
            std::fs::read(&target)?,
            std::fs::read(&target_wal)?,
            std::fs::read(&target_journal)?
        ],
        original
    );
    let copied = std::fs::read(&target)?;
    let guard = config.bind_existing_recovery_database(&database)?;
    assert_eq!(
        config.materialize_identity_bound_recovery_copy(&guard, &target),
        Err(SqliteRecoveryError::Indeterminate)
    );
    assert_eq!(
        std::fs::read(&target)?,
        copied,
        "occupied file must not be removed"
    );
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn materialize_aggregate_bound_precedes_bundle_allocation() -> anyhow::Result<()> {
    use anyhow::Context;
    const CHILD: &str = "CODEX_SQLITE_MATERIALIZE_AS_CHILD";
    if std::env::var_os(CHILD).is_none() {
        return materialize_child(
            "materialize_aggregate_bound_precedes_bundle_allocation",
            CHILD,
        );
    }
    let (home, config) = materialize_fixture()?;
    let _cleanup = scopeguard::guard(home.clone(), |home| {
        let _ = std::fs::remove_dir_all(home);
    });
    let database = home.join("large.sqlite3");
    for path in [
        database.clone(),
        super::super::sqlite_sidecar_path(&database, "-wal"),
        super::super::sqlite_sidecar_path(&database, "-journal"),
    ] {
        materialize_private_file(&path, 96 * 1024 * 1024)?;
    }
    let guard = config.bind_existing_recovery_database(&database)?;
    let pages = std::fs::read_to_string("/proc/self/statm")?
        .split_whitespace()
        .next()
        .context("current process virtual page count")?
        .parse::<u64>()?;
    // SAFETY: sysconf accepts this constant and does not mutate memory.
    let page_size = u64::try_from(unsafe { libc::sysconf(libc::_SC_PAGESIZE) })?;
    let headroom = pages
        .checked_mul(page_size)
        .and_then(|bytes| bytes.checked_add(64 * 1024 * 1024))
        .context("bounded virtual-memory headroom")?;
    let mut previous = libc::rlimit {
        rlim_cur: 0,
        rlim_max: 0,
    };
    // SAFETY: previous is valid writable storage for the resource query.
    anyhow::ensure!(
        unsafe { libc::getrlimit(libc::RLIMIT_AS, &mut previous) } == 0,
        "get address-space limit: {}",
        std::io::Error::last_os_error()
    );
    anyhow::ensure!(
        previous.rlim_max >= headroom,
        "hard address-space limit cannot run control"
    );
    let limited = libc::rlimit {
        rlim_cur: headroom,
        rlim_max: previous.rlim_max,
    };
    // SAFETY: only this exact-test child is limited; the hard limit is preserved.
    anyhow::ensure!(
        unsafe { libc::setrlimit(libc::RLIMIT_AS, &limited) } == 0,
        "limit address space: {}",
        std::io::Error::last_os_error()
    );
    let target = home.join("too-large-candidate.sqlite3");
    let result = config.materialize_identity_bound_recovery_copy(&guard, &target);
    // SAFETY: restore the original child-process limit before assertions.
    anyhow::ensure!(
        unsafe { libc::setrlimit(libc::RLIMIT_AS, &previous) } == 0,
        "restore address space: {}",
        std::io::Error::last_os_error()
    );
    assert_eq!(result, Err(SqliteRecoveryError::Unavailable));
    assert!(!target.exists());
    guard.verify_inspection_unchanged()?;
    Ok(())
}
