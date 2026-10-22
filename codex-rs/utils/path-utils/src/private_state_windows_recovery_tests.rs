//! Native Windows checks of retained identity, sharing, and private creation.

use super::super::PrivateFileAccess;
use super::super::open_private_state_child;
use super::super::open_private_state_directory;
use super::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::FileTimes;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::process::Command;
use std::time::Duration;
use std::time::UNIX_EPOCH;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

fn write_private(root: &Path, name: &str, bytes: &[u8]) -> io::Result<()> {
    let directory = open_private_state_directory(root)?;
    let mut file = open_private_state_child(&directory, name, PrivateFileAccess::Create)?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn metadata_handle(path: &Path, access: u32) -> io::Result<File> {
    OpenOptions::new()
        .access_mode(access)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
}

fn junction(target: &Path, alias: &Path) -> io::Result<()> {
    let output = Command::new("cmd")
        .args(["/C", "mklink", "/J"])
        .arg(alias)
        .arg(target)
        .output()?;
    if !output.status.success() {
        return Err(io::Error::other(format!(
            "junction fixture failed: stdout={} stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        )));
    }
    Ok(())
}

#[test]
fn existing_only_acquisition_does_not_create_or_accept_stream_names() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    assert!(RetainedPrivateStateDirectory::open_existing(&root).is_err());
    assert!(!root.try_exists()?);
    drop(open_private_state_directory(&root)?);
    let directory = RetainedPrivateStateDirectory::open_existing(&root)?;
    assert!(
        directory
            .retain_file(OsStr::new("missing.sqlite3"))?
            .is_none()
    );
    for name in [
        "../escape",
        "nested\\child",
        "database:stream",
        "C:\\escape",
        ".",
    ] {
        assert!(directory.retain_file(OsStr::new(name)).is_err());
        assert!(directory.create_new_file(OsStr::new(name)).is_err());
    }
    directory.verify_unchanged()?;
    assert_eq!(fs::read_dir(&root)?.count(), 0);
    Ok(())
}

#[test]
fn retained_file_excludes_real_writers_and_replacement_until_drop() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    write_private(&root, "database", b"retained evidence")?;
    let path = root.join("database");
    let writer = OpenOptions::new().write(true).open(&path)?;
    let directory = RetainedPrivateStateDirectory::open_existing(&root)?;
    assert!(directory.retain_file(OsStr::new("database")).is_err());
    drop(writer);

    let file = directory.retain_file(OsStr::new("database"))?.unwrap();
    let before = security_snapshot(&file.descriptor)?;
    let mut bytes = [0; 17];
    file.read_exact_at(&mut bytes, 0)?;
    assert_eq!(&bytes, b"retained evidence");
    assert!(OpenOptions::new().write(true).open(&path).is_err());
    assert!(fs::rename(&path, root.join("replacement")).is_err());
    assert!(fs::remove_file(&path).is_err());
    assert!(fs::rename(&root, temporary.path().join("moved")).is_err());
    directory.verify_unchanged()?;
    directory.verify_file_unchanged(&file)?;
    assert_eq!(security_snapshot(&file.descriptor)?, before);
    assert_eq!(fs::read(&path)?, b"retained evidence");

    drop(file);
    drop(directory);
    fs::write(&path, b"writer succeeds after retention ends")?;
    assert_eq!(fs::read(&path)?, b"writer succeeds after retention ends");
    Ok(())
}

#[test]
fn rejects_hardlinks_and_junctions_without_touching_redirected_state() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    write_private(&root, "database", b"original")?;
    fs::hard_link(root.join("database"), root.join("second-link"))?;
    let directory = RetainedPrivateStateDirectory::open_existing(&root)?;
    assert!(directory.retain_file(OsStr::new("database")).is_err());
    drop(directory);
    fs::remove_file(root.join("second-link"))?;

    let alias = temporary.path().join("alias");
    junction(&root, &alias)?;
    let denied = RetainedPrivateStateDirectory::open_existing(&alias).is_err();
    assert_eq!(fs::read(root.join("database"))?, b"original");
    fs::remove_dir(&alias)?;
    assert!(denied, "a real junction must not be traversed");
    let leaf_alias = root.join("redirected-file");
    junction(temporary.path(), &leaf_alias)?;
    let directory = RetainedPrivateStateDirectory::open_existing(&root)?;
    let denied = directory
        .retain_file(OsStr::new("redirected-file"))
        .is_err();
    drop(directory);
    fs::remove_dir(leaf_alias)?;
    assert!(
        denied,
        "a directory reparse leaf is not a regular recovery input"
    );
    Ok(())
}

#[test]
fn security_drift_is_rejected_without_repairing_the_actual_dacl() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    write_private(&root, "database", b"unchanged bytes")?;
    let path = root.join("database");
    let directory = RetainedPrivateStateDirectory::open_existing(&root)?;
    let file = directory.retain_file(OsStr::new("database"))?.unwrap();
    let security_writer = metadata_handle(&path, READ_CONTROL | WRITE_DAC)?;
    // Change actual security while the data handle is retained. This is not a
    // fake snapshot mutation: NULL DACL makes this real file unsafe to retain.
    let status = unsafe {
        SetSecurityInfo(
            security_writer.as_raw_handle() as HANDLE,
            1,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
        )
    };
    assert_eq!(status, ERROR_SUCCESS);
    assert!(directory.verify_file_unchanged(&file).is_err());
    let mut dacl: *mut ACL = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            security_writer.as_raw_handle() as HANDLE,
            1,
            DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    let remains_unsafe = status == ERROR_SUCCESS && !descriptor.is_null() && dacl.is_null();
    if !descriptor.is_null() {
        unsafe { LocalFree(descriptor as HLOCAL) };
    }
    assert!(
        remains_unsafe,
        "failed validation must not repair source security"
    );
    assert_eq!(fs::read(path)?, b"unchanged bytes");
    Ok(())
}

#[test]
fn timestamp_drift_on_same_retained_file_is_rejected() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    write_private(&root, "database", b"same bytes and file id")?;
    let directory = RetainedPrivateStateDirectory::open_existing(&root)?;
    let file = directory.retain_file(OsStr::new("database"))?.unwrap();
    let metadata = metadata_handle(&root.join("database"), FILE_WRITE_ATTRIBUTES)?;
    metadata.set_times(FileTimes::new().set_modified(UNIX_EPOCH + Duration::from_secs(1)))?;
    assert!(directory.verify_file_unchanged(&file).is_err());
    assert_eq!(fs::read(root.join("database"))?, b"same bytes and file id");
    Ok(())
}

#[test]
fn new_private_output_uses_exclusive_creation_and_preserves_collision() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("private");
    drop(open_private_state_directory(&root)?);
    let directory = RetainedPrivateStateDirectory::open_existing(&root)?;
    let mut output = directory.create_new_file(OsStr::new("candidate"))?;
    output.write_all(b"candidate bytes")?;
    output.sync_all()?;
    drop(output);
    assert!(directory.create_new_file(OsStr::new("candidate")).is_err());
    let file = directory.retain_file(OsStr::new("candidate"))?.unwrap();
    directory.verify_file_unchanged(&file)?;
    assert_eq!(fs::read(root.join("candidate"))?, b"candidate bytes");
    assert!(directory.discard_created_file(file.descriptor).is_err());
    assert_eq!(fs::read(root.join("candidate"))?, b"candidate bytes");
    let failed_output = directory.create_new_file(OsStr::new("failed-candidate"))?;
    directory.discard_created_file(failed_output)?;
    assert!(!root.join("failed-candidate").try_exists()?);
    Ok(())
}
