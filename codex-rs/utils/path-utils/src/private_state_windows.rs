//! Handle-bound private state files on local Windows filesystems.
//!
//! Creation supplies a protected DACL for the current process owner. Existing
//! objects must already satisfy that contract; opening never repairs an unsafe
//! ACL. Root and child opens reject reparse traversal, children must have one
//! hard link, and every child operation is relative to the pinned root handle.
//! Successful flushes have the filesystem/device guarantees of FlushFileBuffers;
//! unsupported or failed flushes remain errors, including after a rename.

use std::fs::File;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::path::Component;
use std::path::Path;
use std::path::Prefix;

#[path = "private_state_nt.rs"]
mod nt;
#[path = "private_state_security.rs"]
mod security;

use security::OwnerSecurity;

/// Access requested for one validated regular state file.
#[derive(Clone, Copy)]
pub enum StateFileAccess {
    Read,
    /// Open a file for mutation without creating an absent journal.
    WriteExisting,
    Create,
}

/// A private owner directory whose open handle prevents rebinding by rename.
#[derive(Debug)]
pub struct PrivateStateDirectory {
    file: File,
}

impl PrivateStateDirectory {
    /// Create the final directory, or verify an existing one without changing it.
    /// Parent directories must exist. Only absolute local-disk paths are accepted.
    pub fn open_or_create(path: &Path) -> io::Result<Self> {
        let name = native_path(path)?;
        let owner = OwnerSecurity::current()?;
        let file = nt::open(
            None,
            &name,
            owner.descriptor(),
            nt::EntryKind::Directory,
            nt::Access::Create,
        )?;
        nt::validate_kind(&file, nt::EntryKind::Directory)?;
        owner.validate(&file)?;
        Ok(Self { file })
    }

    /// Open a single regular child without following links or changing its ACL.
    pub fn open_file(&self, name: &str, access: StateFileAccess) -> io::Result<File> {
        let access = match access {
            StateFileAccess::Read => nt::Access::Read,
            StateFileAccess::WriteExisting => nt::Access::WriteExisting,
            StateFileAccess::Create => nt::Access::Create,
        };
        self.open_child(name, access)
    }

    /// Check a validated child entry; unsafe entries are errors, not absence.
    pub fn entry_exists(&self, name: &str) -> io::Result<bool> {
        match self.open_child(name, nt::Access::Read) {
            Ok(_) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error),
        }
    }

    /// Atomically rename a previously synced staging file within this directory.
    /// The caller must then sync this directory and treat a failure as uncertain
    /// durability. The method does not acknowledge persistence on its own.
    pub fn replace_file(&self, staging: &str, destination: &str) -> io::Result<()> {
        let destination_name = child_name(destination)?;
        // Validate an existing target before permitting replacement of it.
        self.entry_exists(destination)?;
        let source = self.open_child(staging, nt::Access::WriteExisting)?;
        nt::rename(&self.file, &source, &destination_name)
    }

    /// Flush directory metadata without suppressing unsupported-filesystem errors.
    pub fn sync_all(&self) -> io::Result<()> {
        self.file.sync_all()
    }

    fn open_child(&self, name: &str, access: nt::Access) -> io::Result<File> {
        let name = child_name(name)?;
        let owner = OwnerSecurity::current()?;
        owner.validate(&self.file)?;
        let file = nt::open(
            Some(&self.file),
            &name,
            owner.descriptor(),
            nt::EntryKind::File,
            access,
        )?;
        nt::validate_kind(&file, nt::EntryKind::File)?;
        owner.validate(&file)?;
        Ok(file)
    }
}

fn invalid_path() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, "invalid private state path")
}

fn child_name(name: &str) -> io::Result<Vec<u16>> {
    if name.is_empty()
        || name.len() > 240
        || matches!(name, "." | "..")
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
    {
        return Err(invalid_path());
    }
    Ok(name.encode_utf16().collect())
}

fn native_path(path: &Path) -> io::Result<Vec<u16>> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
    {
        return Err(invalid_path());
    }
    let skip = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(_) => 0,
            Prefix::VerbatimDisk(_) => 4,
            _ => return Err(invalid_path()),
        },
        _ => return Err(invalid_path()),
    };
    let mut result: Vec<u16> = "\\??\\".encode_utf16().collect();
    result.extend(path.as_os_str().encode_wide().skip(skip).map(|unit| {
        if unit == u16::from(b'/') {
            u16::from(b'\\')
        } else {
            unit
        }
    }));
    if result.contains(&0) || result.len() > 32_766 {
        return Err(invalid_path());
    }
    Ok(result)
}

#[cfg(test)]
#[path = "private_state_windows_tests.rs"]
mod tests;
