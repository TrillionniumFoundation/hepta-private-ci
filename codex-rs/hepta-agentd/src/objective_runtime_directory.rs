//! Private objective journal directory preparation and entry synchronization.
//!
//! Unix native opens reject final links and FIFO replacements before permission
//! changes or fsync. Existing owner, inode and namespace policies remain with
//! their callers; this is not a deadline for arbitrary filesystem I/O.

use std::path::Path;

use super::AgentdError;
use super::invalid;

#[cfg(unix)]
fn open_directory_handle(path: &Path) -> std::io::Result<std::fs::File> {
    use std::os::unix::fs::OpenOptionsExt;

    std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
}

#[cfg(unix)]
pub(super) fn sync_run_start_directory(path: &Path) -> Result<(), AgentdError> {
    open_directory_handle(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
pub(super) fn sync_run_start_directory(_path: &Path) -> Result<(), AgentdError> {
    // The selected non-Unix host profile must independently qualify directory-entry
    // durability. The journal file itself is synchronized before this boundary.
    Ok(())
}

pub(super) fn prepare_private_directory(path: &Path) -> Result<(), AgentdError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("objective run-start root has no parent"))?;
    if parent.canonicalize()? != parent {
        return Err(invalid("objective run-start parent must be canonical"));
    }
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if !metadata.is_dir() || metadata.file_type().is_symlink() => {
            return Err(invalid("objective run-start root must be a real directory"));
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            std::fs::create_dir(path)?;
        }
        Err(error) => return Err(error.into()),
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(invalid("objective run-start root must be a real directory"));
    }
    #[cfg(unix)]
    prepare_inspected_directory(path, parent, &metadata)?;
    Ok(())
}

#[cfg(unix)]
fn prepare_inspected_directory(
    path: &Path,
    parent: &Path,
    metadata: &std::fs::Metadata,
) -> Result<(), AgentdError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let directory = open_directory_handle(path)?;
    let opened = directory.metadata()?;
    if !opened.is_dir()
        || opened.dev() != metadata.dev()
        || opened.ino() != metadata.ino()
        || opened.uid() != std::fs::metadata(parent)?.uid()
    {
        return Err(invalid("objective run-start root changed while opening"));
    }
    // Change the verified directory handle, never a path that may have
    // become a symlink to another owner's directory before chmod.
    directory.set_permissions(std::fs::Permissions::from_mode(0o700))?;
    let after = std::fs::symlink_metadata(path)?;
    if !after.is_dir() || after.dev() != opened.dev() || after.ino() != opened.ino() {
        return Err(invalid(
            "objective run-start root changed during preparation",
        ));
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "objective_runtime_directory_tests.rs"]
mod tests;
