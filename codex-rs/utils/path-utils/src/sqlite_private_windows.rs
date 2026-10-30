//! Private SQLite files and read-only retained sources on Windows.
//!
//! Existing objects are never repaired. Sources retain their names, native file
//! identities and owner/group/DACL snapshots; regular source handles deny new
//! write/delete sharing. Directory handles deny deletion but still share writes;
//! directory changes are rejected by snapshot revalidation. This detects drift,
//! not currentness or writer authority.
//! Sharing follows the Windows file/mapping access contract. It does not prove
//! currentness or writer authority. Bounded bytes and metadata checks still
//! require an independent current-cut witness and the owner's writer fence.
//!
//! New directories have a protected current-owner-only inheritable DACL. SQLite
//! may create private DB/WAL/SHM/journal children by ordinary inheritance. Existing
//! directories must already have this exact policy. Registry ACL rules are
//! separate and unchanged. Flush errors, including unsupported filesystems, are
//! never treated as successful durability.

use super::child_name;
use super::native_path;
use super::nt;
use super::security::OwnerSecurity;
use std::fs::File;
use std::io;
use std::os::windows::fs::FileExt;
use std::path::Path;
use std::ptr;
use std::sync::Arc;

#[path = "sqlite_private_identity.rs"]
mod identity;
use identity::Snapshot;

/// Writable destination directory. It does not confer SQLite writer authority.
#[derive(Debug)]
pub struct PrivateSqliteDirectory {
    file: File,
}

impl PrivateSqliteDirectory {
    /// Create only a missing final component under an existing local parent.
    /// The parent is opened read-only and checked before any creation. Names use
    /// the same bounded component policy as private state files.
    pub fn create_new(path: &Path) -> io::Result<Self> {
        let parent_name = native_path(path.parent().ok_or_else(super::invalid_path)?)?;
        let name = child_name(
            path.file_name().and_then(|name| name.to_str()).ok_or_else(super::invalid_path)?
        )?;
        let parent = nt::open(
            /*root*/ None, &parent_name, ptr::null(), nt::EntryKind::Directory, nt::Access::RetainRead
        )?;
        nt::validate_kind(&parent, nt::EntryKind::Directory)?;
        nt::require_local_disk(&parent)?;
        let owner = OwnerSecurity::sqlite_directory()?;
        let file = nt::open(
            Some(&parent), &name, owner.descriptor(), nt::EntryKind::Directory, nt::Access::CreateNew
        )?;
        Snapshot::read(&file, nt::EntryKind::Directory)?;
        Ok(Self { file })
    }

    /// Open an existing private directory without creating or changing its ACL.
    pub fn open_existing(path: &Path) -> io::Result<Self> {
        let (file, _) = open_directory(path, nt::Access::WriteExisting)?;
        Ok(Self { file })
    }

    /// Create one new protected owner-only file relative to this retained root.
    /// An existing name, including an unsafe entry, is never opened or truncated.
    pub fn create_new_file(&self, name: &str) -> io::Result<File> {
        let name = child_name(name)?;
        Snapshot::read(&self.file, nt::EntryKind::Directory)?;
        let owner = OwnerSecurity::current()?;
        let file = nt::open(
            Some(&self.file),
            &name,
            owner.descriptor(),
            nt::EntryKind::File,
            nt::Access::CreateNew,
        )?;
        Snapshot::read(&file, nt::EntryKind::File)?;
        Snapshot::read(&self.file, nt::EntryKind::Directory)?;
        Ok(file)
    }

    /// Flush this pinned directory; callers must first flush their new files.
    pub fn sync_all(&self) -> io::Result<()> {
        Snapshot::read(&self.file, nt::EntryKind::Directory)?;
        self.file.sync_all()
    }
}

/// An existing directory retained read-only. This type exposes no write handle.
#[derive(Clone, Debug)]
pub struct RetainedSqliteDirectory {
    inner: Arc<DirectorySource>,
}

#[derive(Debug)]
struct DirectorySource {
    name: Vec<u16>,
    file: File,
    snapshot: Snapshot,
}

/// One rooted filename, including a retained observation that it was absent.
#[derive(Debug)]
pub struct RetainedSqliteFile {
    directory: RetainedSqliteDirectory,
    name: Vec<u16>,
    object: Option<(File, Snapshot)>,
}

impl RetainedSqliteDirectory {
    /// Retain only an existing directory; never creates, repairs, or opens SQLite.
    pub fn open_existing(path: &Path) -> io::Result<Self> {
        let (file, snapshot) = open_directory(path, nt::Access::RetainRead)?;
        let retained = Self {
            inner: Arc::new(DirectorySource {
                name: native_path(path)?,
                file,
                snapshot,
            }),
        };
        retained.verify_unchanged()?;
        Ok(retained)
    }

    /// Retain a regular child or its absence. Unsafe entries are errors, not absence.
    pub fn retain_file(&self, name: &str) -> io::Result<RetainedSqliteFile> {
        self.verify_unchanged()?;
        let name = child_name(name)?;
        let object = match nt::open(
            Some(&self.inner.file),
            &name,
            ptr::null(),
            nt::EntryKind::File,
            nt::Access::RetainRead,
        ) {
            Ok(file) => {
                let snapshot = Snapshot::read(&file, nt::EntryKind::File)?;
                Some((file, snapshot))
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => None,
            Err(error) => return Err(error),
        };
        let retained = RetainedSqliteFile { directory: self.clone(), name, object };
        retained.verify_unchanged()?;
        Ok(retained)
    }

    /// Compare the pinned handle and freshly reopened original name to the snapshot.
    /// Directory metadata is immutable during capture: creating a candidate must
    /// happen after the last source verification, as it changes directory times.
    pub fn verify_unchanged(&self) -> io::Result<()> {
        let current = nt::open(
            /*root*/ None,
            &self.inner.name,
            ptr::null(),
            nt::EntryKind::Directory,
            nt::Access::RetainRead,
        )?;
        if Snapshot::read(&self.inner.file, nt::EntryKind::Directory)? != self.inner.snapshot
            || Snapshot::read(&current, nt::EntryKind::Directory)? != self.inner.snapshot
        {
            return Err(changed());
        }
        Ok(())
    }
}

impl RetainedSqliteFile {
    /// Recheck the original file or its absence relative to the pinned root.
    pub fn verify_unchanged(&self) -> io::Result<()> {
        self.directory.verify_unchanged()?;
        let current = nt::open(
            Some(&self.directory.inner.file),
            &self.name,
            ptr::null(),
            nt::EntryKind::File,
            nt::Access::RetainRead,
        );
        match (&self.object, current) {
            (None, Err(error)) if error.kind() == io::ErrorKind::NotFound => {}
            (Some((file, snapshot)), Ok(current)) => {
                if Snapshot::read(file, nt::EntryKind::File)? != *snapshot
                    || Snapshot::read(&current, nt::EntryKind::File)? != *snapshot
                {
                    return Err(changed());
                }
            }
            (_, Err(error)) => return Err(error),
            (None, Ok(_)) => return Err(changed()),
        }
        self.directory.verify_unchanged()
    }

    /// Read exactly the retained length within a caller-supplied byte bound.
    /// Every read specifies its offset, handles short reads, and is followed by
    /// full revalidation. None denotes a still-absent file, not a read failure.
    pub fn read_bounded(&self, maximum_bytes: u64) -> io::Result<Option<Vec<u8>>> {
        self.verify_unchanged()?;
        let Some((file, snapshot)) = &self.object else { return Ok(None); };
        if snapshot.length > maximum_bytes {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "retained SQLite file exceeds byte bound"));
        }
        let length = usize::try_from(snapshot.length).map_err(io::Error::other)?;
        let mut bytes = Vec::new();
        bytes.try_reserve_exact(length).map_err(io::Error::other)?;
        bytes.resize(length, 0);
        let mut offset = 0;
        while offset < bytes.len() {
            match file.seek_read(&mut bytes[offset..], offset as u64) {
                Ok(0) => return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "retained SQLite file shortened")),
                Ok(count) => offset += count,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(error) => return Err(error),
            }
        }
        self.verify_unchanged()?;
        Ok(Some(bytes))
    }
}

fn open_directory(path: &Path, access: nt::Access) -> io::Result<(File, Snapshot)> {
    let name = native_path(path)?;
    if !matches!(access, nt::Access::RetainRead | nt::Access::WriteExisting) {
        return Err(super::invalid_path());
    }
    let file = nt::open(/*root*/ None, &name, ptr::null(), nt::EntryKind::Directory, access)?;
    nt::require_local_disk(&file)?;
    let snapshot = Snapshot::read(&file, nt::EntryKind::Directory)?;
    Ok((file, snapshot))
}

fn changed() -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, "retained SQLite source identity or ACL changed")
}

#[cfg(test)]
#[path = "sqlite_private_windows_tests.rs"]
mod tests;
