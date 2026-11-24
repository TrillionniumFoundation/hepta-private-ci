//! A separate owner-only inheritance contract for SQLite-created sidecars.
//!
//! The directory has one protected owner ACE with OI/CI. SQLite's ordinary
//! CreateFile calls therefore create files with only that owner's inherited
//! ACE. Explicitly created files use the stricter protected owner-only ACL.
//! Neither this type nor its inspection entry point repairs existing ACLs.

use std::fmt;
use std::fs::File;
use std::io;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::path::PathBuf;
use std::ptr;
use std::sync::Mutex;

use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_BASIC_INFO;
use windows_sys::Win32::Storage::FileSystem::FileBasicInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;

use super::Access;
use super::ObjectKind;
use super::handles;
use super::handles::DirectoryMode;
use super::namespace;
use super::security;
use super::security::AclShape;
use super::unsafe_object;
use super::validate_kind;
use super::validate_volume;

/// Same-handle identity and drift metadata; access-time changes are excluded.
/// This is not an atomic content snapshot or an authentication of currentness.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Snapshot {
    volume: u32,
    file_index: u64,
    attributes: u32,
    links: u32,
    length: u64,
    creation_time: i64,
    write_time: i64,
    change_time: i64,
}

impl Snapshot {
    pub fn same_object(&self, other: Self) -> bool {
        self.volume == other.volume && self.file_index == other.file_index
    }

    pub fn len(&self) -> u64 {
        self.length
    }

    pub fn is_empty(&self) -> bool {
        self.length == 0
    }

    fn capture(file: &File) -> io::Result<Self> {
        // SAFETY: Both all-zero values are valid API output buffers.
        let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
        // SAFETY: As above.
        let mut basic: FILE_BASIC_INFO = unsafe { std::mem::zeroed() };
        // SAFETY: The borrowed handle and correctly sized output remain live.
        if unsafe { GetFileInformationByHandle(file.as_raw_handle() as _, &mut information) } == 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: FILE_BASIC_INFO matches FileBasicInfo, with a live allocation.
        if unsafe {
            GetFileInformationByHandleEx(
                file.as_raw_handle() as _,
                FileBasicInfo,
                ptr::addr_of_mut!(basic).cast(),
                size_of::<FILE_BASIC_INFO>() as u32,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        if information.dwFileAttributes != basic.FileAttributes {
            return Err(unsafe_object());
        }
        Ok(Self {
            volume: information.dwVolumeSerialNumber,
            file_index: (u64::from(information.nFileIndexHigh) << 32)
                | u64::from(information.nFileIndexLow),
            attributes: basic.FileAttributes,
            links: information.nNumberOfLinks,
            length: (u64::from(information.nFileSizeHigh) << 32)
                | u64::from(information.nFileSizeLow),
            creation_time: basic.CreationTime,
            write_time: basic.LastWriteTime,
            change_time: basic.ChangeTime,
        })
    }
}

/// Directory identity plus two equal, bounded observations of its child names
/// and file IDs. This does not authenticate currentness or fence an ABA writer.
/// File content stability requires its own retained-object checks and writer fence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DirectorySnapshot {
    metadata: Snapshot,
    entries: Vec<namespace::Entry>,
}

/// Retains a local NTFS directory under the SQLite-specific private ACL policy.
///
/// `inspect` opens existing objects read-only without creating or flushing them.
/// Writing requires an explicitly inheritable owner-only root. This type does
/// not change `PrivateDirectory`'s stricter non-inheriting default contract.
pub struct PrivateSqliteDirectory {
    file: File,
    identity: security::Identity,
    path: PathBuf,
    writable: bool,
    enumeration: Mutex<()>,
}

impl fmt::Debug for PrivateSqliteDirectory {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PrivateSqliteDirectory")
            .field("path", &self.path)
            .field("writable", &self.writable)
            .finish_non_exhaustive()
    }
}

impl PrivateSqliteDirectory {
    /// Atomically create an owner-only inheritable root, or validate that exact
    /// policy on an existing root. The parent must already exist.
    pub fn prepare(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, DirectoryMode::Prepare)
    }

    /// Open an existing private root without creation, repair, or a write flush.
    /// Both the explicit non-inheriting policy and the SQLite policy qualify
    /// for read-only inspection; children must independently be owner-only.
    pub fn inspect(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, DirectoryMode::ReadOnlyExisting)
    }

    /// Open an existing root for new candidate files, requiring the SQLite
    /// inheritance policy and a real directory flush. Never creates the root.
    pub fn open_writable(path: &Path) -> io::Result<Self> {
        Self::open_directory(path, DirectoryMode::WritableExisting)
    }

    fn open_directory(path: &Path, mode: DirectoryMode) -> io::Result<Self> {
        let identity = security::Identity::current()?;
        let descriptor = if matches!(mode, DirectoryMode::Prepare) {
            Some(identity.sqlite_descriptor()?)
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
        let directory = Self {
            file,
            identity,
            path: path.to_path_buf(),
            writable: !matches!(mode, DirectoryMode::ReadOnlyExisting),
            enumeration: Mutex::new(()),
        };
        directory.validate()?;
        validate_volume(&directory.file)?;
        if directory.writable {
            directory.file.sync_all()?;
        }
        Ok(directory)
    }

    fn validate(&self) -> io::Result<()> {
        validate_kind(&self.file, ObjectKind::Directory)?;
        self.identity.validate_shape(
            &self.file,
            if self.writable {
                AclShape::SqliteDirectory
            } else {
                AclShape::InspectDirectory
            },
        )
    }

    /// Observe directory identity and names without relying on cached timestamps.
    /// Oversized, malformed or concurrently changing observations fail closed.
    pub fn snapshot(&self) -> io::Result<DirectorySnapshot> {
        let _enumeration = self
            .enumeration
            .lock()
            .map_err(|_| io::Error::other("private directory enumeration state is poisoned"))?;
        self.validate()?;
        let metadata = Snapshot::capture(&self.file)?;
        let entries = namespace::capture(&self.file)?;
        if namespace::capture(&self.file)? != entries || Snapshot::capture(&self.file)? != metadata
        {
            return Err(unsafe_object());
        }
        Ok(DirectorySnapshot { metadata, entries })
    }

    /// Recheck the retained handle and its original absolute namespace binding.
    pub fn verify_unchanged(&self, expected: &DirectorySnapshot) -> io::Result<()> {
        if &self.snapshot()? != expected || &Self::inspect(&self.path)?.snapshot()? != expected {
            return Err(unsafe_object());
        }
        Ok(())
    }

    pub fn open(&self, name: &str, access: Access) -> io::Result<File> {
        self.validate()?;
        if !self.writable && !matches!(access, Access::Read) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "read-only inspection",
            ));
        }
        let descriptor = self.identity.descriptor()?;
        let file = handles::child(&self.file, name, access, descriptor.as_ptr())?;
        self.file_snapshot(&file)?;
        Ok(file)
    }

    /// Validate a regular single-link file and its exact owner ACL on its handle.
    pub fn file_snapshot(&self, file: &File) -> io::Result<Snapshot> {
        self.validate()?;
        validate_kind(file, ObjectKind::File)?;
        self.identity.validate_shape(file, AclShape::SqliteFile)?;
        Snapshot::capture(file)
    }

    pub fn verify_file(&self, name: &str, file: &File, expected: Snapshot) -> io::Result<()> {
        if self.file_snapshot(file)? != expected
            || self.file_snapshot(&self.open(name, Access::Read)?)? != expected
        {
            return Err(unsafe_object());
        }
        Ok(())
    }

    pub fn replace(&self, source: &str, destination: &str) -> io::Result<()> {
        let file = self.open(source, Access::Write)?;
        match self.open(destination, Access::Read) {
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
        handles::replace(&self.file, &file, destination)
    }

    /// Remove an owned candidate through its retained DELETE-capable handle.
    /// This cannot accidentally delete a replacement installed under its name.
    ///
    /// The caller must pass the actual handle returned by this directory's
    /// `Access::CreateNew`, retained through the failed candidate transaction.
    /// `File` has no directory-ownership brand: the ACL/kind check alone does
    /// not prove that an arbitrary caller-supplied handle belongs to this root.
    pub fn remove_created(&self, file: File) -> io::Result<()> {
        self.file_snapshot(&file)?;
        if !self.writable {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "read-only inspection",
            ));
        }
        handles::remove(file)
    }

    pub fn sync_all(&self) -> io::Result<()> {
        self.validate()?;
        if !self.writable {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "read-only inspection",
            ));
        }
        self.file.sync_all()
    }
}
