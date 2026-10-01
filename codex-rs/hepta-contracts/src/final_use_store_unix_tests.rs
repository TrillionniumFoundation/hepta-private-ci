use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn final_use_fifo_read_rejects_without_waiting_for_a_writer()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    #[cfg(target_os = "macos")]
    clear_fresh_fixture_acl(directory.path())?;
    let path = directory.path().join("authority.json");
    let output = std::process::Command::new("/usr/bin/mkfifo")
        .args(["-m", "600"])
        .arg(&path)
        .output()?;
    if !output.status.success() {
        return Err(
            std::io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into(),
        );
    }
    let metadata = std::fs::symlink_metadata(&path)?;
    assert!(metadata.file_type().is_fifo());
    assert_eq!(metadata.permissions().mode() & 0o777, 0o600);
    let root = prepare_directory(directory.path())?;
    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let result = open_private(&root, "authority.json", Access::Read).map(|_| ());
        let _ = sender.send(result);
    });
    // Never join a stalled worker: removing NONBLOCK must fail this assertion
    // within the deadline rather than hang the test process on the FIFO open.
    let result = receiver.recv_timeout(Duration::from_secs(2))?;
    assert_eq!(result, Err(FinalUseError::UnsafeStateDirectory));
    assert!(worker.join().is_ok());
    assert!(std::fs::symlink_metadata(&path)?.file_type().is_fifo());
    assert_eq!(
        std::fs::metadata(&path)?.permissions().mode() & 0o777,
        0o600
    );
    Ok(())
}

#[cfg(target_os = "macos")]
fn clear_fresh_fixture_acl(path: &Path) -> Result<(), Box<dyn std::error::Error>> {
    // This is a newly created test-owned directory, not existing product state.
    let output = std::process::Command::new("/bin/chmod")
        .arg("-N")
        .arg(path)
        .output()?;
    if !output.status.success() {
        return Err(
            std::io::Error::other(String::from_utf8_lossy(&output.stderr).into_owned()).into(),
        );
    }
    Ok(())
}
