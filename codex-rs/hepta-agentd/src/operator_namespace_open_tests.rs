use super::*;
use std::ffi::CString;
use std::io::Read;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

#[test]
fn unchanged_private_file_is_read_through_the_actual_descriptor() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("owner.json");
    std::fs::write(&path, b"original")?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let before = std::fs::symlink_metadata(&path)?;
    let namespace = OperatorNamespace::capture(&path, &before)?;
    let mut file = namespace.open_regular(&path, &before)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"original");
    namespace.verify(&path, &std::fs::symlink_metadata(&path)?)?;
    Ok(())
}

#[test]
fn fifo_replacement_after_inspection_is_rejected_without_waiting_for_a_writer() -> io::Result<()> {
    let mut child = Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            "operator_namespace::tests::replacement_fixture_child",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_OWNER_FILE_REPLACEMENT_FIXTURE", "fifo")
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(1);
    loop {
        if let Some(status) = child.try_wait()? {
            assert!(
                status.success(),
                "actual replacement fixture failed: {status}"
            );
            break;
        }
        if Instant::now() >= deadline {
            // Only this owned, isolated blocking-read fixture is terminated.
            // Cargo, nextest, the parent test and live processes are untouched.
            child.kill()?;
            child.wait()?;
            return Err(io::Error::other(
                "regular-file replacement blocked waiting on a FIFO writer",
            ));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    Ok(())
}

#[test]
fn symlink_to_the_original_inode_is_rejected_before_a_read() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("owner.json");
    std::fs::write(&path, b"original")?;
    let before = std::fs::symlink_metadata(&path)?;
    let namespace = OperatorNamespace::capture(&path, &before)?;
    let retained = temp.path().join("retained.json");
    std::fs::rename(&path, &retained)?;
    std::os::unix::fs::symlink(&retained, &path)?;
    assert!(namespace.open_regular(&path, &before).is_err());
    Ok(())
}

#[test]
fn a_replaced_parent_directory_cannot_reuse_the_original_namespace() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let parent = temp.path().join("private");
    std::fs::create_dir(&parent)?;
    let path = parent.join("owner.json");
    std::fs::write(&path, b"original")?;
    let before = std::fs::symlink_metadata(&path)?;
    let namespace = OperatorNamespace::capture(&path, &before)?;
    std::fs::rename(&parent, temp.path().join("retained"))?;
    std::fs::create_dir(&parent)?;
    assert!(namespace.verify(&path, &before).is_err());
    Ok(())
}

#[test]
#[ignore = "only the actual bounded FIFO replacement parent launches this child"]
fn replacement_fixture_child() -> io::Result<()> {
    assert_eq!(
        std::env::var("HEPTA_OWNER_FILE_REPLACEMENT_FIXTURE").as_deref(),
        Ok("fifo")
    );
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("owner.json");
    std::fs::write(&path, b"original")?;
    let before = std::fs::symlink_metadata(&path)?;
    let namespace = OperatorNamespace::capture(&path, &before)?;
    std::fs::remove_file(&path)?;
    let name = CString::new(path.as_os_str().as_bytes())?;
    if unsafe { libc::mkfifo(name.as_ptr(), 0o600) } != 0 {
        return Err(io::Error::last_os_error());
    }
    assert!(namespace.open_regular(&path, &before).is_err());
    Ok(())
}
