use super::*;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn private_regular_file_is_bounded_and_rejects_unsafe_identity() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let path = root.join("config.json");
    fs::write(&path, b"{}")?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    assert_eq!(read(&path, /*maximum*/ 2)?, b"{}");
    assert!(read(&path, /*maximum*/ 1).is_err());
    let alias = root.join("alias");
    symlink(&path, &alias)?;
    assert!(read(&alias, /*maximum*/ 2).is_err());
    let other = root.join("hard-link");
    fs::hard_link(&path, &other)?;
    assert!(read(&path, /*maximum*/ 2).is_err());
    fs::remove_file(other)?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644))?;
    assert!(read(&path, /*maximum*/ 2).is_err());
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o770))?;
    assert!(read(&path, /*maximum*/ 2).is_err());
    Ok(())
}

#[test]
fn private_fifo_without_a_writer_is_rejected_before_any_blocking_read() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let path = root.join("substituted-fifo");
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        &path,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )?;
    let (sent, received) = mpsc::channel();
    let reader = std::thread::spawn(move || sent.send(read(&path, /*maximum*/ 64)));
    assert!(received.recv_timeout(Duration::from_secs(2))?.is_err());
    reader
        .join()
        .map_err(|_| anyhow::anyhow!("private reader thread panicked"))??;
    Ok(())
}
