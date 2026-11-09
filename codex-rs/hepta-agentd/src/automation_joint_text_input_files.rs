//! Private Linux directory-fd custody. No caller-controlled path is interpreted
//! relative to the process cwd, and failures leave partial original files intact.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::Metadata;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

use codex_hepta_automation::JointTextRootIdentityV1;
use rustix::fs::Mode;
use rustix::fs::OFlags;

#[derive(Clone, Debug, Eq, PartialEq)]
struct DirectoryIdentity {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
}

impl DirectoryIdentity {
    fn read(metadata: &Metadata) -> io::Result<Self> {
        if !metadata.is_dir()
            || metadata.uid() != rustix::process::geteuid().as_raw()
            || metadata.mode() & 0o7777 != 0o700
        {
            return invalid("Joint input directory must be owned and private");
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct FileIdentity {
    device: u64,
    inode: u64,
    uid: u32,
    gid: u32,
    mode: u32,
    bytes: u64,
    mtime: (i64, i64),
    ctime: (i64, i64),
}

impl FileIdentity {
    fn read(metadata: &Metadata, maximum: usize) -> io::Result<Self> {
        if !metadata.is_file()
            || metadata.uid() != rustix::process::geteuid().as_raw()
            || metadata.mode() & 0o7777 != 0o600
            || metadata.nlink() != 1
            || metadata.len() == 0
            || metadata.len() > maximum as u64
        {
            return invalid("Joint input must be a bounded private single-link regular file");
        }
        Ok(Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            uid: metadata.uid(),
            gid: metadata.gid(),
            mode: metadata.mode(),
            bytes: metadata.len(),
            mtime: (metadata.mtime(), metadata.mtime_nsec()),
            ctime: (metadata.ctime(), metadata.ctime_nsec()),
        })
    }
}

pub(super) struct Directory {
    file: File,
    identity: DirectoryIdentity,
}

pub(super) enum Creation {
    Created,
    Existing,
}

impl Directory {
    pub(super) fn open_root(path: &Path, expected: &JointTextRootIdentityV1) -> io::Result<Self> {
        expected.validate().map_err(io::Error::other)?;
        if !path.is_absolute() || path.canonicalize()? != path {
            return invalid("Joint input root must already exist at its canonical path");
        }
        let file: File = rustix::fs::open(path, directory_flags(), Mode::empty())?.into();
        let identity = DirectoryIdentity::read(&file.metadata()?)?;
        if (identity.device, identity.inode, identity.uid)
            != (expected.device, expected.inode, expected.uid)
        {
            return invalid("Joint root differs from the admitted deployment identity");
        }
        let value = Self { file, identity };
        value.verify_root(path)?;
        Ok(value)
    }

    pub(super) fn verify_root(&self, path: &Path) -> io::Result<()> {
        let named = std::fs::symlink_metadata(path)?;
        if path.canonicalize()? != path
            || named.file_type().is_symlink()
            || DirectoryIdentity::read(&named)? != self.identity
        {
            return invalid("Joint input root name changed");
        }
        self.verify()
    }

    pub(super) fn open(&self, name: &str) -> io::Result<Self> {
        component(name)?;
        self.verify()?;
        let file: File =
            rustix::fs::openat(&self.file, name, directory_flags(), Mode::empty())?.into();
        let identity = DirectoryIdentity::read(&file.metadata()?)?;
        Ok(Self { file, identity })
    }

    pub(super) fn create(&self, name: &str) -> io::Result<(Self, Creation)> {
        component(name)?;
        self.verify()?;
        let creation = match rustix::fs::mkdirat(&self.file, name, Mode::from_bits_truncate(0o700))
        {
            Ok(()) => {
                self.file.sync_all()?;
                Creation::Created
            }
            Err(rustix::io::Errno::EXIST) => Creation::Existing,
            Err(error) => return Err(error.into()),
        };
        Ok((self.open(name)?, creation))
    }

    pub(super) fn verify_child(&self, name: &str, child: &Self) -> io::Result<()> {
        child.verify()?;
        if self.open(name)?.identity != child.identity {
            return invalid("Joint input directory was replaced");
        }
        Ok(())
    }

    pub(super) fn write_new(&self, name: &str, bytes: &[u8]) -> io::Result<()> {
        component(name)?;
        self.verify()?;
        if bytes.is_empty() {
            return invalid("Joint input file must not be empty");
        }
        let mut file: File = rustix::fs::openat(
            &self.file,
            name,
            OFlags::WRONLY
                | OFlags::CREATE
                | OFlags::EXCL
                | OFlags::NOFOLLOW
                | OFlags::NONBLOCK
                | OFlags::CLOEXEC,
            Mode::from_bits_truncate(0o600),
        )?
        .into();
        file.write_all(bytes)?;
        file.sync_all()?;
        FileIdentity::read(&file.metadata()?, bytes.len())?;
        self.file.sync_all()?;
        Ok(())
    }

    pub(super) fn read(&self, name: &str, maximum: usize) -> io::Result<ObservedFile> {
        let mut file = self.open_file(name)?;
        let before = FileIdentity::read(&file.metadata()?, maximum)?;
        let length = usize::try_from(before.bytes).map_err(io::Error::other)?;
        let mut bytes = vec![0; length];
        file.read_exact(&mut bytes)?;
        let mut extra = [0];
        if file.read(&mut extra)? != 0 {
            return invalid("Joint input grew while reading");
        }
        let observed = ObservedFile {
            file,
            before,
            bytes,
        };
        observed.verify(self, name)?;
        Ok(observed)
    }

    pub(super) fn exact_files(&self, expected: &[&str]) -> io::Result<()> {
        self.verify()?;
        // This fixed Linux proc path refers only to our held CLOEXEC directory
        // descriptor; no task path or ambient repository path reaches read_dir.
        let path = format!("/proc/self/fd/{}", self.file.as_raw_fd());
        let mut actual = BTreeSet::new();
        for entry in std::fs::read_dir(path)? {
            let entry = entry?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| io::Error::other("non-UTF8 Joint input name"))?;
            if !expected.contains(&name.as_str())
                || !actual.insert(name)
                || actual.len() > expected.len()
            {
                return invalid("Joint input directory contains unexpected entries");
            }
        }
        if actual != expected.iter().map(|name| (*name).to_owned()).collect() {
            return invalid("Joint input directory is incomplete");
        }
        Ok(())
    }

    fn verify(&self) -> io::Result<()> {
        if DirectoryIdentity::read(&self.file.metadata()?)? != self.identity {
            return invalid("Joint input held directory changed");
        }
        Ok(())
    }

    fn open_file(&self, name: &str) -> io::Result<File> {
        component(name)?;
        self.verify()?;
        Ok(rustix::fs::openat(
            &self.file,
            name,
            OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
            Mode::empty(),
        )?
        .into())
    }
}

pub(super) struct ObservedFile {
    file: File,
    before: FileIdentity,
    pub(super) bytes: Vec<u8>,
}

impl ObservedFile {
    pub(super) fn verify(&self, directory: &Directory, name: &str) -> io::Result<()> {
        let maximum = self.bytes.len();
        if FileIdentity::read(&self.file.metadata()?, maximum)? != self.before
            || FileIdentity::read(&directory.open_file(name)?.metadata()?, maximum)? != self.before
        {
            return invalid("Joint input file identity changed");
        }
        Ok(())
    }
}

fn directory_flags() -> OFlags {
    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC
}

fn component(name: &str) -> io::Result<()> {
    if name.is_empty()
        || name == "."
        || name == ".."
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return invalid("invalid fixed Joint input component");
    }
    Ok(())
}

pub(super) fn invalid<T>(message: &str) -> io::Result<T> {
    Err(io::Error::new(io::ErrorKind::InvalidData, message))
}
