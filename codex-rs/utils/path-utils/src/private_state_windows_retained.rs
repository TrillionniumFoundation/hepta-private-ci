//! Recovery building blocks, intentionally not wired into recovery or activation.
//! Only local NTFS is supported. Handles deny deletion; source handles also deny
//! writes. Same-user/SYSTEM/Administrator mutation is not a security boundary:
//! callers must retain handles and compare snapshots around bounded reads.

use super::CurrentUser;
use super::HandleKind;
use super::PrivateSecuritySnapshot;
use super::capture_private_security;
use super::private_dacl;
use super::unsafe_state;
use std::ffi::c_void;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::mem::size_of_val;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::NTSTATUS;
use windows_sys::Win32::Foundation::RtlNtStatusToDosError;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Security::InitializeSecurityDescriptor;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SetSecurityDescriptorControl;
use windows_sys::Win32::Security::SetSecurityDescriptorDacl;
use windows_sys::Win32::Security::SetSecurityDescriptorOwner;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_BASIC_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_STANDARD_INFO;
use windows_sys::Win32::Storage::FileSystem::FILE_TYPE_DISK;
use windows_sys::Win32::Storage::FileSystem::FileBasicInfo;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::FileStandardInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
use windows_sys::Win32::Storage::FileSystem::GetFileType;
use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationByHandleW;

const FILE_DIRECTORY_FILE: u32 = 1;
const FILE_SYNCHRONOUS_IO_NONALERT: u32 = 0x20;
const FILE_NON_DIRECTORY_FILE: u32 = 0x40;
const FILE_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const OBJ_CASE_INSENSITIVE: u32 = 0x40;
const OBJ_DONT_REPARSE: u32 = 0x1000;

#[repr(C)]
struct ObjectAttributes {
    length: u32,
    root_directory: HANDLE,
    object_name: *const UNICODE_STRING,
    attributes: u32,
    security_descriptor: *const c_void,
    security_quality_of_service: *const c_void,
}

// IO_STATUS_BLOCK's first member is the NTSTATUS/pointer union.
#[repr(C)]
struct IoStatusBlock {
    status: usize,
    information: usize,
}

#[link(name = "ntdll")]
unsafe extern "system" {
    fn NtCreateFile(
        handle: *mut HANDLE,
        access: u32,
        attributes: *const ObjectAttributes,
        status: *mut IoStatusBlock,
        allocation: *const i64,
        file_attributes: u32,
        sharing: u32,
        disposition: u32,
        options: u32,
        ea: *const c_void,
        ea_length: u32,
    ) -> NTSTATUS;
    fn NtQueryVolumeInformationFile(
        handle: HANDLE,
        status: *mut IoStatusBlock,
        information: *mut c_void,
        length: u32,
        class: u32,
    ) -> NTSTATUS;
}

/// Existing objects are never created, truncated, or permission-repaired.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrivateDirectoryMode {
    OpenExisting,
    CreateNew,
}

/// Source access excludes writes/deletion; lock holders share reads and writes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrivateFileMode {
    ReadSource,
    CreateNew,
    OpenLock,
    CreateNewLock,
}

/// A private directory whose children are opened relative to this exact handle.
/// Existing directories are checked for unsafe effective and inheritable grants,
/// but may have no inheritable ACEs at all. This is not proof that ordinary child
/// creation is private: Windows may use the token default DACL in that case.
/// SQLite/ordinary sidecars must be created only in a fresh CreateNew generation
/// while its protected creation security remains unchanged. `open_file` creation
/// supplies its own protected descriptor and does not rely on inheritance.
#[derive(Debug)]
pub struct RetainedPrivateDirectory(File);

/// A validated, single-link regular file retained without delete sharing.
#[derive(Debug)]
pub struct RetainedPrivateFile(File);

/// Exact identity and relevant metadata from one validated retained handle.
/// Access time is excluded because reads may update it. A snapshot is evidence
/// of stability, not a content hash or an independent recovery witness.
#[derive(Debug, Eq, PartialEq)]
pub struct PrivateObjectSnapshot {
    volume: u64,
    file_id: [u8; 16],
    attributes: u32,
    creation_time: i64,
    write_time: i64,
    change_time: i64,
    allocation: i64,
    size: i64,
    links: u32,
    security: PrivateSecuritySnapshot,
}

impl RetainedPrivateDirectory {
    /// Opens a fully qualified local-drive path without any reparse traversal.
    /// A failed create is indeterminate: it can leave a new empty object whose
    /// privacy is unestablished if filesystem/security qualification failed.
    pub fn open(path: &Path, mode: PrivateDirectoryMode) -> io::Result<Self> {
        // Deliberately reject UNC/device namespaces and lossy path conversion.
        let path = path
            .to_str()
            .ok_or_else(|| unsafe_state("invalid private root path"))?;
        let path = path.strip_prefix(r"\\?\").unwrap_or(path);
        let bytes = path.as_bytes();
        if bytes.len() < 4
            || !bytes[0].is_ascii_alphabetic()
            || bytes[1] != b':'
            || bytes[2] != b'\\'
        {
            return Err(unsafe_state(
                "private roots require an absolute local-drive path",
            ));
        }
        for name in path[3..].split('\\') {
            literal_name(name)?;
        }
        let name: Vec<u16> = format!(r"\??\{path}").encode_utf16().collect();
        let file = open_handle(
            /*parent*/ 0,
            name,
            HandleKind::Directory,
            mode,
            FILE_GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
        )?;
        Ok(Self(file))
    }

    pub fn open_directory(&self, name: &str, mode: PrivateDirectoryMode) -> io::Result<Self> {
        self.snapshot()?;
        let file = open_handle(
            self.0.as_raw_handle() as HANDLE,
            literal_name(name)?,
            HandleKind::Directory,
            mode,
            FILE_GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
        )?;
        Ok(Self(file))
    }

    pub fn open_file(&self, name: &str, mode: PrivateFileMode) -> io::Result<RetainedPrivateFile> {
        self.snapshot()?;
        let (disposition, access, sharing) = match mode {
            PrivateFileMode::ReadSource => (
                PrivateDirectoryMode::OpenExisting,
                FILE_GENERIC_READ,
                FILE_SHARE_READ,
            ),
            PrivateFileMode::CreateNew => (
                PrivateDirectoryMode::CreateNew,
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                FILE_SHARE_READ,
            ),
            PrivateFileMode::OpenLock => (
                PrivateDirectoryMode::OpenExisting,
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
            ),
            PrivateFileMode::CreateNewLock => (
                PrivateDirectoryMode::CreateNew,
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
            ),
        };
        open_handle(
            self.0.as_raw_handle() as HANDLE,
            literal_name(name)?,
            HandleKind::File,
            disposition,
            access,
            sharing,
        )
        .map(RetainedPrivateFile)
    }

    pub fn snapshot(&self) -> io::Result<PrivateObjectSnapshot> {
        snapshot(&self.0, HandleKind::Directory)
    }

    /// Borrow the read-only directory handle. It permits another write-capable
    /// handle for a future validated durability barrier, but cannot flush itself.
    pub fn as_file(&self) -> &File {
        &self.0
    }
}

impl RetainedPrivateFile {
    pub fn snapshot(&self) -> io::Result<PrivateObjectSnapshot> {
        snapshot(&self.0, HandleKind::File)
    }

    /// The OS access mask remains read-only for ReadSource handles.
    pub fn as_file(&self) -> &File {
        &self.0
    }
}

fn literal_name(name: &str) -> io::Result<Vec<u16>> {
    let stem = name.split('.').next().unwrap_or_default().to_uppercase();
    let device = matches!(
        stem.as_str(),
        "CON" | "PRN" | "AUX" | "NUL" | "CONIN$" | "CONOUT$" | "CLOCK$"
    ) || ["COM", "LPT"].iter().any(|prefix| {
        stem.strip_prefix(prefix).is_some_and(|suffix| {
            matches!(
                suffix,
                "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
            )
        })
    });
    if name.is_empty()
        || name.ends_with(['.', ' '])
        || device
        || name.chars().any(|c| {
            c.is_control() || matches!(c, '/' | '\\' | ':' | '<' | '>' | '"' | '|' | '?' | '*')
        })
    {
        return Err(unsafe_state(
            "private child name is not literal and unambiguous",
        ));
    }
    Ok(name.encode_utf16().collect())
}

fn open_handle(
    parent: HANDLE,
    mut name: Vec<u16>,
    kind: HandleKind,
    mode: PrivateDirectoryMode,
    access: u32,
    sharing: u32,
) -> io::Result<File> {
    let user = CurrentUser::read()?; // Reject impersonation before filesystem effects.
    let length = u16::try_from(name.len() * size_of::<u16>())
        .map_err(|_| unsafe_state("private name is too long"))?;
    let name = UNICODE_STRING {
        Length: length,
        MaximumLength: length,
        Buffer: name.as_mut_ptr(),
    };
    let mut dacl = private_dacl(&user)?;
    let mut descriptor: SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
    let sd = (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast();
    if unsafe {
        InitializeSecurityDescriptor(sd, /*dwrevision*/ 1)
    } == 0
        || unsafe {
            SetSecurityDescriptorOwner(sd, user.sid(), /*bownerdefaulted*/ 0)
        } == 0
        || unsafe {
            SetSecurityDescriptorDacl(
                sd,
                /*bdaclpresent*/ 1,
                dacl.as_mut_ptr().cast(),
                /*bdacldefaulted*/ 0,
            )
        } == 0
        || unsafe { SetSecurityDescriptorControl(sd, SE_DACL_PROTECTED, SE_DACL_PROTECTED) } == 0
    {
        return Err(io::Error::last_os_error());
    }
    let attributes = ObjectAttributes {
        length: size_of::<ObjectAttributes>() as u32,
        root_directory: parent,
        object_name: &name,
        attributes: OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE,
        security_descriptor: if mode == PrivateDirectoryMode::CreateNew {
            sd
        } else {
            ptr::null()
        },
        security_quality_of_service: ptr::null(),
    };
    let mut status = IoStatusBlock {
        status: 0,
        information: 0,
    };
    let mut handle = 0;
    let options = match kind {
        HandleKind::Directory => FILE_DIRECTORY_FILE,
        HandleKind::File => FILE_NON_DIRECTORY_FILE,
    };
    let result = unsafe {
        NtCreateFile(
            &mut handle,
            access,
            &attributes,
            &mut status,
            ptr::null(),
            FILE_ATTRIBUTE_NORMAL,
            sharing,
            if mode == PrivateDirectoryMode::CreateNew {
                2
            } else {
                1
            },
            options | FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT,
            ptr::null(),
            /*ea_length*/ 0,
        )
    };
    if result < 0 {
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(result) } as i32,
        ));
    }
    if handle == 0 || handle == INVALID_HANDLE_VALUE {
        return Err(unsafe_state("invalid private object handle"));
    }
    let file = unsafe { File::from_raw_handle(handle as _) };
    let snapshot = snapshot(&file, kind)?;
    if mode == PrivateDirectoryMode::CreateNew && snapshot.security.control & SE_DACL_PROTECTED == 0
    {
        return Err(unsafe_state("new private object DACL is not protected"));
    }
    Ok(file)
}

fn snapshot(file: &File, kind: HandleKind) -> io::Result<PrivateObjectSnapshot> {
    let handle = file.as_raw_handle() as HANDLE;
    if unsafe { GetFileType(handle) } != FILE_TYPE_DISK {
        return Err(unsafe_state("private object is not on disk"));
    }
    let mut id: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    let mut basic: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
    let mut standard: FILE_STANDARD_INFO = unsafe { std::mem::zeroed() };
    for (class, buffer, size) in [
        (
            FileIdInfo,
            (&mut id as *mut FILE_ID_INFO).cast(),
            size_of::<FILE_ID_INFO>(),
        ),
        (
            FileBasicInfo,
            (&mut basic as *mut FILE_BASIC_INFO).cast(),
            size_of::<FILE_BASIC_INFO>(),
        ),
        (
            FileStandardInfo,
            (&mut standard as *mut FILE_STANDARD_INFO).cast(),
            size_of::<FILE_STANDARD_INFO>(),
        ),
    ] {
        if unsafe { GetFileInformationByHandleEx(handle, class, buffer, size as u32) } == 0 {
            return Err(io::Error::last_os_error());
        }
    }
    let directory = matches!(kind, HandleKind::Directory);
    if basic.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || (basic.FileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0) != directory
        || (standard.Directory != 0) != directory
        || standard.DeletePending != 0
        || (!directory && standard.NumberOfLinks != 1)
    {
        return Err(unsafe_state(
            "private object kind, links, or deletion state is unsafe",
        ));
    }
    // FILE_FS_DEVICE_INFORMATION: reject mapped/network drives as well as UNC.
    let mut device = [0_u32; 2];
    let mut status = IoStatusBlock {
        status: 0,
        information: 0,
    };
    let result = unsafe {
        NtQueryVolumeInformationFile(
            handle,
            &mut status,
            device.as_mut_ptr().cast(),
            /*length*/ 8,
            /*class*/ 4,
        )
    };
    if result < 0 {
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(result) } as i32,
        ));
    }
    if status.information != size_of_val(&device) {
        return Err(unsafe_state("incomplete private volume information"));
    }
    let mut filesystem = [0_u16; 16];
    if unsafe {
        GetVolumeInformationByHandleW(
            handle,
            ptr::null_mut(),
            0,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            filesystem.as_mut_ptr(),
            filesystem.len() as u32,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    if device[1] & 0x10 != 0
        || filesystem[..5] != [b'N' as u16, b'T' as u16, b'F' as u16, b'S' as u16, 0]
    {
        return Err(unsafe_state("private objects currently require local NTFS"));
    }
    Ok(PrivateObjectSnapshot {
        volume: id.VolumeSerialNumber,
        file_id: id.FileId.Identifier,
        attributes: basic.FileAttributes,
        creation_time: basic.CreationTime,
        write_time: basic.LastWriteTime,
        change_time: basic.ChangeTime,
        allocation: standard.AllocationSize,
        size: standard.EndOfFile,
        links: standard.NumberOfLinks,
        security: capture_private_security(file, kind)?,
    })
}

#[cfg(test)]
#[path = "private_state_windows_retained_tests.rs"]
mod tests;
