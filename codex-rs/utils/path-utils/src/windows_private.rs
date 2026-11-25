//! Handle-bound private storage on local NTFS volumes.
//!
//! Existing objects are never chmod-ed or repaired. They must have the current
//! token user as owner and a protected, owner-only DACL. Every child is opened
//! relative to the retained directory handle without following reparse points.
//! Directory flush failures remain errors; this is not a power-loss simulator.

use std::fs::File;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;

use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_NAME_OPENED;
use windows_sys::Win32::Storage::FileSystem::FILE_TYPE_DISK;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::GetFileType;
use windows_sys::Win32::Storage::FileSystem::GetFinalPathNameByHandleW;
use windows_sys::Win32::Storage::FileSystem::GetVolumeInformationByHandleW;
use windows_sys::Win32::Storage::FileSystem::VOLUME_NAME_GUID;
use windows_sys::Win32::System::SystemServices::FILE_PERSISTENT_ACLS;

#[path = "windows_private_handles.rs"]
mod handles;
#[path = "windows_private_namespace.rs"]
mod namespace;
#[path = "windows_private_security.rs"]
mod security;
#[path = "windows_private_sqlite.rs"]
mod sqlite;
pub use sqlite::DirectorySnapshot;
pub use sqlite::PrivateSqliteDirectory;
pub use sqlite::Snapshot;

/// File access within an already validated private directory.
#[derive(Clone, Copy)]
pub enum Access {
    Read,
    Write,
    Create,
    CreateNew,
}

/// A private, non-reparse local NTFS directory held open for its lifetime.
pub struct PrivateDirectory {
    file: File,
    identity: security::Identity,
    writable: bool,
}

impl PrivateDirectory {
    /// Create a private directory atomically, or validate an existing one.
    ///
    /// The parent must exist. Relative, UNC, device and redirected paths are
    /// rejected. Existing ACLs are inspected on the opened handle, never changed.
    pub fn prepare(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, handles::DirectoryMode::Prepare)
    }

    /// Create a new protected, non-inheriting owner-only directory atomically.
    /// Existing names fail with `AlreadyExists` and are never adopted or repaired.
    pub fn create_new(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, handles::DirectoryMode::CreateNew)
    }

    /// Open an existing root for writes and execute its real flush barrier.
    /// This never creates the root or modifies an existing security descriptor.
    pub fn open_existing(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, handles::DirectoryMode::WritableExisting)
    }

    /// Inspect an existing strict private root without creation or a write flush.
    /// The returned wrapper permits only read access to its children.
    pub fn inspect(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, handles::DirectoryMode::ReadOnlyExisting)
    }

    fn open_directory(path: &Path, mode: handles::DirectoryMode) -> io::Result<Self> {
        let identity = security::Identity::current()?;
        let descriptor = if matches!(
            mode,
            handles::DirectoryMode::Prepare | handles::DirectoryMode::CreateNew
        ) {
            Some(identity.descriptor()?)
        } else {
            None
        };
        let file = handles::directory_with(
            path,
            descriptor
                .as_ref()
                .map_or(ptr::null(), security::Descriptor::as_ptr),
            mode,
        )?;
        validate_kind(&file, ObjectKind::Directory)?;
        identity.validate(&file)?;
        validate_volume(&file)?;
        // Prove that the retained handle supports the real durability barrier
        // before any authoritative file is created. Never replace this with Ok.
        let writable = !matches!(mode, handles::DirectoryMode::ReadOnlyExisting);
        if writable {
            file.sync_all()?;
        }
        Ok(Self {
            file,
            identity,
            writable,
        })
    }

    /// Open a single regular file; creation never inherits a broader parent ACL.
    pub fn open(&self, name: &str, access: Access) -> io::Result<File> {
        self.identity.validate(&self.file)?;
        if !self.writable && !matches!(access, Access::Read) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "read-only private directory inspection",
            ));
        }
        let descriptor = self.identity.descriptor()?;
        let file = handles::child(&self.file, name, access, descriptor.as_ptr())?;
        validate_kind(&file, ObjectKind::File)?;
        self.identity.validate(&file)?;
        Ok(file)
    }

    /// Test for a valid private regular file, rejecting unsafe existing entries.
    pub fn contains(&self, name: &str) -> io::Result<bool> {
        match self.open(name, Access::Read) {
            Ok(_) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error),
        }
    }

    /// Atomically replace a same-directory name with an already flushed file.
    ///
    /// The caller must subsequently call `sync_all`. Failure after a successful
    /// rename is an indeterminate commit and must poison the authoritative owner.
    pub fn replace(&self, source: &str, destination: &str) -> io::Result<()> {
        let file = self.open(source, Access::Write)?;
        self.contains(destination)?;
        handles::replace(&self.file, &file, destination)
    }

    /// Flush the retained directory handle, propagating the actual OS result.
    pub fn sync_all(&self) -> io::Result<()> {
        self.identity.validate(&self.file)?;
        if !self.writable {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "read-only private directory inspection",
            ));
        }
        self.file.sync_all()
    }
}

fn validate_volume(file: &File) -> io::Result<()> {
    let mut filesystem = [0_u16; 32];
    let mut flags = 0;
    // SAFETY: The handle and output buffers remain live for the call.
    let success = unsafe {
        GetVolumeInformationByHandleW(
            file.as_raw_handle() as _,
            ptr::null_mut(),
            /*nvolumenamesize*/ 0,
            ptr::null_mut(),
            ptr::null_mut(),
            &mut flags,
            filesystem.as_mut_ptr(),
            filesystem.len() as u32,
        )
    };
    if success == 0 {
        return Err(io::Error::last_os_error());
    }
    if filesystem[..5] != [78, 84, 70, 83, 0] || flags & FILE_PERSISTENT_ACLS == 0 {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "private storage requires local NTFS with persistent ACLs",
        ));
    }
    // A drive letter may name an SMB mapping. Require a volume GUID from
    // this exact handle: Windows does not assign volume GUIDs to shares.
    let mut volume_path = vec![0_u16; 32_768];
    // SAFETY: The handle and bounded output allocation remain live.
    let length = unsafe {
        GetFinalPathNameByHandleW(
            file.as_raw_handle() as _,
            volume_path.as_mut_ptr(),
            volume_path.len() as u32,
            FILE_NAME_OPENED | VOLUME_NAME_GUID,
        )
    } as usize;
    if length == 0 {
        return Err(io::Error::last_os_error());
    }
    let prefix: Vec<u16> = r"\\?\Volume{".encode_utf16().collect();
    if length >= volume_path.len() || !volume_path[..length].starts_with(&prefix) {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "private storage requires a local volume GUID",
        ));
    }
    Ok(())
}

enum ObjectKind {
    Directory,
    File,
}

fn validate_kind(file: &File, expected: ObjectKind) -> io::Result<()> {
    // SAFETY: Zero is a valid initial representation and the API fills it.
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    let handle = file.as_raw_handle() as _;
    // SAFETY: Both the borrowed handle and output buffer remain live.
    if unsafe { GetFileInformationByHandle(handle, &mut information) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let directory = information.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY != 0;
    // SAFETY: This is the same live filesystem handle that was inspected above.
    if unsafe { GetFileType(handle) } != FILE_TYPE_DISK
        || information.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || match expected {
            ObjectKind::Directory => !directory,
            ObjectKind::File => directory || information.nNumberOfLinks != 1,
        }
    {
        return Err(unsafe_object());
    }
    Ok(())
}

fn unsafe_object() -> io::Error {
    io::Error::new(
        io::ErrorKind::PermissionDenied,
        "storage object is not private, regular or free of reparse points",
    )
}

#[cfg(test)]
#[path = "windows_private_tests.rs"]
mod tests;
