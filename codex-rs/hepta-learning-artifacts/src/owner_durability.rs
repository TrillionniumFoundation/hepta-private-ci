//! The storage codec synchronizes file bytes. The named host also owns parent
//! directory durability on Unix, including newly created directory chains.
use super::ArtifactOwnerHostError;
use std::fs;
use std::fs::File;
use std::path::Path;

pub(super) fn create_root(path: &Path) -> Result<(), ArtifactOwnerHostError> {
    fs::create_dir_all(path)?;
    // An earlier attempt can have created a readable directory entry before
    // failing its parent sync. Reopen must synchronize that entry too, rather
    // than treating its existence as proof that the entire chain is durable.
    let canonical = fs::canonicalize(path)?;
    for directory in canonical
        .ancestors()
        .filter(|directory| directory.parent().is_some())
    {
        sync_parent(directory)?;
    }
    Ok(())
}

pub(super) fn sync_file_and_parent(path: &Path) -> Result<(), ArtifactOwnerHostError> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    sync_parent(path)
}

pub(super) fn sync_parent(path: &Path) -> Result<(), ArtifactOwnerHostError> {
    let parent = path.parent().ok_or(ArtifactOwnerHostError::PathBoundary)?;
    #[cfg(unix)]
    {
        let parent = if parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            parent
        };
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    }
    // Windows directory-entry durability has no qualified implementation here.
    // File sync remains supported, but it must not be described as equivalent
    // power-loss evidence for that platform.
    #[cfg(not(unix))]
    let _ = parent;
    Ok(())
}
