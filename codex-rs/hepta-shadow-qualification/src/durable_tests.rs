use pretty_assertions::assert_eq;

#[test]
fn writes_are_readable_after_directory_sync_without_overwriting()
-> Result<(), crate::QualificationError> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("runtime");
    super::durable::create_private_directory(&root)?;
    let path = root.join("artifact.json");
    super::durable::write_private_new(&path, b"original")?;
    assert_eq!(
        super::durable::read_private_bounded(&path, 64)?,
        b"original"
    );
    assert!(super::durable::write_private_new(&path, b"must not overwrite").is_err());
    assert_eq!(
        super::durable::read_private_bounded(&path, 64)?,
        b"original"
    );
    Ok(())
}

#[test]
fn missing_directory_sync_rejects_without_creating_state() -> Result<(), crate::QualificationError>
{
    let temporary = tempfile::tempdir()?;
    let path = temporary.path().join("absent");
    assert!(
        matches!(super::durable::sync_directory(&path), Err(crate::QualificationError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound)
    );
    assert!(!path.exists());
    assert_eq!(std::fs::read_dir(temporary.path())?.count(), 0);
    Ok(())
}

#[cfg(windows)]
#[test]
fn directory_sharing_failure_is_not_reported_as_success() -> Result<(), crate::QualificationError> {
    use std::os::windows::fs::OpenOptionsExt;

    let temporary = tempfile::tempdir()?;
    let blocker = std::fs::OpenOptions::new()
        .read(true)
        .share_mode(0)
        .custom_flags(0x0200_0000)
        .open(temporary.path())?;
    assert!(matches!(
        super::durable::sync_directory(temporary.path()),
        Err(crate::QualificationError::Io(_))
    ));
    drop(blocker);
    super::durable::sync_directory(temporary.path())?;
    Ok(())
}

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
