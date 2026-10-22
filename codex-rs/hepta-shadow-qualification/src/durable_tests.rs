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

#[cfg(windows)]
#[test]
fn native_private_artifacts_round_trip_without_overwriting_existing_state()
-> Result<(), crate::QualificationError> {
    use pretty_assertions::assert_eq;

    let temp = tempfile::tempdir()?;
    let root = temp.path().join("runtime");
    super::durable::create_private_directory(&root)?;
    let artifact = root.join("artifact.json");
    super::durable::write_private_new(&artifact, b"original")?;
    super::durable::verify_private_tree(&root)?;
    let overwrite_rejected = super::durable::write_private_new(&artifact, b"replacement").is_err();
    let short_read_rejected = super::durable::read_private_bounded(&artifact, 7).is_err();
    assert_eq!(
        (
            overwrite_rejected,
            short_read_rejected,
            super::durable::read_private_bounded(&artifact, 8)?,
        ),
        (true, true, b"original".to_vec()),
    );
    Ok(())
}

#[cfg(windows)]
#[test]
fn native_private_artifact_reader_rejects_multiple_links() -> Result<(), crate::QualificationError>
{
    use pretty_assertions::assert_eq;

    let temp = tempfile::tempdir()?;
    let root = temp.path().join("runtime");
    super::durable::create_private_directory(&root)?;
    let artifact = root.join("artifact.json");
    super::durable::write_private_new(&artifact, b"original")?;
    let alias = root.join("alias.json");
    std::fs::hard_link(&artifact, &alias)?;
    assert_eq!(
        (
            super::durable::verify_private_regular(&artifact).is_err(),
            super::durable::read_private_bounded(&alias, 8).is_err(),
            std::fs::read(&artifact)?,
        ),
        (true, true, b"original".to_vec()),
    );
    Ok(())
}
