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
fn directory_flush_requires_an_existing_directory() -> Result<(), crate::QualificationError> {
    let temporary = tempfile::tempdir()?;
    let directory = temporary.path().join("durable");
    super::durable::create_private_directory(&directory)?;
    super::durable::write_private_new(&directory.join("receipt"), b"persisted")?;
    super::durable::sync_directory(&directory)?;
    assert!(super::durable::sync_directory(&directory.join("receipt")).is_err());
    assert!(super::durable::sync_directory(&directory.join("missing")).is_err());
    Ok(())
}

#[cfg(windows)]
#[test]
fn directory_flush_rejects_a_junction() -> Result<(), crate::QualificationError> {
    let temporary = tempfile::tempdir()?;
    let directory = temporary.path().join("durable");
    super::durable::create_private_directory(&directory)?;
    let alias = temporary.path().join("alias");
    let status = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&directory)
        .status()?;
    assert!(status.success());
    assert!(super::durable::sync_directory(&alias).is_err());
    super::durable::sync_directory(&directory)?;
    Ok(())
}
