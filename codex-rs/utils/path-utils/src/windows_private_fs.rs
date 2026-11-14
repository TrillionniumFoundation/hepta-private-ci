//! Private Windows state anchored to a retained, validated directory handle.
//!
//! Existing objects are rejected when their owner, DACL, type, link count, or
//! reparse status is unsafe. Creation supplies the protected DACL atomically;
//! it never changes permissions on a pre-existing object to make it acceptable.

mod nt;
mod snapshot;

pub use snapshot::FileSnapshot;
pub use snapshot::snapshot_private_file;

use std::fs::File;
use std::io;
use std::path::Path;

use crate::windows_security::CurrentIdentity;
use crate::windows_security::DescriptorInheritance;
use crate::windows_security::OwnerSecurityDescriptor;
use crate::windows_security::invalid_security;

/// A private state directory whose children are resolved relative to its handle.
#[derive(Debug)]
pub struct PrivateDirectory {
    file: File,
}

impl PrivateDirectory {
    /// Opens or creates one directory. Its parent must already exist.
    pub fn open_or_create(path: &Path) -> io::Result<Self> {
        let identity = CurrentIdentity::read()?;
        let descriptor = OwnerSecurityDescriptor::new(
            &identity.user,
            DescriptorInheritance::ContainersAndObjects,
        )?;
        let file = nt::open_absolute(
            path,
            nt::Access::ReadWrite,
            nt::Kind::Directory,
            nt::Disposition::OpenOrCreate,
            Some(&descriptor),
        )?;
        if !snapshot::snapshot(&file, &identity)?.is_directory() {
            return Err(invalid_security("private state root is not a directory"));
        }
        Ok(Self { file })
    }

    /// Opens a pre-existing private directory without following any reparse point.
    pub fn open_existing(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, nt::Access::ReadWrite)
    }

    /// Retains a read-only directory handle for inspection without requesting writes.
    pub fn open_existing_read_only(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, nt::Access::Read)
    }

    fn open_directory(path: &Path, access: nt::Access) -> io::Result<Self> {
        let file = nt::open_absolute(
            path,
            access,
            nt::Kind::Directory,
            nt::Disposition::Existing,
            /*descriptor*/ None,
        )?;
        let directory = Self { file };
        directory.validate()?;
        Ok(directory)
    }

    /// Returns the retained handle for identity inspection, without reopening a path.
    pub fn as_file(&self) -> &File {
        &self.file
    }

    /// Revalidates the current effective owner and private ACL on the retained root.
    pub fn validate(&self) -> io::Result<()> {
        if !snapshot_private_file(&self.file)?.is_directory() {
            return Err(invalid_security("private state root is not a directory"));
        }
        Ok(())
    }

    pub fn open_read(&self, name: &str) -> io::Result<File> {
        self.validate()?;
        let file = nt::open_child(
            &self.file,
            name,
            nt::Access::Read,
            nt::Kind::RegularFile,
            nt::Disposition::Existing,
            /*descriptor*/ None,
        )?;
        snapshot_private_file(&file)?;
        Ok(file)
    }

    /// Opens read/write, creating a private file if missing. Never truncates it.
    pub fn open_write(&self, name: &str) -> io::Result<File> {
        self.open_for_write(name, nt::Disposition::OpenOrCreate)
    }

    /// Opens an existing file read/write without creating or truncating it.
    pub fn open_write_existing(&self, name: &str) -> io::Result<File> {
        self.open_for_write(name, nt::Disposition::Existing)
    }

    /// Creates a private file and refuses to overwrite an existing entry.
    pub fn create_new(&self, name: &str) -> io::Result<File> {
        self.open_for_write(name, nt::Disposition::CreateNew)
    }

    fn open_for_write(&self, name: &str, disposition: nt::Disposition) -> io::Result<File> {
        self.validate()?;
        let identity = CurrentIdentity::read()?;
        let descriptor =
            OwnerSecurityDescriptor::new(&identity.user, DescriptorInheritance::ObjectOnly)?;
        let file = nt::open_child(
            &self.file,
            name,
            nt::Access::ReadWrite,
            nt::Kind::RegularFile,
            disposition,
            Some(&descriptor),
        )?;
        snapshot::snapshot(&file, &identity)?;
        Ok(file)
    }

    /// Checks for a valid private file. Unsafe or unreadable entries remain errors.
    pub fn entry_exists(&self, name: &str) -> io::Result<bool> {
        match self.open_read(name) {
            Ok(_) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error),
        }
    }

    /// Replaces an entry using the source and parent handles, without a path reopen.
    ///
    /// The caller must sync the source contents first, then call `sync_all` on
    /// this directory. A later sync error does not imply publication was undone.
    pub fn replace(&self, source: &str, destination: &str) -> io::Result<()> {
        self.validate()?;
        let file = nt::open_child(
            &self.file,
            source,
            nt::Access::Rename,
            nt::Kind::RegularFile,
            nt::Disposition::Existing,
            /*descriptor*/ None,
        )?;
        snapshot_private_file(&file)?;
        self.entry_exists(destination)?;
        nt::replace(&self.file, &file, destination)
    }

    /// Removes only the validated file represented by this exact prior snapshot.
    ///
    /// The deletion applies to the opened file handle, so a later entry swap
    /// cannot redirect cleanup to another file. The caller must sync the directory.
    pub fn remove_if_unchanged(&self, name: &str, expected: &FileSnapshot) -> io::Result<()> {
        self.validate()?;
        let file = nt::open_child(
            &self.file,
            name,
            nt::Access::Rename,
            nt::Kind::RegularFile,
            nt::Disposition::Existing,
            /*descriptor*/ None,
        )?;
        if snapshot_private_file(&file)? != *expected {
            return Err(invalid_security("cleanup file identity changed"));
        }
        nt::remove(&file)
    }

    /// Flushes the writable directory handle and propagates every OS error.
    pub fn sync_all(&self) -> io::Result<()> {
        self.validate()?;
        self.file.sync_all()
    }
}

#[cfg(test)]
#[path = "windows_private_fs_tests.rs"]
mod tests;
