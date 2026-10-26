//! Retained local-NTFS recovery handles. Every child is opened relative to its
//! held directory, one component at a time, and every reparse point is refused.
//! These identities authorize inspection only; they never establish Current.

use super::ExistingSqliteRecoveryGuard;
use super::RecoveryGuardInner;
use super::SqliteRecoveryError;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::path::Component;
use std::path::Path;
use std::path::Prefix;
use std::sync::Arc;
use windows_sys::Wdk::Foundation::OBJECT_ATTRIBUTES;
use windows_sys::Wdk::Storage::FileSystem::*;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::STATUS_NO_SUCH_FILE;
use windows_sys::Win32::Foundation::STATUS_OBJECT_NAME_NOT_FOUND;
use windows_sys::Win32::Foundation::UNICODE_STRING;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::IO::IO_STATUS_BLOCK;

#[path = "sqlite_recovery_windows_identity.rs"]
mod identity;
#[path = "sqlite_recovery_windows_security.rs"]
mod security;

#[derive(Clone, Copy)]
enum Kind {
    Directory,
    File,
}

#[derive(Debug)]
pub(super) struct RetainedObject {
    pub(super) descriptor: File,
    name: OsString,
    snapshot: identity::Snapshot,
}

#[derive(Debug)]
pub(super) enum RetainedOptionalObject {
    Absent(OsString),
    Present(RetainedObject),
}

pub(super) fn bind(path: &Path) -> Result<ExistingSqliteRecoveryGuard, SqliteRecoveryError> {
    let home = path.parent().ok_or(SqliteRecoveryError::Indeterminate)?;
    let (ancestors, directory) = open_home(home)?;
    let parent = RetainedObject {
        snapshot: identity::snapshot(&directory, Kind::Directory)?,
        descriptor: directory,
        name: OsString::new(),
    };
    let database = required(&parent.descriptor, file_name(path)?)?;
    let sidecars = ["-wal", "-shm", "-journal"].map(|suffix| {
        let sidecar = super::sqlite_sidecar_path(path, suffix);
        let name = file_name(&sidecar)?;
        match relative(&parent.descriptor, name, Kind::File)? {
            Some(file) => retained(file, name).map(RetainedOptionalObject::Present),
            None => Ok(RetainedOptionalObject::Absent(name.to_owned())),
        }
    });
    let [wal, shm, journal] = sidecars;
    let guard = ExistingSqliteRecoveryGuard {
        inner: Arc::new(RecoveryGuardInner {
            database_path: path.to_owned(),
            parent,
            database,
            sidecars: [wal?, shm?, journal?],
            ancestors,
        }),
    };
    guard.revalidate()?;
    Ok(guard)
}

pub(super) fn revalidate(inner: &RecoveryGuardInner) -> Result<(), SqliteRecoveryError> {
    let home = inner
        .database_path
        .parent()
        .ok_or(SqliteRecoveryError::Indeterminate)?;
    let (ancestors, directory) = open_home(home)?;
    if ancestors.len() != inner.ancestors.len() {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    for (original, current) in inner.ancestors.iter().zip(&ancestors) {
        if identity::file_id(original)? != identity::file_id(current)? {
            return Err(SqliteRecoveryError::Indeterminate);
        }
    }
    if identity::snapshot(&directory, Kind::Directory)? != inner.parent.snapshot
        || identity::snapshot(&inner.parent.descriptor, Kind::Directory)? != inner.parent.snapshot
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    check_object(&inner.database, &directory)?;
    for sidecar in &inner.sidecars {
        match sidecar {
            RetainedOptionalObject::Absent(name) => {
                if relative(&directory, name, Kind::File)?.is_some() {
                    return Err(SqliteRecoveryError::Indeterminate);
                }
            }
            RetainedOptionalObject::Present(object) => check_object(object, &directory)?,
        }
    }
    Ok(())
}

fn check_object(object: &RetainedObject, directory: &File) -> Result<(), SqliteRecoveryError> {
    let current =
        relative(directory, &object.name, Kind::File)?.ok_or(SqliteRecoveryError::Indeterminate)?;
    if identity::snapshot(&current, Kind::File)? != object.snapshot
        || identity::snapshot(&object.descriptor, Kind::File)? != object.snapshot
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(())
}

fn retained(descriptor: File, name: &OsStr) -> Result<RetainedObject, SqliteRecoveryError> {
    Ok(RetainedObject {
        snapshot: identity::snapshot(&descriptor, Kind::File)?,
        descriptor,
        name: name.to_owned(),
    })
}

fn required(directory: &File, name: &OsStr) -> Result<RetainedObject, SqliteRecoveryError> {
    retained(
        relative(directory, name, Kind::File)?.ok_or(SqliteRecoveryError::Indeterminate)?,
        name,
    )
}

fn file_name(path: &Path) -> Result<&OsStr, SqliteRecoveryError> {
    let name = path.file_name().ok_or(SqliteRecoveryError::Indeterminate)?;
    validate_name(name)?;
    Ok(name)
}

fn validate_name(name: &OsStr) -> Result<Vec<u16>, SqliteRecoveryError> {
    let units: Vec<_> = name.encode_wide().collect();
    let base = name
        .to_string_lossy()
        .split('.')
        .next()
        .unwrap_or_default()
        .to_ascii_uppercase();
    let reserved = matches!(base.as_str(), "CON" | "PRN" | "AUX" | "NUL" | "CLOCK$")
        || base
            .strip_prefix("COM")
            .or_else(|| base.strip_prefix("LPT"))
            .is_some_and(|suffix| {
                matches!(suffix.as_bytes(), [b'1'..=b'9']) || matches!(suffix, "¹" | "²" | "³")
            });
    if reserved
        || units.is_empty()
        || units.iter().any(|unit| matches!(*unit, 0 | 47 | 58 | 92))
        || units == [46]
        || units == [46, 46]
        || matches!(units.last(), Some(32 | 46))
        || units.len() > (u16::MAX as usize / 2)
    {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok(units)
}

fn relative(parent: &File, name: &OsStr, kind: Kind) -> Result<Option<File>, SqliteRecoveryError> {
    let mut units = validate_name(name)?;
    let mut name = UNICODE_STRING {
        Length: (units.len() * 2) as u16,
        MaximumLength: (units.len() * 2) as u16,
        Buffer: units.as_mut_ptr(),
    };
    let attributes = OBJECT_ATTRIBUTES {
        Length: std::mem::size_of::<OBJECT_ATTRIBUTES>() as u32,
        RootDirectory: parent.as_raw_handle() as _,
        ObjectName: &mut name,
        Attributes: 0x40, // OBJ_CASE_INSENSITIVE; one component, never follow a reparse.
        SecurityDescriptor: std::ptr::null_mut(),
        SecurityQualityOfService: std::ptr::null_mut(),
    };
    let mut handle = 0;
    let mut status_block: IO_STATUS_BLOCK = unsafe { std::mem::zeroed() };
    let (access, object_type) = match kind {
        Kind::Directory => (FILE_TRAVERSE, FILE_DIRECTORY_FILE),
        Kind::File => (FILE_READ_DATA, FILE_NON_DIRECTORY_FILE),
    };
    // SAFETY: all buffers live across the synchronous call; the retained parent
    // handle is borrowed. FILE_OPEN never creates, truncates or writes an object.
    let status = unsafe {
        NtCreateFile(
            &mut handle,
            access | FILE_READ_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE,
            &attributes,
            &mut status_block,
            std::ptr::null(),
            0,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            FILE_OPEN,
            FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT | object_type,
            std::ptr::null(),
            0,
        )
    };
    if matches!(status, STATUS_OBJECT_NAME_NOT_FOUND | STATUS_NO_SUCH_FILE) {
        return Ok(None);
    }
    if status < 0 || handle == 0 || handle == INVALID_HANDLE_VALUE {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: the successful call returned exactly one new owned handle.
    let file = unsafe { File::from_raw_handle(handle as _) };
    identity::file_id(&file)?; // Includes disk/type/tag checks before use.
    Ok(Some(file))
}

fn open_home(home: &Path) -> Result<(Vec<File>, File), SqliteRecoveryError> {
    let mut components = home.components();
    let drive = match components.next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
            _ => return Err(SqliteRecoveryError::Indeterminate),
        },
        _ => return Err(SqliteRecoveryError::Indeterminate),
    };
    if !matches!(components.next(), Some(Component::RootDir)) {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let drive_root: Vec<_> = format!("{}:\\", char::from(drive))
        .encode_utf16()
        .chain([0])
        .collect();
    // SAFETY: drive_root is a terminated drive-root spelling. Mapped network
    // drives and removable/unqualified filesystems are not admitted.
    const DRIVE_FIXED: u32 = 3; // Windows SDK GetDriveTypeW result.
    if unsafe { GetDriveTypeW(drive_root.as_ptr()) } != DRIVE_FIXED {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    let root: Vec<_> = format!("\\\\?\\{}:\\", char::from(drive))
        .encode_utf16()
        .chain([0])
        .collect();
    // SAFETY: root is a NUL-terminated local drive-root name with no intermediate
    // path components. No creation, backup privilege bypass or write is requested.
    let handle = unsafe {
        CreateFileW(
            root.as_ptr(),
            FILE_READ_ATTRIBUTES | FILE_TRAVERSE | SYNCHRONIZE,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            0,
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    // SAFETY: CreateFileW returned a new owned handle.
    let mut current = unsafe { File::from_raw_handle(handle as _) };
    identity::require_local_ntfs(&current)?;
    let mut ancestors = Vec::new();
    for component in components {
        let Component::Normal(name) = component else {
            return Err(SqliteRecoveryError::Indeterminate);
        };
        let next =
            relative(&current, name, Kind::Directory)?.ok_or(SqliteRecoveryError::Indeterminate)?;
        ancestors.push(current);
        current = next;
    }
    if ancestors.is_empty() {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    Ok((ancestors, current))
}
