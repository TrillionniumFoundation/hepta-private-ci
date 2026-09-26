//! Durable file opening helpers for Agentd-owned journals and descriptors.
//!
//! Unix opens use `O_NOFOLLOW | O_CLOEXEC`, compare pre-open and post-open
//! device/inode identity, and fsync the parent directory after create. These
//! checks reduce pathname substitution risk; deployment evidence must still
//! prove that files advertised as independent occupy independent rollback domains.

#[path = "self_iteration_coordinator.rs"]
pub(crate) mod self_iteration_coordinator;
#[path = "self_iteration_service.rs"]
pub(crate) mod self_iteration_service;

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;

use codex_hepta_types::Digest32;

use crate::AgentdError;

#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DurableFileIdentityV1 {
    pub device: u64,
    pub inode: u64,
    pub canonical_parent_digest: Digest32,
}

impl DurableFileIdentityV1 {
    #[must_use]
    pub fn semantic_digest(self) -> Digest32 {
        let mut bytes = b"hepta.agentd.durable-file-identity.v1\0".to_vec();
        bytes.extend_from_slice(&self.device.to_be_bytes());
        bytes.extend_from_slice(&self.inode.to_be_bytes());
        bytes.extend_from_slice(self.canonical_parent_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

pub(crate) fn open_existing_rw_nofollow(
    path: &Path,
    label: &str,
) -> Result<(File, DurableFileIdentityV1), AgentdError> {
    require_absolute(path, label)?;
    let before = std::fs::symlink_metadata(path)?;
    if before.file_type().is_symlink() || !before.is_file() {
        return invalid(&format!("{label} must be a regular non-symlink file"));
    }
    let parent_digest = canonical_parent_digest(path, label)?;
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    apply_secure_flags(&mut options);
    let file = options.open(path)?;
    let after = file.metadata()?;
    if !after.is_file() || !same_identity(&before, &after) {
        return invalid(&format!("{label} changed while it was opened"));
    }
    Ok((file, identity(&after, parent_digest)))
}

pub(crate) fn create_new_rw_nofollow(
    path: &Path,
    label: &str,
) -> Result<(File, DurableFileIdentityV1), AgentdError> {
    require_absolute(path, label)?;
    let parent_digest = canonical_parent_digest(path, label)?;
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    apply_secure_flags(&mut options);
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return invalid(&format!("{label} is not a regular file after create"));
    }
    file.sync_all()?;
    sync_parent_directory(path, label)?;
    Ok((file, identity(&metadata, parent_digest)))
}

/// Open an existing file or atomically create a new one. A concurrent creator is
/// handled by retrying through the existing-file path, never by following a link.
pub(crate) fn open_or_create_rw_nofollow(
    path: &Path,
    label: &str,
) -> Result<(File, DurableFileIdentityV1, bool), AgentdError> {
    match create_new_rw_nofollow(path, label) {
        Ok((file, identity)) => Ok((file, identity, true)),
        Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            open_existing_rw_nofollow(path, label).map(|(file, identity)| (file, identity, false))
        }
        Err(error) => Err(error),
    }
}

pub(crate) fn sync_parent_directory(path: &Path, label: &str) -> Result<(), AgentdError> {
    let parent = path
        .parent()
        .ok_or_else(|| AgentdError::Invalid(format!("{label} has no parent directory")))?;
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    options.custom_flags(libc::O_DIRECTORY | libc::O_CLOEXEC | libc::O_NOFOLLOW);
    let directory = options.open(parent)?;
    directory.sync_all()?;
    Ok(())
}

pub(crate) fn require_distinct_file_identity(
    left: DurableFileIdentityV1,
    right: DurableFileIdentityV1,
    label: &str,
) -> Result<(), AgentdError> {
    if left.device == right.device && left.inode == right.inode {
        return invalid(&format!("{label} resolve to the same file identity"));
    }
    Ok(())
}

fn require_absolute(path: &Path, label: &str) -> Result<(), AgentdError> {
    if !path.is_absolute() {
        return invalid(&format!("{label} path must be absolute"));
    }
    Ok(())
}

fn canonical_parent_digest(path: &Path, label: &str) -> Result<Digest32, AgentdError> {
    let parent = path
        .parent()
        .ok_or_else(|| AgentdError::Invalid(format!("{label} has no parent directory")))?;
    let canonical = parent.canonicalize()?;
    if parent != canonical {
        return invalid(&format!("{label} parent directory must be canonical"));
    }
    let raw = canonical.as_os_str().as_encoded_bytes();
    Ok(Digest32::of_bytes(raw))
}

fn apply_secure_flags(options: &mut OpenOptions) {
    #[cfg(unix)]
    options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
}

#[cfg(unix)]
fn same_identity(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    before.dev() == after.dev() && before.ino() == after.ino()
}

#[cfg(not(unix))]
fn same_identity(_before: &std::fs::Metadata, _after: &std::fs::Metadata) -> bool {
    true
}

#[cfg(unix)]
fn identity(metadata: &std::fs::Metadata, parent: Digest32) -> DurableFileIdentityV1 {
    DurableFileIdentityV1 {
        device: metadata.dev(),
        inode: metadata.ino(),
        canonical_parent_digest: parent,
    }
}

#[cfg(not(unix))]
fn identity(_metadata: &std::fs::Metadata, parent: Digest32) -> DurableFileIdentityV1 {
    DurableFileIdentityV1 {
        device: 0,
        inode: 0,
        canonical_parent_digest: parent,
    }
}

fn invalid<T>(message: &str) -> Result<T, AgentdError> {
    Err(AgentdError::Invalid(message.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn create_sync_and_reopen_preserve_identity() {
        let directory = tempfile::tempdir().expect("tempdir");
        let canonical = directory.path().canonicalize().expect("canonical");
        let path = canonical.join("journal");
        let (file, created, was_created) =
            open_or_create_rw_nofollow(&path, "journal").expect("create");
        assert!(was_created);
        drop(file);
        let (_, reopened, was_created) =
            open_or_create_rw_nofollow(&path, "journal").expect("reopen");
        assert!(!was_created);
        assert_eq!(created, reopened);
    }

    #[cfg(unix)]
    #[test]
    fn symlink_is_never_followed() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().expect("tempdir");
        let canonical = directory.path().canonicalize().expect("canonical");
        let target = canonical.join("target");
        std::fs::write(&target, b"target").expect("write");
        let link = canonical.join("link");
        symlink(&target, &link).expect("symlink");
        assert!(open_existing_rw_nofollow(&link, "link").is_err());
    }
}
