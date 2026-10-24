//! Original platform I/O boundary; parsing and journal formats stay in Store.

use super::FinalUseError;
use std::fs::File;
use std::io::Read;
use std::path::Path;

pub(super) fn read_bounded(
    directory: &File,
    name: &str,
    maximum: usize,
) -> Result<Vec<u8>, FinalUseError> {
    let mut bytes = Vec::new();
    open_private(directory, name, Access::Read)?
        .take(u64::try_from(maximum).map_err(|_| FinalUseError::InvalidTrust)? + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| FinalUseError::Unavailable)?;
    if bytes.len() > maximum {
        return Err(FinalUseError::InvalidTrust);
    }
    Ok(bytes)
}

pub(super) enum Access {
    Read,
    Write,
    Create,
}

#[cfg(unix)]
pub(super) fn prepare_directory(root: &Path) -> Result<File, FinalUseError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(FinalUseError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| FinalUseError::UnsafeStateDirectory)?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| FinalUseError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(FinalUseError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(unix)]
pub(super) fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, FinalUseError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;
    use std::os::unix::fs::MetadataExt;
    let flags = match access {
        Access::Read => OFlags::RDONLY,
        Access::Write => OFlags::RDWR,
        Access::Create => OFlags::RDWR | OFlags::CREATE,
    } | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
        .map_err(|_| FinalUseError::Unavailable)?
        .into();
    let metadata = file.metadata().map_err(|_| FinalUseError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(FinalUseError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(not(unix))]
pub(super) fn prepare_directory(_root: &Path) -> Result<File, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}
#[cfg(not(unix))]
pub(super) fn open_private(
    _directory: &File,
    _name: &str,
    _access: Access,
) -> Result<File, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}

#[cfg(unix)]
pub(super) fn entry_exists(directory: &File, name: &str) -> Result<bool, FinalUseError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(FinalUseError::Unavailable),
    }
}

#[cfg(unix)]
pub(super) fn replace_state(directory: &File, _stage: &File) -> Result<(), FinalUseError> {
    rustix::fs::renameat(directory, "authority.next", directory, "authority.json")
        .map_err(|_| FinalUseError::Unavailable)
}

#[cfg(unix)]
pub(super) fn replace_claims(directory: &File, _stage: &File) -> Result<(), FinalUseError> {
    rustix::fs::renameat(
        directory,
        "authority.claims.next",
        directory,
        "authority.claims",
    )
    .map_err(|_| FinalUseError::Unavailable)
}

#[cfg(not(unix))]
pub(super) fn entry_exists(_directory: &File, _name: &str) -> Result<bool, FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}
#[cfg(windows)]
pub(super) fn replace_state(directory: &File, stage: &File) -> Result<(), FinalUseError> {
    crate::replace_synced_state_stage(directory, stage, "authority.json")
        .map_err(|_| FinalUseError::Unavailable)
}
#[cfg(not(any(unix, windows)))]
pub(super) fn replace_state(_directory: &File, _stage: &File) -> Result<(), FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}
#[cfg(windows)]
pub(super) fn replace_claims(directory: &File, stage: &File) -> Result<(), FinalUseError> {
    crate::replace_synced_state_stage(directory, stage, "authority.claims")
        .map_err(|_| FinalUseError::Unavailable)
}
#[cfg(not(any(unix, windows)))]
pub(super) fn replace_claims(_directory: &File, _stage: &File) -> Result<(), FinalUseError> {
    Err(FinalUseError::UnsafeStateDirectory)
}
