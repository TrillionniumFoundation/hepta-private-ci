//! The storage codec synchronizes file bytes. The named host also owns parent
//! directory durability on Unix, including newly created directory chains.
use super::ArtifactOwnerHostError;
use std::fs;
use std::fs::File;
#[cfg(windows)]
use std::fs::OpenOptions;
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
    open_file_for_sync(path)
        .and_then(|file| file.sync_all())
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    sync_parent(path)
}

#[cfg(windows)]
fn open_file_for_sync(path: &Path) -> std::io::Result<File> {
    // Windows implements File::sync_all with FlushFileBuffers, which rejects
    // a separately opened read-only handle. Reopen the owner-controlled file
    // with write access so the durability barrier is real; any ACL or sharing
    // failure still maps to Indeterminate at the caller.
    OpenOptions::new().read(true).write(true).open(path)
}

#[cfg(not(windows))]
fn open_file_for_sync(path: &Path) -> std::io::Result<File> {
    File::open(path)
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
