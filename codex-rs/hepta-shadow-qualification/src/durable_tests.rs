use pretty_assertions::assert_eq;

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
fn syncs_completed_artifact_and_parent_directory() -> Result<(), crate::QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("runtime");
    super::durable::create_private_directory(&root)?;
    let artifact = root.join("artifact.json");
    let bytes = b"{\"completed\":true}\n";
    super::durable::write_private_new(&artifact, bytes)?;
    super::durable::sync_directory(&root)?;
    assert_eq!(std::fs::read(&artifact)?, bytes);
    assert!(root.is_dir());
    super::durable::verify_private_tree(&root)?;
    Ok(())
}

#[test]
fn missing_directory_sync_propagates_open_error() -> Result<(), crate::QualificationError> {
    let temp = tempfile::tempdir()?;
    let absent = temp.path().join("absent");
    let error = super::durable::sync_directory(&absent)
        .expect_err("directory sync must propagate a failed open");
    let crate::QualificationError::Io(error) = error else {
        panic!("unexpected directory error: {error:?}");
    };
    assert_eq!(error.kind(), std::io::ErrorKind::NotFound);
    assert!(!absent.exists());
    Ok(())
}
