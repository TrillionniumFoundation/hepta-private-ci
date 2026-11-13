//! Full handle identity, distinct from path spelling, size or timestamps.

use super::Kind;
use super::SqliteRecoveryError;
use std::fs::File;
use std::os::windows::io::AsRawHandle;
use windows_sys::Win32::Storage::FileSystem::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct FileId {
    volume: u64,
    id: [u8; 16],
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct Snapshot {
    identity: FileId,
    creation: i64,
    modified: i64,
    changed: i64,
    length: i64,
    allocated: i64,
    links: u32,
    attributes: u32,
    security: Vec<u8>,
}

pub(super) fn file_id(file: &File) -> Result<FileId, SqliteRecoveryError> {
    // SAFETY: the borrowed File owns a live handle across these read-only calls.
    if unsafe { GetFileType(file.as_raw_handle() as _) } != FILE_TYPE_DISK {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let mut tag: FILE_ATTRIBUTE_TAG_INFO = unsafe { std::mem::zeroed() };
    query(file, FileAttributeTagInfo, &mut tag)?;
    if tag.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0 || tag.ReparseTag != 0 {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let mut information: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    query(file, FileIdInfo, &mut information)?;
    if information.VolumeSerialNumber == 0 || information.FileId.Identifier == [0; 16] {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(FileId {
        volume: information.VolumeSerialNumber,
        id: information.FileId.Identifier,
    })
}

pub(super) fn snapshot(file: &File, kind: Kind) -> Result<Snapshot, SqliteRecoveryError> {
    let identity = file_id(file)?;
    let mut basic: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
    let mut standard: FILE_STANDARD_INFO = unsafe { std::mem::zeroed() };
    query(file, FileBasicInfo, &mut basic)?;
    query(file, FileStandardInfo, &mut standard)?;
    let directory = matches!(kind, Kind::Directory);
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
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let security = super::security::private_security(file)?;
    // Metadata/security collection is not assumed atomic. Recheck the stable
    // immutable identity before accepting the complete snapshot.
    if file_id(file)? != identity {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(Snapshot {
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

fn query<T>(
    file: &File,
    class: FILE_INFO_BY_HANDLE_CLASS,
    value: &mut T,
) -> Result<(), SqliteRecoveryError> {
    let size =
        u32::try_from(std::mem::size_of::<T>()).map_err(|_| SqliteRecoveryError::Indeterminate)?;
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
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(())
}

pub(super) fn require_local_ntfs(file: &File) -> Result<(), SqliteRecoveryError> {
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
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(())
}
