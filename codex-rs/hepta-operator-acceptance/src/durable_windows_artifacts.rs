//! Windows adapters to the single canonical retained private-artifact backend.

use super::MAX_ARTIFACT_BYTES;
use super::SidecarLock;
use super::invalid;
use crate::AcceptanceError;
use codex_utils_path::PrivateFile;
use codex_utils_path::RetainedPrivateDirectory;
use sha2::Digest;
use sha2::Sha256;
use std::ffi::OsStr;
use std::path::Path;
use std::path::PathBuf;

pub(super) fn canonical_file(path: &Path, label: &str) -> Result<PathBuf, AcceptanceError> {
    if !path.is_absolute() {
        return Err(invalid(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(invalid(format!(
            "{label} must already be canonical and contain no symlink components"
        )));
    }
    PrivateFile::open_existing(&canonical)?.verify()?;
    Ok(canonical)
}

pub(super) fn verify_directory(path: &Path, _label: &str) -> Result<(), AcceptanceError> {
    PrivateFile::open_directory(path)?.verify()?;
    Ok(())
}

pub(super) fn read(path: &Path, maximum: usize) -> Result<Vec<u8>, AcceptanceError> {
    Ok(PrivateFile::open_existing(path)?.read_bounded(maximum)?)
}

pub(super) fn hash(path: &Path) -> Result<(String, u64), AcceptanceError> {
    let file = PrivateFile::open_existing(path)?;
    let mut digest = Sha256::new();
    let length = file.read_chunks(MAX_ARTIFACT_BYTES, |chunk| {
        digest.update(chunk);
        Ok(())
    })?;
    Ok((format!("{:x}", digest.finalize()), length))
}

pub(super) fn write_new(path: &Path, bytes: &[u8]) -> Result<(), AcceptanceError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("sidecar artifact has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| invalid("sidecar artifact has no ordinary name"))?;
    RetainedPrivateDirectory::open_existing(parent)?
        .write_new_child(name, bytes)?
        .verify()?;
    Ok(())
}

pub(super) fn atomic_replace(
    path: &Path,
    temporary: &Path,
    bytes: &[u8],
) -> Result<(), AcceptanceError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("sidecar artifact has no parent"))?;
    if temporary.parent() != Some(parent) {
        return Err(invalid(
            "atomic sidecar temporary path must be a distinct sibling",
        ));
    }
    let name = path
        .file_name()
        .ok_or_else(|| invalid("sidecar artifact has no ordinary name"))?;
    let temporary = temporary
        .file_name()
        .ok_or_else(|| invalid("temporary has no ordinary name"))?;
    RetainedPrivateDirectory::open_existing(parent)?
        .atomic_replace_child(name, temporary, bytes)?
        .verify()?;
    Ok(())
}

pub(super) fn sidecar_lock(root: &Path, create: bool) -> Result<SidecarLock, AcceptanceError> {
    let directory = RetainedPrivateDirectory::open_existing(root)?;
    let name = OsStr::new(".operator-acceptance.lock");
    let file = if create {
        directory.create_or_lock_child(name)
    } else {
        directory.lock_existing_child(name)
    }
    .map_err(|error| {
        if !create && error.kind() == std::io::ErrorKind::NotFound {
            invalid("read-only receipt verification requires the existing sidecar lock")
        } else {
            error.into()
        }
    })?;
    Ok(SidecarLock { _file: file })
}
