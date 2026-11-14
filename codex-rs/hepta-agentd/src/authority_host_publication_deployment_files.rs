//! Retained read-only files for the Root deployment loader. Paths are locators;
//! an opened descriptor and its original private directory remain authoritative.

use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_types::Digest32;

const METADATA_BOUND: u64 = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
struct Identity {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
    links: u64,
}

impl Identity {
    fn from_metadata(metadata: &Metadata) -> Self {
        Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
            links: if metadata.is_dir() {
                0
            } else {
                metadata.nlink()
            },
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Stamp {
    identity: Identity,
    length: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

impl Stamp {
    fn from_metadata(metadata: &Metadata) -> Self {
        Self {
            identity: Identity::from_metadata(metadata),
            length: metadata.len(),
            modified: (metadata.mtime(), metadata.mtime_nsec()),
            changed: (metadata.ctime(), metadata.ctime_nsec()),
        }
    }
}

pub(in crate::authority_host_runtime::session) struct DirectoryPin {
    path: PathBuf,
    identity: Identity,
    file: File,
    root_owned: bool,
}

impl DirectoryPin {
    pub(in crate::authority_host_runtime::session) fn capture_root(
        path: &Path,
    ) -> io::Result<Self> {
        RootAuthorityDirectory::open(path).map_err(io::Error::other)?;
        let mut pin = Self::capture_private(path)?;
        if pin.identity.uid != 0 || pin.identity.mode & 0o077 != 0 {
            return Err(io::Error::other(
                "original Root deployment directory required",
            ));
        }
        pin.root_owned = true;
        Ok(pin)
    }

    pub(in crate::authority_host_runtime::session) fn capture_private(
        path: &Path,
    ) -> io::Result<Self> {
        require_absolute(path)?;
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_dir()
            || metadata.mode() & 0o022 != 0
            || std::fs::canonicalize(path)? != path
        {
            return Err(io::Error::other(
                "original private deployment directory required",
            ));
        }
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)?;
        let identity = Identity::from_metadata(&metadata);
        if Identity::from_metadata(&file.metadata()?) != identity {
            return Err(io::Error::other(
                "original directory changed during capture",
            ));
        }
        Ok(Self {
            path: path.to_owned(),
            identity,
            file,
            root_owned: false,
        })
    }

    pub(in crate::authority_host_runtime::session) fn require_directory(&self) -> io::Result<()> {
        if self.root_owned {
            RootAuthorityDirectory::open(&self.path).map_err(io::Error::other)?;
        }
        let metadata = std::fs::symlink_metadata(&self.path)?;
        if !metadata.is_dir()
            || Identity::from_metadata(&metadata) != self.identity
            || Identity::from_metadata(&self.file.metadata()?) != self.identity
            || std::fs::canonicalize(&self.path)? != self.path
        {
            return Err(io::Error::other("original deployment directory replaced"));
        }
        Ok(())
    }
}

pub(in crate::authority_host_runtime::session) struct MetadataFile {
    path: PathBuf,
    parent: DirectoryPin,
    file: File,
    stamp: Stamp,
    digest: Digest32,
}

impl MetadataFile {
    pub(in crate::authority_host_runtime::session) fn open_metadata(
        path: &Path,
    ) -> io::Result<(Self, Vec<u8>)> {
        require_absolute(path)?;
        let parent = DirectoryPin::capture_root(parent(path)?)?;
        let file = open_readonly(path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.mode() & 0o7777 != 0o600
            || metadata.nlink() != 1
            || metadata.len() == 0
            || metadata.len() > METADATA_BOUND
        {
            return Err(io::Error::other(
                "bounded Root0600 single-link metadata required",
            ));
        }
        let stamp = Stamp::from_metadata(&metadata);
        let mut bytes = vec![0; metadata.len() as usize];
        file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        let held = Self {
            path: path.to_owned(),
            parent,
            file,
            stamp,
            digest: Digest32::of_bytes(&bytes),
        };
        held.require_metadata_unchanged()?;
        Ok((held, bytes))
    }

    pub(in crate::authority_host_runtime::session) fn digest(&self) -> Digest32 {
        self.digest
    }

    pub(in crate::authority_host_runtime::session) fn require_metadata_unchanged(
        &self,
    ) -> io::Result<()> {
        self.parent.require_directory()?;
        let path = std::fs::symlink_metadata(&self.path)?;
        if !path.is_file()
            || Stamp::from_metadata(&path) != self.stamp
            || Stamp::from_metadata(&self.file.metadata()?) != self.stamp
        {
            return Err(io::Error::other(
                "original Root metadata file replaced or changed",
            ));
        }
        let mut bytes = vec![0; self.stamp.length as usize];
        self.file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        if Digest32::of_bytes(&bytes) != self.digest
            || Stamp::from_metadata(&self.file.metadata()?) != self.stamp
            || Stamp::from_metadata(&std::fs::symlink_metadata(&self.path)?) != self.stamp
        {
            return Err(io::Error::other(
                "original Root metadata bytes or path changed",
            ));
        }
        self.parent.require_directory()?;
        Ok(())
    }
}

/// Journal bytes may advance normally. Their original descriptor and parent
/// cannot be replaced; the original owner verifies private custody and the cut.
pub(in crate::authority_host_runtime::session) struct OriginalFile {
    path: PathBuf,
    parent: DirectoryPin,
    file: File,
    identity: Identity,
}

impl OriginalFile {
    pub(in crate::authority_host_runtime::session) fn open_original(
        path: &Path,
    ) -> io::Result<Self> {
        require_absolute(path)?;
        let parent = DirectoryPin::capture_private(parent(path)?)?;
        let file = open_readonly(path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file() || metadata.nlink() != 1 || metadata.mode() & 0o022 != 0 {
            return Err(io::Error::other(
                "original single-link material must reject unrelated writers",
            ));
        }
        let held = Self {
            path: path.to_owned(),
            parent,
            identity: Identity::from_metadata(&metadata),
            file,
        };
        held.require_original_file()?;
        Ok(held)
    }

    pub(in crate::authority_host_runtime::session) fn original_descriptor(
        &self,
    ) -> io::Result<File> {
        self.require_original_file()?;
        self.file.try_clone()
    }

    pub(in crate::authority_host_runtime::session) fn require_original_file(
        &self,
    ) -> io::Result<()> {
        self.parent.require_directory()?;
        let path = std::fs::symlink_metadata(&self.path)?;
        if !path.is_file()
            || Identity::from_metadata(&path) != self.identity
            || Identity::from_metadata(&self.file.metadata()?) != self.identity
        {
            return Err(io::Error::other(
                "original material path or descriptor replaced",
            ));
        }
        self.parent.require_directory()?;
        Ok(())
    }
}

pub(in crate::authority_host_runtime::session) fn require_absolute(path: &Path) -> io::Result<()> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
        || path.as_os_str().as_encoded_bytes().len() > 4096
    {
        return Err(io::Error::other("bounded absolute original path required"));
    }
    Ok(())
}

pub(in crate::authority_host_runtime::session) fn parent(path: &Path) -> io::Result<&Path> {
    path.parent()
        .ok_or_else(|| io::Error::other("original path parent required"))
}

fn open_readonly(path: &Path) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
}
