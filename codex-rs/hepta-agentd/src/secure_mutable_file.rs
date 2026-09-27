//! Race-resistant mutable-owner file opening for Agentd-owned host adapters.
//!
//! Mutable state is opened relative to an already opened canonical directory.
//! The final component is never followed, the descriptor is close-on-exec, and
//! descriptor identity is compared with the directory entry after opening.
//! Creation durability includes both file and parent-directory sync.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::path::Path;

use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MutableOwnerStorageIdentityV1 {
    pub device_id: u64,
    pub inode: u64,
    pub parent_device_id: u64,
    pub parent_inode: u64,
    /// Path binding only; target-host evidence must separately prove rollback
    /// and snapshot-domain independence.
    pub path_binding_digest: Digest32,
}

#[derive(Debug)]
pub enum SecureMutableFileErrorV1 {
    UnsupportedPlatform,
    InvalidDirectory,
    InvalidName,
    NotRegular,
    IdentityChanged,
    Io(std::io::ErrorKind),
}
impl fmt::Display for SecureMutableFileErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SecureMutableFileErrorV1 {}
impl From<std::io::Error> for SecureMutableFileErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

pub(crate) struct SecureMutableFileV1 {
    pub(crate) file: File,
    pub(crate) identity: MutableOwnerStorageIdentityV1,
    pub(crate) created: bool,
}

#[cfg(unix)]
pub(crate) fn open_or_create_private_mutable_file_v1(
    directory_path: &Path,
    name: &str,
) -> Result<SecureMutableFileV1, SecureMutableFileErrorV1> {
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::fs::MetadataExt;

    use rustix::fs::AtFlags;
    use rustix::fs::Mode;
    use rustix::fs::OFlags;

    if !directory_path.is_absolute() {
        return Err(SecureMutableFileErrorV1::InvalidDirectory);
    }
    if name.is_empty()
        || name == "."
        || name == ".."
        || name.as_bytes().contains(&b'/')
        || name.as_bytes().contains(&0)
    {
        return Err(SecureMutableFileErrorV1::InvalidName);
    }
    let canonical = directory_path
        .canonicalize()
        .map_err(SecureMutableFileErrorV1::from)?;
    if canonical != directory_path {
        return Err(SecureMutableFileErrorV1::InvalidDirectory);
    }

    let directory: File = rustix::fs::open(
        &canonical,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(|error| errno(error.raw_os_error()))?
    .into();
    let directory_metadata = directory.metadata()?;
    if !directory_metadata.is_dir() {
        return Err(SecureMutableFileErrorV1::InvalidDirectory);
    }

    let create_flags = OFlags::RDWR
        | OFlags::CREATE
        | OFlags::EXCL
        | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let (file, created): (File, bool) = match rustix::fs::openat(
        &directory,
        name,
        create_flags,
        Mode::RUSR | Mode::WUSR,
    ) {
        Ok(file) => (file.into(), true),
        Err(rustix::io::Errno::EXIST) => (
            rustix::fs::openat(
                &directory,
                name,
                OFlags::RDWR | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                Mode::RUSR | Mode::WUSR,
            )
            .map_err(|error| errno(error.raw_os_error()))?
            .into(),
            false,
        ),
        Err(error) => return Err(errno(error.raw_os_error())),
    };

    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(SecureMutableFileErrorV1::NotRegular);
    }
    let descriptor = rustix::fs::fstat(&file).map_err(|error| errno(error.raw_os_error()))?;
    let entry = rustix::fs::statat(&directory, name, AtFlags::SYMLINK_NOFOLLOW)
        .map_err(|error| errno(error.raw_os_error()))?;
    if descriptor.st_dev != entry.st_dev || descriptor.st_ino != entry.st_ino {
        return Err(SecureMutableFileErrorV1::IdentityChanged);
    }

    if created {
        file.sync_all()?;
        directory.sync_all()?;
    }

    let mut binding = b"hepta.agentd.mutable-owner-path.v1\0".to_vec();
    binding.extend_from_slice(canonical.as_os_str().as_bytes());
    binding.push(0);
    binding.extend_from_slice(name.as_bytes());
    Ok(SecureMutableFileV1 {
        file,
        identity: MutableOwnerStorageIdentityV1 {
            device_id: metadata.dev(),
            inode: metadata.ino(),
            parent_device_id: directory_metadata.dev(),
            parent_inode: directory_metadata.ino(),
            path_binding_digest: Digest32::of_bytes(&binding),
        },
        created,
    })
}

#[cfg(not(unix))]
pub(crate) fn open_or_create_private_mutable_file_v1(
    _directory_path: &Path,
    _name: &str,
) -> Result<SecureMutableFileV1, SecureMutableFileErrorV1> {
    Err(SecureMutableFileErrorV1::UnsupportedPlatform)
}

#[cfg(unix)]
fn errno(raw: i32) -> SecureMutableFileErrorV1 {
    SecureMutableFileErrorV1::Io(std::io::Error::from_raw_os_error(raw).kind())
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;

    #[test]
    fn relative_open_is_private_identity_checked_and_directory_durable() {
        let temp = tempfile::tempdir().expect("tempdir");
        let canonical = temp.path().canonicalize().expect("canonical temp");
        let opened = open_or_create_private_mutable_file_v1(&canonical, "owner.journal")
            .expect("secure create");
        assert!(opened.created);
        assert_ne!(opened.identity.inode, 0);
        assert!(!opened.identity.path_binding_digest.is_zero());
        let reopened = open_or_create_private_mutable_file_v1(&canonical, "owner.journal")
            .expect("secure reopen");
        assert!(!reopened.created);
        assert_eq!(opened.identity, reopened.identity);
    }

    #[test]
    fn final_component_symlink_is_rejected() {
        let temp = tempfile::tempdir().expect("tempdir");
        let canonical = temp.path().canonicalize().expect("canonical temp");
        std::fs::write(canonical.join("target"), b"target").expect("target");
        symlink("target", canonical.join("owner.journal")).expect("symlink");
        assert!(open_or_create_private_mutable_file_v1(&canonical, "owner.journal").is_err());
    }

    #[test]
    fn noncanonical_parent_and_path_names_are_rejected() {
        let temp = tempfile::tempdir().expect("tempdir");
        let canonical = temp.path().canonicalize().expect("canonical temp");
        assert!(open_or_create_private_mutable_file_v1(&canonical, "../escape").is_err());
        assert!(open_or_create_private_mutable_file_v1(&canonical, "a/b").is_err());
        assert!(
            open_or_create_private_mutable_file_v1(&canonical.join("."), "owner").is_err()
        );
    }
}
