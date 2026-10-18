//! Store shape chooses original recovery; it grants no header or artifact admission.
use super::*;
use std::os::unix::fs::PermissionsExt;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn partial_or_substituted_original_stores_never_choose_fresh_creation() -> TestResult {
    let root = tempfile::tempdir()?;
    let paths = [
        root.path().join("generation"),
        root.path().join("index"),
        root.path().join("witness"),
    ];
    let refs = [&*paths[0], &*paths[1], &*paths[2]];
    assert!(matches!(
        existing_generation_mode(refs)?,
        CpuNeuronGenerationOpenModeV1::Create
    ));
    std::fs::write(&paths[0], b"existing generation obligation")?;
    std::fs::set_permissions(&paths[0], std::fs::Permissions::from_mode(0o600))?;
    let original = std::fs::read(&paths[0])?;
    assert!(existing_generation_mode(refs).is_err());
    assert_eq!(std::fs::read(&paths[0])?, original);
    for path in &paths[1..] {
        std::fs::write(path, b"existing store obligation")?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    assert!(matches!(
        existing_generation_mode(refs)?,
        CpuNeuronGenerationOpenModeV1::Recover
    ));
    std::fs::hard_link(&paths[2], root.path().join("linked-witness"))?;
    assert!(existing_generation_mode(refs).is_err());
    std::fs::remove_file(root.path().join("linked-witness"))?;
    std::fs::set_permissions(&paths[1], std::fs::Permissions::from_mode(0o644))?;
    assert!(existing_generation_mode(refs).is_err());
    assert_eq!(std::fs::read(&paths[0])?, original);
    Ok(())
}
