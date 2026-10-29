#[cfg(unix)]
#[test]
fn rejects_group_or_other_runtime_permissions() -> Result<(), crate::QualificationError> {
    use std::os::unix::fs::PermissionsExt;

    let temp = tempfile::tempdir()?;
    let root = temp.path().join("runtime");
    super::durable::create_private_directory(&root)?;
    let artifact = root.join("artifact.json");
    super::durable::write_private_new(&artifact, b"{}")?;
    super::durable::verify_private_tree(&root)?;
    std::fs::set_permissions(&artifact, std::fs::Permissions::from_mode(0o644))?;
    assert!(super::durable::verify_private_tree(&root).is_err());
    Ok(())
}

#[test]
fn synchronizes_new_file_and_directory_without_replacing_existing_bytes()
-> Result<(), crate::QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("runtime");
    super::durable::create_private_directory(&root)?;
    super::durable::sync_directory(temp.path())?;
    let artifact = root.join("artifact.json");
    super::durable::write_private_new(&artifact, b"original")?;
    assert!(super::durable::write_private_new(&artifact, b"replacement").is_err());
    super::durable::sync_directory(&root)?;
    assert_eq!(std::fs::read(&artifact)?, b"original");
    assert!(super::durable::sync_directory(&root.join("missing")).is_err());
    Ok(())
}

#[cfg(windows)]
#[test]
fn windows_directory_flush_uses_write_access_and_propagates_sharing_failure()
-> Result<(), crate::QualificationError> {
    use std::fs::OpenOptions;
    use std::os::windows::fs::OpenOptionsExt;

    use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
    use windows_sys::Win32::Foundation::ERROR_SHARING_VIOLATION;
    use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
    use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;

    let temp = tempfile::tempdir()?;
    let read_only = OpenOptions::new()
        .read(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(temp.path())?;
    let Err(error) = read_only.sync_all() else {
        panic!("read-only flush must fail")
    };
    assert_eq!(error.raw_os_error(), Some(ERROR_ACCESS_DENIED as i32));
    super::durable::sync_directory(temp.path())?;
    drop(read_only);
    let held = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(temp.path())?;
    let Err(crate::QualificationError::Io(error)) = super::durable::sync_directory(temp.path())
    else {
        panic!("sharing error must preserve the original IO failure")
    };
    assert_eq!(error.raw_os_error(), Some(ERROR_SHARING_VIOLATION as i32));
    drop(held);
    super::durable::sync_directory(temp.path())?;
    let file = temp.path().join("not-a-directory");
    std::fs::write(&file, b"untouched")?;
    assert!(super::durable::sync_directory(&file).is_err());
    assert_eq!(std::fs::read(file)?, b"untouched");
    Ok(())
}

#[cfg(windows)]
#[test]
fn windows_directory_sync_refuses_a_real_junction() -> Result<(), crate::QualificationError> {
    let temp = tempfile::tempdir()?;
    let target = temp.path().join("target");
    super::durable::create_private_directory(&target)?;
    let junction = temp.path().join("junction");
    let output = std::process::Command::new("cmd.exe")
        .args(["/D", "/C", "mklink", "/J"])
        .arg(&junction)
        .arg(&target)
        .output()?;
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    assert!(super::durable::sync_directory(&junction).is_err());
    super::durable::sync_directory(&target)?;
    std::fs::remove_dir(junction)?;
    Ok(())
}
