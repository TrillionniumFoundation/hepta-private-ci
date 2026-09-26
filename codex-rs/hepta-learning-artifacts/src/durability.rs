//! Target-host durability primitives for the learning-artifact owner.
//!
//! Immutable file writers sync file contents. This module closes the remaining
//! containing-directory gap on qualified Unix targets and provides bounded,
//! host-authorized create/replace/remove helpers. It deliberately does not
//! claim `openat2(2)` semantics: safe Rust cannot bind every path component to
//! one dirfd without a platform adapter. The caller must still fence hostile
//! ancestor replacement.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use crate::storage::resolve_beneath_trusted_root;

const MAX_CONTROL_FILE_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DirectoryDurabilityProfileV1 {
    /// File and containing-directory `sync_all` are both required.
    UnixDirectorySync,
    /// The crate has no qualified directory durability primitive.
    Unsupported,
}

#[must_use]
pub const fn directory_durability_profile_v1() -> DirectoryDurabilityProfileV1 {
    #[cfg(unix)]
    {
        DirectoryDurabilityProfileV1::UnixDirectorySync
    }
    #[cfg(not(unix))]
    {
        DirectoryDurabilityProfileV1::Unsupported
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DirectoryDurabilityError {
    InvalidPath,
    PathBoundary,
    AlreadyExists,
    NotRegular,
    Capacity,
    Unsupported,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for DirectoryDurabilityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DirectoryDurabilityError {}

impl From<io::Error> for DirectoryDurabilityError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

/// An opened and canonicalized trusted root.
///
/// The retained directory handle makes the selected root inode explicit for
/// diagnostics and syncing. Relative operations still revalidate every existing
/// ancestor and therefore remain contingent on the host fencing concurrent
/// hostile replacement.
pub struct TrustedDirectoryCapabilityV1 {
    canonical_root: PathBuf,
    directory: File,
}

impl fmt::Debug for TrustedDirectoryCapabilityV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("TrustedDirectoryCapabilityV1")
            .field("canonical_root", &self.canonical_root)
            .finish_non_exhaustive()
    }
}

impl TrustedDirectoryCapabilityV1 {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, DirectoryDurabilityError> {
        let metadata = fs::symlink_metadata(root.as_ref())?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(DirectoryDurabilityError::PathBoundary);
        }
        let canonical_root = fs::canonicalize(root)?;
        let directory = File::open(&canonical_root)?;
        Ok(Self {
            canonical_root,
            directory,
        })
    }

    #[must_use]
    pub fn root(&self) -> &Path {
        &self.canonical_root
    }

    pub fn resolve(
        &self,
        relative: impl AsRef<Path>,
    ) -> Result<PathBuf, DirectoryDurabilityError> {
        resolve_beneath_trusted_root(&self.canonical_root, relative)
            .map_err(|_| DirectoryDurabilityError::PathBoundary)
    }

    pub fn sync(&self) -> Result<(), DirectoryDurabilityError> {
        sync_open_directory(&self.directory)
    }
}

#[cfg(unix)]
fn sync_open_directory(directory: &File) -> Result<(), DirectoryDurabilityError> {
    directory
        .sync_all()
        .map_err(|_| DirectoryDurabilityError::Indeterminate)
}

#[cfg(not(unix))]
fn sync_open_directory(_directory: &File) -> Result<(), DirectoryDurabilityError> {
    Err(DirectoryDurabilityError::Unsupported)
}

pub fn sync_directory(path: impl AsRef<Path>) -> Result<(), DirectoryDurabilityError> {
    let metadata = fs::symlink_metadata(path.as_ref())?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(DirectoryDurabilityError::PathBoundary);
    }
    let directory = File::open(path)?;
    sync_open_directory(&directory)
}

pub fn sync_parent_directory(path: impl AsRef<Path>) -> Result<(), DirectoryDurabilityError> {
    let parent = path
        .as_ref()
        .parent()
        .ok_or(DirectoryDurabilityError::InvalidPath)?;
    sync_directory(parent)
}

/// Sync every namespace mutated by one artifact publication, then the root.
///
/// Calling this after `LearningArtifactOwnerService::publish` closes the parent
/// directory persistence gap for payload, registry, witness, head and
/// transaction records on qualified Unix targets.
pub fn sync_artifact_owner_publication_directories(
    root: impl AsRef<Path>,
) -> Result<(), DirectoryDurabilityError> {
    let root = fs::canonicalize(root)?;
    for name in [
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "transactions",
        "writer",
    ] {
        sync_directory(root.join(name))?;
    }
    sync_directory(root)
}

fn validate_control_bytes(bytes: &[u8]) -> Result<(), DirectoryDurabilityError> {
    if bytes.is_empty() || bytes.len() > MAX_CONTROL_FILE_BYTES {
        return Err(DirectoryDurabilityError::Capacity);
    }
    Ok(())
}

fn open_new_private(path: &Path) -> Result<File, DirectoryDurabilityError> {
    let mut options = OpenOptions::new();
    options.write(true).read(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    options.open(path).map_err(|error| {
        if error.kind() == io::ErrorKind::AlreadyExists {
            DirectoryDurabilityError::AlreadyExists
        } else {
            error.into()
        }
    })
}

/// Create one bounded file and durably publish its directory entry.
pub fn durable_create_file_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
    bytes: &[u8],
) -> Result<PathBuf, DirectoryDurabilityError> {
    validate_control_bytes(bytes)?;
    let path = resolve_beneath_trusted_root(root, relative)
        .map_err(|_| DirectoryDurabilityError::PathBoundary)?;
    let mut file = open_new_private(&path)?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| DirectoryDurabilityError::Indeterminate)?;
    drop(file);
    sync_parent_directory(&path)?;
    Ok(path)
}

/// Replace one host-owned regular control file through a synced temporary file.
///
/// The caller must hold the product writer fence. Existing symlinks, directories
/// and special files are rejected. The temporary file is synced before rename,
/// and the containing directory is synced before success is returned.
pub fn durable_replace_file_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
    bytes: &[u8],
) -> Result<PathBuf, DirectoryDurabilityError> {
    validate_control_bytes(bytes)?;
    let path = resolve_beneath_trusted_root(root, relative)
        .map_err(|_| DirectoryDurabilityError::PathBoundary)?;
    if let Ok(metadata) = fs::symlink_metadata(&path)
        && (metadata.file_type().is_symlink() || !metadata.is_file())
    {
        return Err(DirectoryDurabilityError::NotRegular);
    }

    let file_name = path
        .file_name()
        .ok_or(DirectoryDurabilityError::InvalidPath)?
        .to_string_lossy();
    let digest = Digest32::of_bytes(bytes);
    let temporary = path.with_file_name(format!(
        ".{file_name}.hepta-replace-{}-{digest}",
        std::process::id()
    ));
    let _ = fs::remove_file(&temporary);
    let mut file = open_new_private(&temporary)?;
    let write_result = file
        .write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| DirectoryDurabilityError::Indeterminate);
    drop(file);
    if let Err(error) = write_result {
        let _ = fs::remove_file(&temporary);
        return Err(error);
    }

    if let Err(error) = fs::rename(&temporary, &path) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    sync_parent_directory(&path)?;
    Ok(path)
}

/// Remove one host-authorized regular file and durably publish the deletion.
pub fn durable_remove_file_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
) -> Result<(), DirectoryDurabilityError> {
    let path = resolve_beneath_trusted_root(root, relative)
        .map_err(|_| DirectoryDurabilityError::PathBoundary)?;
    let metadata = fs::symlink_metadata(&path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(DirectoryDurabilityError::NotRegular);
    }
    fs::remove_file(&path)?;
    sync_parent_directory(&path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static NEXT_ROOT: AtomicU64 = AtomicU64::new(1);

    fn root(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "hepta-artifact-durability-{label}-{}-{}",
            std::process::id(),
            NEXT_ROOT.fetch_add(1, Ordering::Relaxed)
        ))
    }

    #[cfg(unix)]
    #[test]
    fn create_replace_remove_syncs_directory_entries() {
        let root = root("lifecycle");
        fs::create_dir_all(&root).expect("create root");
        durable_create_file_beneath(&root, "anchor", b"one").expect("create");
        assert_eq!(fs::read(root.join("anchor")).expect("read"), b"one");
        durable_replace_file_beneath(&root, "anchor", b"two").expect("replace");
        assert_eq!(fs::read(root.join("anchor")).expect("read"), b"two");
        durable_remove_file_beneath(&root, "anchor").expect("remove");
        assert!(!root.join("anchor").exists());
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn trusted_directory_rejects_escape() {
        let root = root("escape");
        fs::create_dir_all(&root).expect("create root");
        let capability = TrustedDirectoryCapabilityV1::open(&root).expect("open");
        assert_eq!(
            capability.resolve("../outside"),
            Err(DirectoryDurabilityError::PathBoundary)
        );
        fs::remove_dir_all(root).expect("cleanup");
    }
}
