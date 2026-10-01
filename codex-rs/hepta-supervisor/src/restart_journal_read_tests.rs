//! The canonical main/companion journal shares the stable bounded read boundary.

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::*;

fn publish(root: &Path) -> Result<()> {
    write_main_restart_budget(
        root,
        &RestartBudgetState {
            schema_version: 1,
            window_started_unix_ms: 1_000,
            attempts: 2,
            pending: true,
            next_eligible_unix_ms: 2_000,
        },
    )?;
    let journal = RestartBudgetJournal::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
        ReleaseId::parse("bounded-restart")?,
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 1,
            window_started_unix_millis: Some(1_000),
        },
    )?;
    write_restart_journal(root, &journal)?;
    Ok(())
}

#[test]
fn restart_readers_preserve_both_charged_domains_and_missing_state() -> Result<()> {
    let root = tempfile::tempdir()?;
    assert!(read_main_restart_budget(root.path())?.is_none());
    assert!(read_restart_journal(root.path())?.is_none());
    publish(root.path())?;
    let main =
        read_main_restart_budget(root.path())?.ok_or_else(|| anyhow::anyhow!("main claim"))?;
    let companion =
        read_restart_journal(root.path())?.ok_or_else(|| anyhow::anyhow!("companion"))?;
    assert_eq!(
        (main.attempts, main.pending, companion.matrix.attempts),
        (2, true, 1)
    );
    Ok(())
}

#[test]
fn restart_readers_reject_oversized_and_torn_records_without_resetting_budget() -> Result<()> {
    let root = tempfile::tempdir()?;
    publish(root.path())?;
    let path = root.path().join(RESTART_JOURNAL_FILE);
    for bytes in [vec![b'x'; MAX_RESTART_JOURNAL_BYTES + 1], b"{".to_vec()] {
        std::fs::write(&path, &bytes)?;
        assert!(read_main_restart_budget(root.path()).is_err());
        assert!(read_restart_journal(root.path()).is_err());
        assert_eq!(std::fs::read(&path)?, bytes);
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn restart_readers_reject_linked_and_writable_records() -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir()?;
    publish(root.path())?;
    let path = root.path().join(RESTART_JOURNAL_FILE);
    let alias = root.path().join("restart-alias");
    std::fs::hard_link(&path, &alias)?;
    assert!(read_main_restart_budget(root.path()).is_err());
    assert!(read_restart_journal(root.path()).is_err());
    std::fs::remove_file(&alias)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(/*mode*/ 0o660))?;
    assert!(read_main_restart_budget(root.path()).is_err());
    assert!(read_restart_journal(root.path()).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(/*mode*/ 0o600))?;
    assert!(read_main_restart_budget(root.path())?.is_some());
    std::fs::rename(&path, &alias)?;
    std::os::unix::fs::symlink(&alias, &path)?;
    assert!(read_main_restart_budget(root.path()).is_err());
    assert!(read_restart_journal(root.path()).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn fifo_restart_record_is_rejected_without_waiting_for_a_writer() -> Result<()> {
    use std::os::unix::ffi::OsStrExt;
    let root = tempfile::tempdir()?;
    let path = root.path().join(RESTART_JOURNAL_FILE);
    let name = std::ffi::CString::new(path.as_os_str().as_bytes())?;
    // SAFETY: the path is NUL-terminated and mkfifo has no pointer outputs.
    if unsafe { libc::mkfifo(name.as_ptr(), 0o600) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    assert!(read_main_restart_budget(root.path()).is_err());
    assert!(read_restart_journal(root.path()).is_err());
    Ok(())
}
