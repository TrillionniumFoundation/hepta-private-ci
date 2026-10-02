use super::*;
use std::os::unix::fs::PermissionsExt;

#[test]
fn partial_goal_stores_require_reconciliation_and_preserve_original_bytes() -> HostResult<()> {
    let directory = tempfile::tempdir()?;
    let paths = ["generation", "index", "witness"].map(|name| directory.path().join(name));
    let refs = paths.each_ref().map(PathBuf::as_path);
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    assert!(matches!(
        mode(refs, StoreRequirement::NewOrExisting)?,
        crate::CpuNeuronGenerationOpenModeV1::Create
    ));
    for (index, path) in paths.iter().enumerate() {
        std::fs::write(path, b"original fixture journal bytes")?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        if index < 2 {
            assert!(mode(refs, StoreRequirement::NewOrExisting).is_err());
            assert!(mode(refs, StoreRequirement::Existing).is_err());
        }
    }
    assert!(matches!(
        mode(refs, StoreRequirement::Existing)?,
        crate::CpuNeuronGenerationOpenModeV1::Recover
    ));
    for path in &paths {
        assert_eq!(std::fs::read(path)?, b"original fixture journal bytes");
    }
    // The original native owners, rather than this file-presence check,
    // authenticate the recovered headers when opening the scope.
    Ok(())
}

#[test]
fn goal_recovery_rejects_exposed_linked_or_aliased_files_without_reset() -> HostResult<()> {
    let directory = tempfile::tempdir()?;
    let paths = ["generation", "index", "witness"].map(|name| directory.path().join(name));
    let refs = paths.each_ref().map(PathBuf::as_path);
    for path in &paths {
        std::fs::write(path, b"original private bytes")?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    std::fs::set_permissions(&paths[0], std::fs::Permissions::from_mode(0o640))?;
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    std::fs::set_permissions(&paths[0], std::fs::Permissions::from_mode(0o600))?;
    let alias = directory.path().join("aliased-generation");
    std::fs::hard_link(&paths[0], &alias)?;
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    std::fs::remove_file(&alias)?;
    std::fs::rename(&paths[0], &alias)?;
    std::os::unix::fs::symlink(&alias, &paths[0])?;
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    assert_eq!(std::fs::read(&alias)?, b"original private bytes");
    Ok(())
}
