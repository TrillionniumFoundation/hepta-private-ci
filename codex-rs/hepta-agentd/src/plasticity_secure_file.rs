//! Hardened mutable-file opening for Agentd-owned plasticity journals.
//!
//! This closes the final-component symlink and check/open race on Unix by opening
//! with `O_NOFOLLOW | O_CLOEXEC`, then validating the opened file with `fstat`
//! metadata and comparing it to the path identity. New files are mode 0600 and the
//! parent directory is synced after creation. Physical rollback-domain independence
//! remains a target-host qualification fact; it cannot be inferred from path names.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::path::Path;

#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityFileIdentityV1 {
    pub device: u64,
    pub inode: u64,
}

#[derive(Debug)]
pub enum PlasticitySecureFileErrorV1 {
    RelativePath,
    MissingParent,
    NonCanonicalParent,
    NotRegular,
    Symlink,
    IdentityChanged,
    AliasedMutableFiles,
    Io(io::ErrorKind),
}

impl std::fmt::Display for PlasticitySecureFileErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for PlasticitySecureFileErrorV1 {}
impl From<io::Error> for PlasticitySecureFileErrorV1 {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

pub struct OpenedPlasticityFileV1 {
    pub file: File,
    pub identity: PlasticityFileIdentityV1,
    pub created: bool,
}

pub fn open_or_create_plasticity_file_v1(
    path: &Path,
) -> Result<OpenedPlasticityFileV1, PlasticitySecureFileErrorV1> {
    match open_existing_plasticity_file_v1(path) {
        Ok(opened) => Ok(opened),
        Err(PlasticitySecureFileErrorV1::Io(io::ErrorKind::NotFound)) => {
            match create_new_plasticity_file_v1(path) {
                Ok(opened) => Ok(opened),
                Err(PlasticitySecureFileErrorV1::Io(io::ErrorKind::AlreadyExists)) => {
                    open_existing_plasticity_file_v1(path)
                }
                Err(error) => Err(error),
            }
        }
        Err(error) => Err(error),
    }
}

pub fn open_existing_plasticity_file_v1(
    path: &Path,
) -> Result<OpenedPlasticityFileV1, PlasticitySecureFileErrorV1> {
    validate_absolute_path(path)?;
    let path_metadata = std::fs::symlink_metadata(path)?;
    if path_metadata.file_type().is_symlink() {
        return Err(PlasticitySecureFileErrorV1::Symlink);
    }
    if !path_metadata.is_file() {
        return Err(PlasticitySecureFileErrorV1::NotRegular);
    }

    let mut options = OpenOptions::new();
    options.read(true).write(true);
    apply_unix_open_hardening(&mut options, false);
    let file = options.open(path)?;
    let opened_metadata = file.metadata()?;
    if !opened_metadata.is_file() {
        return Err(PlasticitySecureFileErrorV1::NotRegular);
    }
    let path_identity = metadata_identity(&path_metadata, path)?;
    let opened_identity = metadata_identity(&opened_metadata, path)?;
    if path_identity != opened_identity {
        return Err(PlasticitySecureFileErrorV1::IdentityChanged);
    }
    Ok(OpenedPlasticityFileV1 {
        file,
        identity: opened_identity,
        created: false,
    })
}

pub fn create_new_plasticity_file_v1(
    path: &Path,
) -> Result<OpenedPlasticityFileV1, PlasticitySecureFileErrorV1> {
    validate_absolute_path(path)?;
    let parent = path
        .parent()
        .ok_or(PlasticitySecureFileErrorV1::MissingParent)?;
    let canonical_parent = parent.canonicalize()?;
    if canonical_parent != parent {
        return Err(PlasticitySecureFileErrorV1::NonCanonicalParent);
    }

    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    apply_unix_open_hardening(&mut options, true);
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(PlasticitySecureFileErrorV1::NotRegular);
    }
    file.sync_all()?;
    sync_parent_directory_v1(path)?;
    Ok(OpenedPlasticityFileV1 {
        identity: metadata_identity(&metadata, path)?,
        file,
        created: true,
    })
}

pub fn sync_parent_directory_v1(
    path: &Path,
) -> Result<(), PlasticitySecureFileErrorV1> {
    let parent = path
        .parent()
        .ok_or(PlasticitySecureFileErrorV1::MissingParent)?;
    File::open(parent)?.sync_all()?;
    Ok(())
}

pub fn require_distinct_plasticity_files_v1(
    left: PlasticityFileIdentityV1,
    right: PlasticityFileIdentityV1,
) -> Result<(), PlasticitySecureFileErrorV1> {
    if left == right {
        return Err(PlasticitySecureFileErrorV1::AliasedMutableFiles);
    }
    Ok(())
}

fn validate_absolute_path(path: &Path) -> Result<(), PlasticitySecureFileErrorV1> {
    if !path.is_absolute() {
        return Err(PlasticitySecureFileErrorV1::RelativePath);
    }
    Ok(())
}

#[cfg(unix)]
fn apply_unix_open_hardening(options: &mut OpenOptions, create: bool) {
    options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    if create {
        options.mode(0o600);
    }
}

#[cfg(not(unix))]
fn apply_unix_open_hardening(_options: &mut OpenOptions, _create: bool) {}

#[cfg(unix)]
fn metadata_identity(
    metadata: &std::fs::Metadata,
    _path: &Path,
) -> Result<PlasticityFileIdentityV1, PlasticitySecureFileErrorV1> {
    Ok(PlasticityFileIdentityV1 {
        device: metadata.dev(),
        inode: metadata.ino(),
    })
}

#[cfg(not(unix))]
fn metadata_identity(
    _metadata: &std::fs::Metadata,
    path: &Path,
) -> Result<PlasticityFileIdentityV1, PlasticitySecureFileErrorV1> {
    use std::hash::Hash;
    use std::hash::Hasher;
    let canonical = path.canonicalize()?;
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    canonical.hash(&mut hasher);
    Ok(PlasticityFileIdentityV1 {
        device: 0,
        inode: hasher.finish(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn create_sync_reopen_and_identity_are_stable() {
        let directory = tempfile::tempdir().expect("tempdir");
        let parent = directory.path().canonicalize().expect("canonical parent");
        let path = parent.join("terminal.journal");
        let created = open_or_create_plasticity_file_v1(&path).expect("create");
        assert!(created.created);
        let identity = created.identity;
        drop(created.file);
        let reopened = open_or_create_plasticity_file_v1(&path).expect("reopen");
        assert!(!reopened.created);
        assert_eq!(identity, reopened.identity);
    }

    #[cfg(unix)]
    #[test]
    fn final_symlink_and_hardlink_alias_fail_closed() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().expect("tempdir");
        let parent = directory.path().canonicalize().expect("canonical parent");
        let left = parent.join("left");
        let right = parent.join("right");
        std::fs::write(&left, b"left").expect("left");
        symlink(&left, &right).expect("symlink");
        assert!(matches!(
            open_existing_plasticity_file_v1(&right),
            Err(PlasticitySecureFileErrorV1::Symlink)
                | Err(PlasticitySecureFileErrorV1::Io(io::ErrorKind::TooManyLinks))
        ));

        std::fs::remove_file(&right).expect("remove symlink");
        std::fs::hard_link(&left, &right).expect("hardlink");
        let left = open_existing_plasticity_file_v1(&left).expect("open left");
        let right = open_existing_plasticity_file_v1(&right).expect("open right");
        assert!(matches!(
            require_distinct_plasticity_files_v1(left.identity, right.identity),
            Err(PlasticitySecureFileErrorV1::AliasedMutableFiles)
        ));
    }
}
