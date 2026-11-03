//! Descriptor-retaining private-state primitives for the Linux native recovery adapter.

use super::*;
use rustix::fs::{Mode, OFlags};
use std::fs::File;
use std::os::unix::fs::MetadataExt;

pub(super) struct Lock {
    pub(super) file: File,
    pub(super) directory: File,
}
impl Lock {
    pub(super) fn verify(&self) -> Result<()> {
        verify_named_file(&self.directory, ".owner-lock", &self.file)
    }
}
impl Drop for Lock {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

pub(super) fn verify_named_file(directory: &File, name: &str, file: &File) -> Result<()> {
    verify_file(file)?;
    let retained = file.metadata().map_err(|_| storage_error())?;
    let current = rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW)
        .map_err(|_| storage_error())?;
    if i128::from(retained.dev()) != i128::from(current.st_dev)
        || i128::from(retained.ino()) != i128::from(current.st_ino)
    {
        return Err(storage_error());
    }
    Ok(())
}

pub(super) fn open_private_root(path: &Path) -> Result<File> {
    use std::path::Component;
    if !path.is_absolute() {
        return Err(storage_error());
    }
    let mut current = File::open("/").map_err(|_| storage_error())?;
    for component in path.components() {
        match component {
            Component::RootDir => continue,
            Component::Normal(name) => {
                let fd = rustix::fs::openat(
                    &current,
                    name,
                    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                    Mode::empty(),
                )
                .map_err(|_| storage_error())?;
                current = File::from(fd);
            }
            _ => return Err(storage_error()),
        }
    }
    let metadata = current.metadata().map_err(|_| storage_error())?;
    if metadata.uid() != rustix::process::geteuid().as_raw() || metadata.mode() & 0o077 != 0 {
        return Err(storage_error());
    }
    // macOS requires its own ACL verification, not only POSIX mode bits.
    #[cfg(target_os = "macos")]
    {
        return Err(storage_error());
    }
    #[cfg(not(target_os = "macos"))]
    Ok(current)
}
pub(super) fn verify_file(file: &File) -> Result<()> {
    let metadata = file.metadata().map_err(|_| storage_error())?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
        || metadata.mode() & 0o077 != 0
    {
        return Err(storage_error());
    }
    Ok(())
}
pub(super) fn open_file(directory: &File, name: &str, create: bool) -> Result<File> {
    let flags = OFlags::RDWR
        | OFlags::NOFOLLOW
        | OFlags::CLOEXEC
        | OFlags::NONBLOCK
        | if create {
            OFlags::CREATE
        } else {
            OFlags::empty()
        };
    let file = File::from(
        rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
            .map_err(|_| storage_error())?,
    );
    verify_file(&file)?;
    Ok(file)
}
pub(super) fn open_existing(directory: &File, name: &str) -> Result<Option<File>> {
    match rustix::fs::openat(
        directory,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
        Mode::empty(),
    ) {
        Ok(fd) => {
            let file = File::from(fd);
            verify_file(&file)?;
            Ok(Some(file))
        }
        Err(rustix::io::Errno::NOENT) => Ok(None),
        Err(_) => Err(storage_error()),
    }
}
pub(super) fn exists(directory: &File, name: &str) -> Result<bool> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(storage_error()),
    }
}
