//! Canonical Windows retained-file facts shared with State recovery.
//!
//! Inspection never creates a handle or grants write/Current authority.

#[path = "private_file_security_windows.rs"]
mod security;

/// Expected filesystem object kind for strict private-file inspection.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrivateFileKind {
    /// A retained ordinary directory, never a reparse object.
    Directory,
    /// A one-link ordinary file, never a reparse object.
    RegularFile,
}

use std::fs::File;
use std::io;
use std::os::windows::io::AsRawHandle;
use windows_sys::Win32::Storage::FileSystem::*;

/// Opaque volume plus full 128-bit immutable ID read from a held disk object.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct WindowsFileId {
    volume: u64,
    id: [u8; 16],
}

/// Opaque full metadata, immutable identity and validated private owner/DACL.
#[derive(Debug, Eq, PartialEq)]
pub struct PrivateFileIdentity {
    identity: WindowsFileId,
    creation: i64,
    modified: i64,
    changed: i64,
    length: i64,
    allocated: i64,
    links: u32,
    attributes: u32,
    security: Vec<u8>,
}

pub(super) fn file_id(file: &File) -> io::Result<WindowsFileId> {
    // SAFETY: the borrowed File owns a live handle across these read-only calls.
    if unsafe { GetFileType(file.as_raw_handle() as _) } != FILE_TYPE_DISK {
        return Err(indeterminate());
    }
    let mut tag: FILE_ATTRIBUTE_TAG_INFO = unsafe { std::mem::zeroed() };
    query(file, FileAttributeTagInfo, &mut tag)?;
    if tag.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 || tag.ReparseTag != 0 {
        return Err(indeterminate());
    }
    let mut information: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    query(file, FileIdInfo, &mut information)?;
    if information.VolumeSerialNumber == 0 || information.FileId.Identifier == [0; 16] {
        return Err(indeterminate());
    }
    Ok(WindowsFileId {
        volume: information.VolumeSerialNumber,
        id: information.FileId.Identifier,
    })
}

pub(super) fn snapshot(file: &File, kind: PrivateFileKind) -> io::Result<PrivateFileIdentity> {
    let identity = file_id(file)?;
    let mut basic: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
    let mut standard: FILE_STANDARD_INFO = unsafe { std::mem::zeroed() };
    query(file, FileBasicInfo, &mut basic)?;
    query(file, FileStandardInfo, &mut standard)?;
    let directory = matches!(kind, PrivateFileKind::Directory);
    if (standard.Directory != 0) != directory
        || (basic.FileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0) != directory
        || standard.DeletePending != 0
        || (!directory && standard.NumberOfLinks != 1)
        || basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || basic.CreationTime <= 0
        || basic.LastWriteTime <= 0
        || basic.ChangeTime <= 0
        || standard.EndOfFile < 0
        || standard.AllocationSize < 0
    {
        return Err(indeterminate());
    }
    let security = security::private_security(file)?;
    // Metadata/security collection is not assumed atomic. Recheck the stable
    // immutable identity before accepting the complete snapshot.
    if file_id(file)? != identity {
        return Err(indeterminate());
    }
    Ok(PrivateFileIdentity {
        identity,
        creation: basic.CreationTime,
        modified: basic.LastWriteTime,
        changed: basic.ChangeTime,
        length: standard.EndOfFile,
        allocated: standard.AllocationSize,
        links: standard.NumberOfLinks,
        attributes: basic.FileAttributes,
        security,
    })
}

fn query<T>(file: &File, class: FILE_INFO_BY_HANDLE_CLASS, value: &mut T) -> io::Result<()> {
    let size = u32::try_from(std::mem::size_of::<T>()).map_err(|_| indeterminate())?;
    // SAFETY: only correctly sized Windows FILE_* information structures are
    // passed by the private callers above. The API writes no more than size.
    if unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle() as _,
            class,
            std::ptr::from_mut(value).cast(),
            size,
        )
    } == 0
    {
        return Err(indeterminate());
    }
    Ok(())
}

pub(super) fn require_local_ntfs(file: &File) -> io::Result<()> {
    file_id(file)?;
    let mut filesystem = [0u16; 32];
    // SAFETY: filesystem is a writable buffer of exactly the declared length;
    // optional outputs are null. An unrecognized filesystem remains refused.
    let result = unsafe {
        GetVolumeInformationByHandleW(
            file.as_raw_handle() as _,
            std::ptr::null_mut(),
            0,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            filesystem.as_mut_ptr(),
            filesystem.len() as u32,
        )
    };
    if result == 0 || filesystem[..5] != [78, 84, 70, 83, 0] {
        return Err(indeterminate());
    }
    Ok(())
}

/// Opaque validated owner/DACL bytes; this value supplies no I/O authority.
#[derive(Debug, Eq, PartialEq)]
pub struct PrivateSecurityIdentity {
    descriptor: Vec<u8>,
}

impl PrivateSecurityIdentity {
    /// Inspect only the same borrowed object; no handle is created or adopted.
    pub fn inspect(file: &File) -> io::Result<Self> {
        Ok(Self {
            descriptor: security::private_security(file)?,
        })
    }

    /// Read the exact validated descriptor facts without a writable port.
    pub fn descriptor_bytes(&self) -> &[u8] {
        &self.descriptor
    }
}

impl WindowsFileId {
    /// Inspect the held disk object, including no-reparse and nonzero full-ID checks.
    pub fn inspect(file: &File) -> io::Result<Self> {
        file_id(file)
    }

    /// Require local NTFS facts on this held disk handle; no authority is granted.
    pub fn require_local_ntfs(file: &File) -> io::Result<()> {
        require_local_ntfs(file)
    }
}

impl PrivateFileIdentity {
    /// Inspect a held object with complete State-compatible type/owner/DACL checks.
    pub fn inspect(file: &File, kind: PrivateFileKind) -> io::Result<Self> {
        snapshot(file, kind)
    }

    pub(super) fn same_object_security(&self, other: &Self) -> bool {
        self.identity == other.identity && self.security == other.security
    }
}

pub(super) fn indeterminate() -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        "private Windows filesystem identity is indeterminate",
    )
}
