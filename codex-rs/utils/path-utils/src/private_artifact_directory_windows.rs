//! Handle-relative NT operations. None of these raw handles leave this crate.

use crate::WindowsFileId;
use crate::private_state_windows::with_private_security;
use crate::validate_private_windows_child_name;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::path::Prefix;
use windows_sys::Wdk::Foundation::OBJECT_ATTRIBUTES;
use windows_sys::Wdk::Storage::FileSystem::*;
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;
// FILE_INFORMATION_CLASS 10 is FileRenameInformation (Microsoft NT contract).
const RENAME_INFORMATION: i32 = 10;

#[derive(Clone, Copy)]
pub(super) enum Request {
    ExistingDirectory,
    ExistingFile,
    InspectFile,
    ExistingLock,
    NewDirectory,
    NewFile,
}

pub(super) fn relative(parent: &File, name: &OsStr, request: Request) -> io::Result<Option<File>> {
    let mut units = validate_private_windows_child_name(name)?;
    let mut unicode = UNICODE_STRING {
        Length: (units.len() * 2) as u16,
        MaximumLength: (units.len() * 2) as u16,
        Buffer: units.as_mut_ptr(),
    };
    let (access, kind, disposition) = match request {
        Request::ExistingDirectory => (
            FILE_TRAVERSE | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE,
            FILE_DIRECTORY_FILE,
            FILE_OPEN,
        ),
        Request::ExistingFile => (FILE_GENERIC_READ, FILE_NON_DIRECTORY_FILE, FILE_OPEN),
        Request::InspectFile => (FILE_GENERIC_READ, FILE_NON_DIRECTORY_FILE, FILE_OPEN),
        Request::ExistingLock => (
            FILE_GENERIC_READ | FILE_GENERIC_WRITE,
            FILE_NON_DIRECTORY_FILE,
            FILE_OPEN,
        ),
        Request::NewDirectory => (
            FILE_GENERIC_READ | FILE_GENERIC_WRITE,
            FILE_DIRECTORY_FILE,
            FILE_CREATE,
        ),
        Request::NewFile => (
            FILE_GENERIC_READ | FILE_GENERIC_WRITE | DELETE,
            FILE_NON_DIRECTORY_FILE,
            FILE_CREATE,
        ),
    };
    let sharing = match request {
        Request::ExistingFile | Request::ExistingLock | Request::NewFile => FILE_SHARE_READ,
        Request::ExistingDirectory | Request::InspectFile | Request::NewDirectory => {
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
        }
    };
    let mut create = |descriptor| {
        let attributes = OBJECT_ATTRIBUTES {
            Length: std::mem::size_of::<OBJECT_ATTRIBUTES>() as u32,
            RootDirectory: parent.as_raw_handle() as _,
            ObjectName: &mut unicode,
            Attributes: 0x40, // OBJ_CASE_INSENSITIVE; exactly one checked component.
            SecurityDescriptor: descriptor,
            SecurityQualityOfService: std::ptr::null_mut(),
        };
        let mut handle = 0;
        let mut block: IO_STATUS_BLOCK = unsafe { std::mem::zeroed() };
        // SAFETY: parent and all pointed-to buffers remain alive during this
        // synchronous call. No OBJ_INHERIT or open-or-create fallback is used.
        let status = unsafe {
            NtCreateFile(
                &mut handle,
                access,
                &attributes,
                &mut block,
                std::ptr::null(),
                FILE_ATTRIBUTE_NORMAL,
                sharing,
                disposition,
                FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT | kind,
                std::ptr::null(),
                0,
            )
        };
        if disposition == FILE_OPEN
            && matches!(status, STATUS_OBJECT_NAME_NOT_FOUND | STATUS_NO_SUCH_FILE)
        {
            return Ok(None);
        }
        if status < 0 {
            return Err(io::Error::from_raw_os_error(
                unsafe { RtlNtStatusToDosError(status) } as i32,
            ));
        }
        if handle == 0 || handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::other("NT create returned no owned object"));
        }
        // SAFETY: the successful NT call returned exactly one new owned handle.
        let file = unsafe { File::from_raw_handle(handle as _) };
        WindowsFileId::inspect(&file)?;
        exact_name(&file, name)?;
        Ok(Some(file))
    };
    if disposition == FILE_CREATE {
        with_private_security(|security| create(security.lpSecurityDescriptor))
    } else {
        create(std::ptr::null_mut())
    }
}

pub(super) fn writable(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
}

pub(super) fn walk(path: &Path) -> io::Result<(Vec<(File, WindowsFileId)>, File)> {
    let (drive, names) = components(path)?;
    let root = format!("{}:\\", char::from(drive));
    let wide: Vec<_> = OsStr::new(&root).encode_wide().chain([0]).collect();
    // SAFETY: wide is a terminated drive-root name; no volume is opened raw.
    if unsafe { GetDriveTypeW(wide.as_ptr()) } != 3 {
        // DRIVE_FIXED.
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "unqualified drive type",
        ));
    }
    let mut current = OpenOptions::new()
        .read(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(root)?;
    WindowsFileId::require_local_ntfs(&current)?;
    let mut ancestors = Vec::new();
    for name in names {
        let next = relative(&current, name, Request::ExistingDirectory)?
            .ok_or_else(|| io::Error::from(io::ErrorKind::NotFound))?;
        let identity = WindowsFileId::inspect(&current)?;
        ancestors.push((current, identity));
        current = next;
    }
    Ok((ancestors, current))
}

pub(super) fn validate_path(path: &Path) -> io::Result<()> {
    components(path).map(|_| ())
}

fn components(path: &Path) -> io::Result<(u8, Vec<&OsStr>)> {
    let mut components = path.components();
    let prefix = match components.next() {
        Some(Component::Prefix(prefix)) => prefix,
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "absolute disk path required",
            ));
        }
    };
    let drive = match prefix.kind() {
        Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "local fixed drive required",
            ));
        }
    };
    if !matches!(components.next(), Some(Component::RootDir)) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "absolute rooted path required",
        ));
    }
    let mut names = Vec::new();
    let mut roundtrip = PathBuf::from(prefix.as_os_str());
    roundtrip.push("\\");
    for component in components {
        let Component::Normal(name) = component else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "noncanonical directory component",
            ));
        };
        validate_private_windows_child_name(name)?;
        names.push(name);
        roundtrip.push(name);
    }
    if roundtrip.as_os_str() != path.as_os_str() || names.is_empty() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "canonical non-root directory required",
        ));
    }
    Ok((drive, names))
}

pub(super) fn exact_name(file: &File, expected: &OsStr) -> io::Result<()> {
    let mut buffer = vec![0u16; 32768];
    // SAFETY: the held disk handle is live and buffer has the declared length.
    let length = unsafe {
        GetFinalPathNameByHandleW(
            file.as_raw_handle() as _,
            buffer.as_mut_ptr(),
            buffer.len() as u32,
            0,
        )
    };
    if length == 0 {
        return Err(io::Error::last_os_error());
    }
    if length as usize >= buffer.len() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "normalized name exceeds bound",
        ));
    }
    let normalized = OsString::from_wide(&buffer[..length as usize]);
    if Path::new(&normalized).file_name() != Some(expected) {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "replacement filename alias refused",
        ));
    }
    Ok(())
}

pub(super) fn rename(file: &File, parent: &File, name: &OsStr) -> io::Result<()> {
    let units = validate_private_windows_child_name(name)?;
    let offset = std::mem::offset_of!(FILE_RENAME_INFORMATION, FileName);
    let length = std::mem::size_of::<FILE_RENAME_INFORMATION>() + units.len() * 2;
    let mut storage = vec![0usize; length.div_ceil(std::mem::size_of::<usize>())];
    let information = storage.as_mut_ptr().cast::<FILE_RENAME_INFORMATION>();
    // SAFETY: the aligned allocation includes the complete variable-name tail.
    unsafe {
        (*information).Anonymous.ReplaceIfExists = 1;
        (*information).RootDirectory = parent.as_raw_handle() as _;
        (*information).FileNameLength = (units.len() * 2) as u32;
        std::ptr::copy_nonoverlapping(
            units.as_ptr(),
            storage.as_mut_ptr().cast::<u8>().add(offset).cast(),
            units.len(),
        );
    }
    let mut block: IO_STATUS_BLOCK = unsafe { std::mem::zeroed() };
    // SAFETY: both held objects and the correctly sized name buffer remain live.
    // RootDirectory resolves the target against the original held directory.
    let status = unsafe {
        NtSetInformationFile(
            file.as_raw_handle() as _,
            &mut block,
            information.cast(),
            length as u32,
            RENAME_INFORMATION,
        )
    };
    if status < 0 {
        return Err(io::Error::from_raw_os_error(
            unsafe { RtlNtStatusToDosError(status) } as i32,
        ));
    }
    Ok(())
}
