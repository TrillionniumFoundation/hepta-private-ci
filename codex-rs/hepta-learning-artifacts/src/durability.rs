//! Host-side durability primitives for learning-artifact owner state.
//!
//! The immutable artifact encoders deliberately stop at a synchronized file.
//! This module closes the next host boundary: final-component creation,
//! directory-entry synchronization, atomic replacement where the target OS
//! supplies the required semantics, and remove-plus-directory-sync. It does
//! not pretend that every filesystem or storage stack has equivalent power-loss
//! behavior; unsupported targets fail closed.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

static NEXT_TEMPORARY: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DirectoryDurabilityProfileV1 {
    /// File and containing-directory synchronization are both available.
    Strong,
    /// The target does not expose a supported directory fsync primitive.
    Unsupported,
}

#[derive(Debug)]
pub enum HostDurabilityError {
    InvalidPath,
    ExistingTarget,
    DirectorySyncUnsupported,
    Indeterminate(io::Error),
    Io(io::Error),
}

impl fmt::Display for HostDurabilityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidPath => formatter.write_str("invalid host durability path"),
            Self::ExistingTarget => formatter.write_str("durable target already exists"),
            Self::DirectorySyncUnsupported => {
                formatter.write_str("target platform has no qualified directory sync primitive")
            }
            Self::Indeterminate(error) => {
                write!(formatter, "indeterminate durable mutation: {error}")
            }
            Self::Io(error) => write!(formatter, "host durability I/O error: {error}"),
        }
    }
}

impl StdError for HostDurabilityError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Indeterminate(error) | Self::Io(error) => Some(error),
            Self::InvalidPath | Self::ExistingTarget | Self::DirectorySyncUnsupported => None,
        }
    }
}

impl From<io::Error> for HostDurabilityError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

#[must_use]
pub const fn directory_durability_profile_v1() -> DirectoryDurabilityProfileV1 {
    #[cfg(unix)]
    {
        DirectoryDurabilityProfileV1::Strong
    }
    #[cfg(not(unix))]
    {
        DirectoryDurabilityProfileV1::Unsupported
    }
}

/// Synchronize directory entries after create, rename or removal.
///
/// Unix targets use an opened directory handle. Other targets fail closed until
/// they receive target-specific qualification instead of silently treating a
/// file `sync_all` as equivalent to durable namespace publication.
pub fn sync_directory_v1(path: impl AsRef<Path>) -> Result<(), HostDurabilityError> {
    let path = path.as_ref();
    #[cfg(unix)]
    {
        let metadata = fs::symlink_metadata(path)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(HostDurabilityError::InvalidPath);
        }
        File::open(path)
            .and_then(|directory| directory.sync_all())
            .map_err(HostDurabilityError::Io)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Err(HostDurabilityError::DirectorySyncUnsupported)
    }
}

/// Create, write and synchronize one new file, then synchronize its parent.
/// Existing paths, including symlinks and empty files, are never adopted.
pub fn durable_write_new_v1(
    path: impl AsRef<Path>,
    bytes: &[u8],
) -> Result<(), HostDurabilityError> {
    let path = path.as_ref();
    validate_final_path(path)?;
    let parent = path.parent().ok_or(HostDurabilityError::InvalidPath)?;
    validate_real_directory(parent)?;

    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut file = match options.open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            return Err(HostDurabilityError::ExistingTarget);
        }
        Err(error) => return Err(HostDurabilityError::Io(error)),
    };
    if let Err(error) = file.write_all(bytes).and_then(|()| file.sync_all()) {
        return Err(HostDurabilityError::Indeterminate(error));
    }
    drop(file);
    sync_directory_v1(parent).map_err(|error| match error {
        HostDurabilityError::Io(error) => HostDurabilityError::Indeterminate(error),
        other => other,
    })
}

/// Atomically replace a small host control file on qualified Unix targets.
///
/// Artifact payloads and registries remain create-only and must not use this
/// operation. It exists for mutable host control metadata such as an authz
/// generation pointer. A failure after the rename is indeterminate and must be
/// reconciled by reading the final path.
pub fn durable_replace_control_file_v1(
    path: impl AsRef<Path>,
    bytes: &[u8],
) -> Result<(), HostDurabilityError> {
    let path = path.as_ref();
    validate_final_path(path)?;
    let parent = path.parent().ok_or(HostDurabilityError::InvalidPath)?;
    validate_real_directory(parent)?;

    #[cfg(not(unix))]
    {
        let _ = bytes;
        return Err(HostDurabilityError::DirectorySyncUnsupported);
    }

    #[cfg(unix)]
    {
        let temporary = temporary_path(
            parent,
            path.file_name().ok_or(HostDurabilityError::InvalidPath)?,
        );
        let result = (|| {
            let mut options = OpenOptions::new();
            options.write(true).create_new(true).mode(0o600);
            let mut file = options.open(&temporary)?;
            file.write_all(bytes)?;
            file.sync_all()?;
            drop(file);
            fs::rename(&temporary, path)?;
            sync_directory_v1(parent).map_err(|error| match error {
                HostDurabilityError::Io(error) => HostDurabilityError::Indeterminate(error),
                other => other,
            })?;
            Ok(())
        })();
        if temporary.exists() {
            let _ = fs::remove_file(&temporary);
        }
        result.map_err(|error: HostDurabilityError| match error {
            HostDurabilityError::Io(error) => HostDurabilityError::Indeterminate(error),
            other => other,
        })
    }
}

/// Remove one regular file and synchronize the containing directory.
pub fn durable_remove_file_v1(path: impl AsRef<Path>) -> Result<(), HostDurabilityError> {
    let path = path.as_ref();
    validate_final_path(path)?;
    let parent = path.parent().ok_or(HostDurabilityError::InvalidPath)?;
    validate_real_directory(parent)?;
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(HostDurabilityError::InvalidPath);
    }
    fs::remove_file(path)?;
    sync_directory_v1(parent).map_err(|error| match error {
        HostDurabilityError::Io(error) => HostDurabilityError::Indeterminate(error),
        other => other,
    })
}

/// Provision or validate the private owner root.
///
/// On Unix the root is created as `0700` and any group/world permission is
/// rejected. The ownership identity itself remains a deployment responsibility
/// because this crate forbids unsafe platform calls.
pub fn provision_private_root_v1(path: impl AsRef<Path>) -> Result<PathBuf, HostDurabilityError> {
    let path = path.as_ref();
    if path.as_os_str().is_empty() {
        return Err(HostDurabilityError::InvalidPath);
    }
    if !path.exists() {
        let mut builder = fs::DirBuilder::new();
        builder.recursive(true);
        #[cfg(unix)]
        builder.mode(0o700);
        builder.create(path)?;
        if let Some(parent) = path.parent()
            && parent.exists()
        {
            sync_directory_v1(parent)?;
        }
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(HostDurabilityError::InvalidPath);
    }
    #[cfg(unix)]
    {
        let mode = metadata.permissions().mode() & 0o777;
        if mode & 0o077 != 0 {
            return Err(HostDurabilityError::InvalidPath);
        }
    }
    fs::canonicalize(path).map_err(HostDurabilityError::Io)
}

fn validate_final_path(path: &Path) -> Result<(), HostDurabilityError> {
    if path.file_name().is_none()
        || path
            .components()
            .any(|component| matches!(component, Component::ParentDir | Component::CurDir))
    {
        return Err(HostDurabilityError::InvalidPath);
    }
    Ok(())
}

fn validate_real_directory(path: &Path) -> Result<(), HostDurabilityError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(HostDurabilityError::InvalidPath);
    }
    Ok(())
}

#[cfg(unix)]
fn temporary_path(parent: &Path, final_name: &std::ffi::OsStr) -> PathBuf {
    let sequence = NEXT_TEMPORARY.fetch_add(1, Ordering::Relaxed);
    let time = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let name = format!(
        ".{}.tmp-{}-{time}-{sequence}",
        final_name.to_string_lossy(),
        std::process::id()
    );
    parent.join(name)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicU64;

    static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(1);

    fn test_root() -> PathBuf {
        let id = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!(
            "hepta-artifact-durability-{}-{id}",
            std::process::id()
        ))
    }

    #[test]
    fn create_replace_remove_is_directory_synchronized_or_explicitly_unsupported() {
        let root = test_root();
        let provisioned = provision_private_root_v1(&root).expect("provision root");
        let path = provisioned.join("control");
        match directory_durability_profile_v1() {
            DirectoryDurabilityProfileV1::Strong => {
                durable_write_new_v1(&path, b"one").expect("durable create");
                assert_eq!(fs::read(&path).expect("read create"), b"one");
                durable_replace_control_file_v1(&path, b"two").expect("durable replace");
                assert_eq!(fs::read(&path).expect("read replace"), b"two");
                durable_remove_file_v1(&path).expect("durable remove");
                assert!(!path.exists());
            }
            DirectoryDurabilityProfileV1::Unsupported => {
                assert!(matches!(
                    durable_write_new_v1(&path, b"one"),
                    Err(HostDurabilityError::DirectorySyncUnsupported)
                ));
            }
        }
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn existing_targets_and_symlinks_are_never_adopted() {
        let root = test_root();
        let provisioned = provision_private_root_v1(&root).expect("provision root");
        let path = provisioned.join("control");
        if directory_durability_profile_v1() == DirectoryDurabilityProfileV1::Strong {
            durable_write_new_v1(&path, b"one").expect("durable create");
            assert!(matches!(
                durable_write_new_v1(&path, b"two"),
                Err(HostDurabilityError::ExistingTarget)
            ));
        }
        let _ = fs::remove_dir_all(root);
    }
}
