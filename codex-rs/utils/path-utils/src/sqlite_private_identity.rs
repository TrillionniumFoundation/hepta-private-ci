//! Immutable handle metadata for a retained SQLite source; access time is excluded.

use super::super::nt;
use super::super::security::OwnerSecurity;
use super::super::security::Policy;
use super::super::security::SecuritySnapshot;
use std::fs::File;
use std::io;
use std::mem::MaybeUninit;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_BASIC_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FileBasicInfo;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;

#[derive(Debug, Eq, PartialEq)]
pub(super) struct Snapshot {
    volume: u64,
    file_id: [u8; 16],
    created: i64,
    modified: i64,
    changed: i64,
    attributes: u32,
    allocated: i64,
    pub(super) length: u64,
    links: u32,
    directory: bool,
    security: SecuritySnapshot,
}

impl Snapshot {
    pub(super) fn read(file: &File, kind: nt::EntryKind) -> io::Result<Self> {
        nt::validate_kind(file, kind)?;
        // Each expansion pairs the documented information class and exact
        // output type. Unsupported identity queries remain errors.
        macro_rules! information {
            ($ty:ty, $class:expr) => {{
                let mut output = MaybeUninit::<$ty>::uninit();
                // SAFETY: The file is live; the paired class initializes this
                // exact type on success and the buffer has its complete size.
                if unsafe {
                    GetFileInformationByHandleEx(
                        file.as_raw_handle() as HANDLE,
                        $class,
                        output.as_mut_ptr().cast(),
                        size_of::<$ty>() as u32,
                    )
                } == 0 {
                    return Err(io::Error::last_os_error());
                }
                // SAFETY: The successful typed query initialized the output.
                unsafe { output.assume_init() }
            }};
        }
        let identity = information!(FILE_ID_INFO, FileIdInfo);
        let basic = information!(FILE_BASIC_INFO, FileBasicInfo);
        let standard = information!(FILE_STANDARD_INFO, FileStandardInfo);
        let (directory, policy) = match kind {
            nt::EntryKind::Directory => (true, Policy::SqliteDirectory),
            nt::EntryKind::File => (false, Policy::SqliteFile),
        };
        if standard.DeletePending != 0
            || (standard.Directory != 0) != directory
            || (!directory && standard.NumberOfLinks != 1)
            || standard.EndOfFile < 0
            || standard.AllocationSize < 0
            || basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err(super::changed());
        }
        Ok(Self {
            volume: identity.VolumeSerialNumber,
            file_id: identity.FileId.Identifier,
            created: basic.CreationTime,
            modified: basic.LastWriteTime,
            changed: basic.ChangeTime,
            attributes: basic.FileAttributes,
            allocated: standard.AllocationSize,
            length: standard.EndOfFile as u64,
            links: standard.NumberOfLinks,
            directory,
            security: OwnerSecurity::current()?.snapshot(file, policy)?,
        })
    }
}
