//! One retained owner-private directory backend for durable artifact callers.

#[path = "private_artifact_directory_windows.rs"]
mod directory;

use crate::PrivateFileIdentity;
use crate::PrivateFileKind;
use crate::WindowsFileId;
use crate::private_file_identity_windows::indeterminate;
use crate::validate_private_windows_child_name;
use directory::Request;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::io;
use std::io::Write;
use std::os::windows::fs::FileExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

struct DirectoryInner {
    file: File,
    identity: PrivateFileIdentity,
    ancestors: Vec<(File, WindowsFileId)>,
    path: PathBuf,
}

/// A writable local-NTFS directory retained by its full ID and private DACL.
///
/// Construction never repairs or adopts an unsafe existing directory. Only
/// checked child-name operations are exposed; no raw handle or writable port.
#[derive(Clone)]
pub struct RetainedPrivateDirectory {
    inner: Arc<DirectoryInner>,
    writable: Arc<WritableDirectory>,
}

struct WritableDirectory {
    file: File,
    identity: PrivateFileIdentity,
}

/// One private artifact, retained with its exact full identity and parent.
///
/// It exposes verified reads/sync only, never File, HANDLE, AsRawHandle or Write.
pub struct PrivateFile {
    file: File,
    kind: PrivateFileKind,
    identity: PrivateFileIdentity,
    parent: Arc<DirectoryInner>,
    name: OsString,
}

impl RetainedPrivateDirectory {
    /// Open an existing canonical directory with real read/write directory rights.
    pub fn open_existing(path: &Path) -> io::Result<Self> {
        let inner = Arc::new(DirectoryInner::open_existing(path)?);
        let file = directory::writable(path)?;
        let identity = PrivateFileIdentity::inspect(&file, PrivateFileKind::Directory)?;
        if !identity.same_object_security(&inner.identity) {
            return Err(indeterminate());
        }
        let value = Self {
            inner,
            writable: Arc::new(WritableDirectory { file, identity }),
        };
        value.verify()?;
        Ok(value)
    }

    /// Create one absent leaf with its protected owner DACL applied atomically.
    pub fn create_new(path: &Path) -> io::Result<Self> {
        directory::validate_path(path)?;
        let parent = path.parent().ok_or_else(indeterminate)?;
        let name = path.file_name().ok_or_else(indeterminate)?;
        let (ancestors, anchor) = directory::walk(parent)?;
        let parent_id = WindowsFileId::inspect(&anchor)?;
        let writable_parent = directory::writable(parent)?;
        if WindowsFileId::inspect(&writable_parent)? != parent_id {
            return Err(indeterminate());
        }
        let created = directory::relative(&writable_parent, name, Request::NewDirectory)?
            .ok_or_else(indeterminate)?;
        let created_identity = PrivateFileIdentity::inspect(&created, PrivateFileKind::Directory)?;
        let (after_ancestors, after_parent) = directory::walk(parent)?;
        if WindowsFileId::inspect(&after_parent)? != parent_id
            || !same_ancestors(&ancestors, &after_ancestors)?
        {
            return Err(indeterminate());
        }
        let value = Self::open_existing(path)?;
        if !value.inner.identity.same_object_security(&created_identity) {
            return Err(indeterminate());
        }
        // Namespace creation is not acknowledged before the parent barrier.
        writable_parent.sync_all()?;
        value.verify()?;
        Ok(value)
    }

    /// Recheck original ancestors, held directory, current path, kind and DACL.
    pub fn verify(&self) -> io::Result<()> {
        self.inner.verify()?;
        if !self
            .writable
            .identity
            .same_object_security(&self.inner.identity)
            || !self
                .writable
                .identity
                .same_object_security(&PrivateFileIdentity::inspect(
                    &self.writable.file,
                    PrivateFileKind::Directory,
                )?)
        {
            return Err(indeterminate());
        }
        Ok(())
    }

    /// Flush this original writable directory and verify it before and after.
    pub fn sync_verified(&self) -> io::Result<()> {
        self.verify()?;
        self.writable.file.sync_all()?;
        self.verify()
    }

    /// Create exactly one new ordinary child, write exact bytes, then flush both.
    pub fn write_new_child(&self, name: &OsStr, bytes: &[u8]) -> io::Result<PrivateFile> {
        self.verify()?;
        let mut file = directory::relative(&self.writable.file, name, Request::NewFile)?
            .ok_or_else(indeterminate)?;
        let before = PrivateFileIdentity::inspect(&file, PrivateFileKind::RegularFile)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        let identity = PrivateFileIdentity::inspect(&file, PrivateFileKind::RegularFile)?;
        if !before.same_object_security(&identity) {
            return Err(indeterminate());
        }
        let value = PrivateFile {
            file,
            kind: PrivateFileKind::RegularFile,
            identity,
            parent: self.inner.clone(),
            name: name.to_owned(),
        };
        let mut offset = 0usize;
        value.read_chunks(bytes.len() as u64, |chunk| {
            let end = offset.checked_add(chunk.len()).ok_or_else(indeterminate)?;
            if bytes.get(offset..end) != Some(chunk) {
                return Err(indeterminate());
            }
            offset = end;
            Ok(())
        })?;
        if offset != bytes.len() {
            return Err(indeterminate());
        }
        self.sync_verified()?;
        value.verify()?;
        Ok(value)
    }

    /// Open one existing private child read-only, denying concurrent write/delete.
    pub fn open_child(&self, name: &OsStr) -> io::Result<PrivateFile> {
        self.verify()?;
        self.inner.open_child(name)
    }

    /// Acquire an existing private lock file without creating or changing it.
    /// The read/write handle denies other writers and deletion until dropped.
    pub fn lock_existing_child(&self, name: &OsStr) -> io::Result<PrivateFile> {
        self.verify()?;
        let file = directory::relative(&self.writable.file, name, Request::ExistingLock)?
            .ok_or_else(|| io::Error::from(io::ErrorKind::NotFound))?;
        let identity = PrivateFileIdentity::inspect(&file, PrivateFileKind::RegularFile)?;
        let value = PrivateFile {
            file,
            kind: PrivateFileKind::RegularFile,
            identity,
            parent: self.inner.clone(),
            name: name.to_owned(),
        };
        value.verify()?;
        Ok(value)
    }

    /// Create a protected empty lock, or lock an already-qualified private file.
    /// Existing ACLs are never repaired and a sharing conflict is never retried.
    pub fn create_or_lock_child(&self, name: &OsStr) -> io::Result<PrivateFile> {
        self.verify()?;
        let file = match directory::relative(&self.writable.file, name, Request::NewFile) {
            Ok(Some(file)) => file,
            Ok(None) => return Err(indeterminate()),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                return self.lock_existing_child(name);
            }
            Err(error) => return Err(error),
        };
        PrivateFileIdentity::inspect(&file, PrivateFileKind::RegularFile)?;
        file.sync_all()?;
        let identity = PrivateFileIdentity::inspect(&file, PrivateFileKind::RegularFile)?;
        let value = PrivateFile {
            file,
            kind: PrivateFileKind::RegularFile,
            identity,
            parent: self.inner.clone(),
            name: name.to_owned(),
        };
        self.sync_verified()?;
        value.verify()?;
        Ok(value)
    }

    /// Replace one normal-name child using an exclusive new temporary and NT rename.
    ///
    /// Both names stay under the original retained directory. Failed or partial
    /// effects remain failures and are not deleted or replayed implicitly.
    pub fn atomic_replace_child(
        &self,
        name: &OsStr,
        temporary: &OsStr,
        bytes: &[u8],
    ) -> io::Result<PrivateFile> {
        validate_private_windows_child_name(name)?;
        validate_private_windows_child_name(temporary)?;
        let first = validate_private_windows_child_name(name)?;
        let second = validate_private_windows_child_name(temporary)?;
        // SAFETY: both bounded, nonempty UTF-16 buffers remain alive. Ordinal
        // comparison matches the Windows namespace without locale guessing.
        let compare = unsafe {
            windows_sys::Win32::Globalization::CompareStringOrdinal(
                first.as_ptr(),
                first.len() as i32,
                second.as_ptr(),
                second.len() as i32,
                /*bignorecase*/ 1,
            )
        };
        if compare == 0 {
            return Err(io::Error::last_os_error());
        }
        if compare == 2 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "distinct non-alias temporary name required",
            ));
        }
        self.verify()?;
        if let Some(existing) =
            directory::relative(&self.writable.file, name, Request::InspectFile)?
        {
            PrivateFileIdentity::inspect(&existing, PrivateFileKind::RegularFile)?;
        }
        let mut value = self.write_new_child(temporary, bytes)?;
        value.verify()?;
        self.verify()?;
        directory::rename(&value.file, &self.writable.file, name)?;
        let after = PrivateFileIdentity::inspect(&value.file, PrivateFileKind::RegularFile)?;
        if !value.identity.same_object_security(&after) {
            return Err(indeterminate());
        }
        value.name = name.to_owned();
        value.identity = after;
        self.sync_verified()?;
        value.verify()?;
        Ok(value)
    }
}

impl DirectoryInner {
    fn open_existing(path: &Path) -> io::Result<Self> {
        let (ancestors, file) = directory::walk(path)?;
        let identity = PrivateFileIdentity::inspect(&file, PrivateFileKind::Directory)?;
        let value = Self {
            file,
            identity,
            ancestors,
            path: path.to_owned(),
        };
        value.verify()?;
        Ok(value)
    }

    fn verify(&self) -> io::Result<()> {
        let (ancestors, current) = directory::walk(&self.path)?;
        if !same_ancestors(&self.ancestors, &ancestors)?
            || !self
                .identity
                .same_object_security(&PrivateFileIdentity::inspect(
                    &self.file,
                    PrivateFileKind::Directory,
                )?)
            || !self
                .identity
                .same_object_security(&PrivateFileIdentity::inspect(
                    &current,
                    PrivateFileKind::Directory,
                )?)
        {
            return Err(indeterminate());
        }
        Ok(())
    }

    fn open_child(self: &Arc<Self>, name: &OsStr) -> io::Result<PrivateFile> {
        self.verify()?;
        let file = directory::relative(&self.file, name, Request::ExistingFile)?
            .ok_or_else(|| io::Error::from(io::ErrorKind::NotFound))?;
        let identity = PrivateFileIdentity::inspect(&file, PrivateFileKind::RegularFile)?;
        let value = PrivateFile {
            file,
            kind: PrivateFileKind::RegularFile,
            identity,
            parent: self.clone(),
            name: name.to_owned(),
        };
        value.verify()?;
        Ok(value)
    }
}

impl PrivateFile {
    /// Inspect immutable facts without exposing this retained artifact's handle.
    pub fn identity(&self) -> &PrivateFileIdentity {
        &self.identity
    }
    /// Open a private file read-only with separate read-only directory custody.
    /// This constructor cannot produce a RetainedPrivateDirectory write capability.
    pub fn open_existing(path: &Path) -> io::Result<Self> {
        let parent = path.parent().ok_or_else(indeterminate)?;
        let name = path.file_name().ok_or_else(indeterminate)?;
        Arc::new(DirectoryInner::open_existing(parent)?).open_child(name)
    }

    /// Retain a read-only private directory for a complete inspection interval.
    /// This object has no directory mutation methods or writable-directory cast.
    pub fn open_directory(path: &Path) -> io::Result<Self> {
        let parent = Arc::new(DirectoryInner::open_existing(path)?);
        let file = parent.file.try_clone()?;
        let identity = PrivateFileIdentity::inspect(&file, PrivateFileKind::Directory)?;
        let value = Self {
            file,
            kind: PrivateFileKind::Directory,
            identity,
            parent,
            name: OsString::new(),
        };
        value.verify()?;
        Ok(value)
    }

    /// Verify the same held object and original namespace across the interval.
    pub fn verify(&self) -> io::Result<()> {
        self.parent.verify()?;
        if self.identity != PrivateFileIdentity::inspect(&self.file, self.kind)? {
            return Err(indeterminate());
        }
        if self.kind == PrivateFileKind::RegularFile {
            let current = directory::relative(&self.parent.file, &self.name, Request::InspectFile)?
                .ok_or_else(indeterminate)?;
            if self.identity
                != PrivateFileIdentity::inspect(&current, PrivateFileKind::RegularFile)?
            {
                return Err(indeterminate());
            }
        }
        Ok(())
    }

    /// Request a real file flush; read-only handles fail rather than claim success.
    pub fn sync_verified(&self) -> io::Result<()> {
        self.verify()?;
        self.file.sync_all()?;
        self.verify()
    }

    /// Read exact bounded bytes while preserving the original private snapshot.
    pub fn read_bounded(&self, maximum: usize) -> io::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        self.read_chunks(maximum as u64, |chunk| {
            bytes.try_reserve(chunk.len()).map_err(io::Error::other)?;
            bytes.extend_from_slice(chunk);
            Ok(())
        })?;
        Ok(bytes)
    }

    /// Stream bounded immutable chunks without exposing any underlying I/O port.
    pub fn read_chunks(
        &self,
        maximum: u64,
        mut consume: impl FnMut(&[u8]) -> io::Result<()>,
    ) -> io::Result<u64> {
        if self.kind != PrivateFileKind::RegularFile {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "directory inspection is not a byte stream",
            ));
        }
        self.verify()?;
        let length = self.file.metadata()?.len();
        if length > maximum {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "private artifact exceeds read bound",
            ));
        }
        let mut buffer = [0u8; 65536];
        let mut offset = 0u64;
        while offset < length {
            let remaining = (length - offset).min(buffer.len() as u64) as usize;
            let count = self.file.seek_read(&mut buffer[..remaining], offset)?;
            if count == 0 {
                return Err(io::Error::from(io::ErrorKind::UnexpectedEof));
            }
            consume(&buffer[..count])?;
            offset += count as u64;
        }
        let mut extra = [0u8; 1];
        if self.file.seek_read(&mut extra, offset)? != 0 {
            return Err(indeterminate());
        }
        self.verify()?;
        Ok(offset)
    }
}

impl PrivateFileIdentity {
    /// Inspect a canonical private directory through read-only retained ancestry.
    /// The returned facts cannot become a writable-directory capability.
    pub fn inspect_directory(path: &Path) -> io::Result<Self> {
        let value = DirectoryInner::open_existing(path)?;
        Ok(value.identity)
    }
}

fn same_ancestors(a: &[(File, WindowsFileId)], b: &[(File, WindowsFileId)]) -> io::Result<bool> {
    if a.len() != b.len() {
        return Ok(false);
    }
    for ((held, identity), (current, current_identity)) in a.iter().zip(b) {
        if WindowsFileId::inspect(held)? != *identity
            || WindowsFileId::inspect(current)? != *identity
            || identity != current_identity
        {
            return Ok(false);
        }
    }
    Ok(true)
}
