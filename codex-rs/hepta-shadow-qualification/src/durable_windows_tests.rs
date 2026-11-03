use super::*;

#[test]
fn directory_flush_persists_a_private_artifact() -> Result<(), QualificationError> {
    let root = tempfile::tempdir()?;
    sync_directory(root.path())?;
    let artifact = root.path().join("evidence.json");
    write_private_new(&artifact, b"{}")?;
    assert_eq!(read_private_bounded(&artifact, 2)?, b"{}");
    Ok(())
}

#[test]
fn directory_flush_rejects_a_regular_file() -> Result<(), QualificationError> {
    let root = tempfile::tempdir()?;
    let artifact = root.path().join("evidence.json");
    std::fs::write(&artifact, b"{}")?;
    assert!(sync_directory(&artifact).is_err());
    Ok(())
}
