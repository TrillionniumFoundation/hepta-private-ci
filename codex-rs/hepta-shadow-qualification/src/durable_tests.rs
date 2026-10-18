#[cfg(windows)]
#[test]
fn durable_write_flushes_the_real_directory_and_preserves_payload()
-> Result<(), crate::QualificationError> {
    let temporary = tempfile::tempdir()?;
    let artifact = temporary.path().join("artifact");
    super::durable::write_private_new(&artifact, b"retained")?;
    assert_eq!(
        super::durable::read_private_bounded(&artifact, /*max_bytes*/ 64)?,
        b"retained"
    );
    Ok(())
}

#[cfg(windows)]
#[test]
fn directory_barrier_rejects_files_missing_paths_and_junctions()
-> Result<(), crate::QualificationError> {
    let temporary = tempfile::tempdir()?;
    let artifact = temporary.path().join("artifact");
    let missing = temporary.path().join("missing");
    std::fs::write(&artifact, b"retained")?;
    assert!(super::durable::sync_directory(&artifact).is_err());
    assert!(super::durable::sync_directory(&missing).is_err());
    assert!(!missing.exists());

    let real = temporary.path().join("real");
    let alias = temporary.path().join("alias");
    std::fs::create_dir(&real)?;
    let output = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&real)
        .output()?;
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    assert!(super::durable::sync_directory(&alias).is_err());
    std::fs::remove_dir(alias)?;
    assert_eq!(std::fs::read(artifact)?, b"retained");
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
