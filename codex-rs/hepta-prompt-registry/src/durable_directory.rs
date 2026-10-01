//! Original owner-directory and regular-file guards, including its actual parent
//! durability fence. These functions issue no independent recovery authority.

use super::Access;
use super::DurableRegistryError;
use super::OpenPolicy;
use super::map_precommit_io;
use std::fs::File;
use std::path::Path;

#[cfg(unix)]
pub(super) fn prepare_directory(root: &Path) -> Result<File, DurableRegistryError> {
    prepare_directory_with_policy(root, OpenPolicy::BootstrapAllowed)
}

#[cfg(unix)]
pub(super) fn prepare_directory_with_policy(
    root: &Path,
    policy: OpenPolicy,
) -> Result<File, DurableRegistryError> {
    prepare_directory_with_parent_sync(root, policy, File::sync_all)
}

#[cfg(unix)]
pub(super) fn prepare_directory_with_parent_sync(
    root: &Path,
    policy: OpenPolicy,
    sync_parent: impl FnOnce(&File) -> std::io::Result<()>,
) -> Result<File, DurableRegistryError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    if policy == OpenPolicy::BootstrapAllowed {
        match std::fs::DirBuilder::new().mode(0o700).create(root) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(_) => return Err(DurableRegistryError::Unavailable),
        }
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|error| {
        if policy == OpenPolicy::ExistingStateRequired && error == rustix::io::Errno::NOENT {
            DurableRegistryError::RecoveryStateMissing
        } else {
            DurableRegistryError::UnsafeStateDirectory
        }
    })?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| DurableRegistryError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(DurableRegistryError::UnsafeStateDirectory);
    }
    // A failed first parent sync leaves a directory behind. Repeat this fence
    // for existing directories too, so a successful retry cannot skip making
    // the owner directory's name durable before any selected publication.
    // Resolve the actual parent from the opened owner, not its spelling. A
    // relative "." or a path ending in ".." can otherwise sync the owner or a
    // child while leaving the owner's entry in its real parent unfenced.
    let parent: File = rustix::fs::openat(
        &directory,
        "..",
        rustix::fs::OFlags::RDONLY | rustix::fs::OFlags::DIRECTORY | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(std::io::Error::from)
    .map_err(map_precommit_io)?
    .into();
    sync_parent(&parent).map_err(map_precommit_io)?;
    Ok(directory)
}

#[cfg(not(unix))]
pub(super) fn prepare_directory(_root: &Path) -> Result<File, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
pub(super) fn prepare_directory_with_policy(
    _root: &Path,
    _policy: OpenPolicy,
) -> Result<File, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}

#[cfg(unix)]
pub(super) fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, DurableRegistryError> {
    use std::os::unix::fs::MetadataExt;

    let flags = match access {
        Access::Read => rustix::fs::OFlags::RDONLY,
        Access::Create => rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE,
        Access::CreateNew => {
            rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE | rustix::fs::OFlags::EXCL
        }
    } | rustix::fs::OFlags::NOFOLLOW
        | rustix::fs::OFlags::NONBLOCK
        | rustix::fs::OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(
        directory,
        name,
        flags,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .map_err(|_| DurableRegistryError::Unavailable)?
    .into();
    let metadata = file
        .metadata()
        .map_err(|_| DurableRegistryError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(DurableRegistryError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(not(unix))]
pub(super) fn open_private(
    _directory: &File,
    _name: &str,
    _access: Access,
) -> Result<File, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}
