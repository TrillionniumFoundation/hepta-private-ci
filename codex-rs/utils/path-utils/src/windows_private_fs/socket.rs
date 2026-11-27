//! Windows AF_UNIX entries under retained physical, owner-private directories.

use std::fs::File;
use std::io;
use std::os::windows::io::AsHandle;
use std::path::Component;
use std::path::Path;
use std::sync::Arc;

use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_TAG_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FileAttributeTagInfo;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;

use super::nt;
use super::snapshot;
use crate::windows_security::CurrentIdentity;
use crate::windows_security::DescriptorInheritance;
use crate::windows_security::OwnerSecurityDescriptor;
use crate::windows_security::invalid_security;
use crate::windows_security::private_child_creation_security;
use crate::windows_security::private_security;

// MS-FSCC 2.1.2.1: this tag identifies the Windows AF_UNIX rendezvous object.
const IO_REPARSE_TAG_AF_UNIX: u32 = 0x8000_0023;

#[derive(Debug)]
struct DirectoryPins {
    directory: File,
    ancestors: Vec<File>,
}

impl DirectoryPins {
    fn validate(&self) -> io::Result<()> {
        if !snapshot::snapshot_private_file(&self.directory)?.is_directory() {
            return Err(invalid_security("socket parent is not a private directory"));
        }
        private_child_creation_security(self.directory.as_handle(), &CurrentIdentity::read()?)?;
        for ancestor in &self.ancestors {
            let tags: FILE_ATTRIBUTE_TAG_INFO = snapshot::query(ancestor, FileAttributeTagInfo)?;
            if tags.FileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0
                || tags.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
                || tags.ReparseTag != 0
            {
                return Err(invalid_security("socket ancestor changed filesystem type"));
            }
        }
        Ok(())
    }
}

/// A private socket directory with every physical ancestor retained against rename.
///
/// Windows `bind` accepts a pathname, not a directory handle. Retaining the
/// complete path without delete sharing keeps that pathname bound to these
/// physical directories until every returned socket capability is dropped.
#[derive(Debug)]
pub struct PrivateSocketDirectory {
    pins: Arc<DirectoryPins>,
}

impl PrivateSocketDirectory {
    /// Creates the final directory with a private inheritable DACL, or checks
    /// an existing directory unchanged. All ancestors must already exist.
    pub fn open_or_create(path: &Path) -> io::Result<Self> {
        if !path.is_absolute()
            || path
                .components()
                .any(|part| matches!(part, Component::ParentDir))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "socket directory must be absolute without parent traversal",
            ));
        }
        let mut ancestors = Vec::new();
        for ancestor in path
            .ancestors()
            .skip(1)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
        {
            ancestors.push(nt::open_absolute(
                ancestor,
                nt::Access::Read,
                nt::Kind::PinnedDirectory,
                nt::Disposition::Existing,
                /*descriptor*/ None,
            )?);
        }
        let identity = CurrentIdentity::read()?;
        let descriptor = OwnerSecurityDescriptor::new(
            &identity.user,
            DescriptorInheritance::ContainersAndObjects,
        )?;
        let directory = nt::open_absolute(
            path,
            nt::Access::ReadWrite,
            nt::Kind::PinnedDirectory,
            nt::Disposition::OpenOrCreate,
            Some(&descriptor),
        )?;
        let pins = Arc::new(DirectoryPins {
            directory,
            ancestors,
        });
        pins.validate()?;
        Ok(Self { pins })
    }

    /// Opens one existing, owner-private AF_UNIX entry without following it.
    /// Only an actual not-found result is absence. Other object types, links,
    /// permissions, and inspection errors remain refusals without deletion.
    pub fn open_socket(&self, name: &str) -> io::Result<Option<PrivateSocket>> {
        self.pins.validate()?;
        let file = match nt::open_child(
            &self.pins.directory,
            name,
            nt::Access::Rename,
            nt::Kind::SocketRendezvous,
            nt::Disposition::Existing,
            /*descriptor*/ None,
        ) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        let socket = PrivateSocket {
            file,
            pins: Arc::clone(&self.pins),
        };
        socket.validate()?;
        Ok(Some(socket))
    }
}

/// A validated socket entry retained against path replacement until cleanup.
/// This does not prove a socket is stale: callers must first perform the real
/// connection probe or retain this capability from their own successful bind.
#[derive(Debug)]
pub struct PrivateSocket {
    file: File,
    pins: Arc<DirectoryPins>,
}

impl PrivateSocket {
    fn validate(&self) -> io::Result<()> {
        self.pins.validate()?;
        let tags: FILE_ATTRIBUTE_TAG_INFO = snapshot::query(&self.file, FileAttributeTagInfo)?;
        let standard: FILE_STANDARD_INFO = snapshot::query(&self.file, FileStandardInfo)?;
        if tags.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT == 0
            || tags.ReparseTag != IO_REPARSE_TAG_AF_UNIX
            || standard.Directory
            || standard.DeletePending
            || standard.NumberOfLinks != 1
        {
            return Err(invalid_security(
                "socket entry is not one physical AF_UNIX object",
            ));
        }
        private_security(self.file.as_handle(), &CurrentIdentity::read()?)?;
        Ok(())
    }

    /// Removes only this still-private AF_UNIX object through its retained handle.
    pub fn remove(self) -> io::Result<()> {
        self.validate()?;
        nt::remove(&self.file)
    }
}

#[cfg(test)]
#[path = "windows_private_socket_tests.rs"]
mod tests;
