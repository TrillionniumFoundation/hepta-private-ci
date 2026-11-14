use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;

use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_TAG_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_BASIC_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_INFO_BY_HANDLE_CLASS;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_TYPE_DISK;
use windows_sys::Win32::Storage::FileSystem::FileAttributeTagInfo;
use windows_sys::Win32::Storage::FileSystem::FileBasicInfo;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::GetFileType;

use crate::windows_security::CurrentIdentity;
use crate::windows_security::SecuritySnapshot;
use crate::windows_security::invalid_security;
use crate::windows_security::private_security;

/// An owner-validated identity and change witness read entirely from one handle.
/// Access time is excluded because reading a retained recovery image can change it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FileSnapshot {
    volume: u64,
    file_id: [u8; 16],
    links: u32,
    directory: bool,
    length: u64,
    attributes: u32,
    created: i64,
    written: i64,
    changed: i64,
    security: SecuritySnapshot,
}

impl FileSnapshot {
    pub fn is_directory(&self) -> bool {
        self.directory
    }

    pub fn len(&self) -> u64 {
        self.length
    }

    pub fn is_empty(&self) -> bool {
        self.length == 0
    }

    /// Compares only the stable volume and file identity, not mutable metadata.
    pub fn same_file(&self, other: &Self) -> bool {
        self.volume == other.volume && self.file_id == other.file_id
    }
}

pub fn snapshot_private_file(file: &File) -> io::Result<FileSnapshot> {
    snapshot(file, &CurrentIdentity::read()?)
}

pub(super) fn snapshot(file: &File, identity: &CurrentIdentity) -> io::Result<FileSnapshot> {
    // SAFETY: the borrowed handle stays live for each synchronous query.
    if unsafe { GetFileType(file.as_raw_handle()) } != FILE_TYPE_DISK {
        return Err(invalid_security(
            "state handle is not a disk filesystem object",
        ));
    }
    let tags: FILE_ATTRIBUTE_TAG_INFO = query(file, FileAttributeTagInfo)?;
    let standard: FILE_STANDARD_INFO = query(file, FileStandardInfo)?;
    if tags.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || tags.ReparseTag != 0
        || standard.DeletePending
        || (!standard.Directory && standard.NumberOfLinks != 1)
    {
        return Err(invalid_security(
            "state object is redirected, multiply linked, or deleting",
        ));
    }
    let id: FILE_ID_INFO = query(file, FileIdInfo)?;
    let basic: FILE_BASIC_INFO = query(file, FileBasicInfo)?;
    Ok(FileSnapshot {
        volume: id.VolumeSerialNumber,
        file_id: id.FileId.Identifier,
        links: standard.NumberOfLinks,
        directory: standard.Directory,
        length: u64::try_from(standard.EndOfFile)
            .map_err(|_| invalid_security("state object has an invalid length"))?,
        attributes: tags.FileAttributes,
        created: basic.CreationTime,
        written: basic.LastWriteTime,
        changed: basic.ChangeTime,
        security: private_security(file.as_handle(), identity)?,
    })
}

fn query<T: Default>(file: &File, class: FILE_INFO_BY_HANDLE_CLASS) -> io::Result<T> {
    let mut value = T::default();
    // SAFETY: the private call sites pair each class with its exact Windows
    // struct. The OS receives the actual size of this aligned output object.
    if unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle(),
            class,
            (&raw mut value).cast(),
            size_of::<T>() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(value)
}
