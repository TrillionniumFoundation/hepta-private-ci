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
fn synchronizes_a_real_directory_after_creating_an_artifact()
-> Result<(), crate::QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("durable");
    super::durable::create_private_directory(&root)?;
    let artifact = root.join("artifact.json");
    super::durable::write_private_new(&artifact, b"{}")?;
    super::durable::sync_directory(&root)?;
    pretty_assertions::assert_eq!(
        super::durable::read_private_bounded(&artifact, /*max_bytes*/ 2)?,
        b"{}"
    );
    Ok(())
}

#[test]
fn rejects_a_regular_file_as_a_directory_sync_target() -> Result<(), crate::QualificationError> {
    let temp = tempfile::tempdir()?;
    let artifact = temp.path().join("regular-file");
    std::fs::write(&artifact, b"unchanged")?;
    let error = super::durable::sync_directory(&artifact)
        .expect_err("a regular file cannot acknowledge directory durability");
    assert!(matches!(error, crate::QualificationError::Invalid(_)));
    pretty_assertions::assert_eq!(std::fs::read(&artifact)?, b"unchanged");
    Ok(())
}
