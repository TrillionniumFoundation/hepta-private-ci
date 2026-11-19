//! A preheld, private material file. Its bytes are data; the same Root
//! enrollment still authenticates the decision, selection and actual owners.

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use super::super::files::OriginalFile;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct MaterialData {
    pub(crate) path: PathBuf,
    pub(crate) device: u64,
    pub(crate) inode: u64,
    pub(crate) uid: u32,
    pub(crate) gid: u32,
    pub(crate) mode: u32,
}

pub(super) struct RetainedMaterial {
    original: OriginalFile,
    expected: MaterialData,
}

/// Holds a distinct shared-lock description across actual Root enrollment.
pub(super) struct MaterialObservation<'a> {
    held: &'a RetainedMaterial,
    file: File,
    stamp: (u64, i64, i64, i64, i64),
    bytes: Vec<u8>,
}

impl RetainedMaterial {
    pub(super) fn original_data(&self) -> io::Result<MaterialData> {
        self.require_original()?;
        Ok(self.expected.clone())
    }

    pub(super) fn open_original(expected: MaterialData, uid: u32, gid: u32) -> io::Result<Self> {
        if uid == 0
            || gid == 0
            || (expected.uid, expected.gid, expected.mode) != (uid, gid, 0o100600)
            || expected.device == 0
            || expected.inode == 0
        {
            return Err(io::Error::other(
                "original private publication material required",
            ));
        }
        let held = Self {
            original: OriginalFile::open_original(&expected.path)?,
            expected,
        };
        held.require_original()?;
        Ok(held)
    }

    pub(super) fn require_original(&self) -> io::Result<()> {
        self.original.require_original_file()?;
        let file = self.original.original_descriptor()?;
        self.require_descriptor(&file)
    }

    pub(super) fn require_distinct(&self, other: &OriginalFile) -> io::Result<()> {
        let metadata = other.original_descriptor()?.metadata()?;
        if (metadata.dev(), metadata.ino()) == (self.expected.device, self.expected.inode) {
            return Err(io::Error::other(
                "publication material aliases an original owner",
            ));
        }
        self.require_original()
    }

    pub(super) fn original_readonly_description(&self) -> io::Result<File> {
        self.require_original()?;
        let original = self.original.original_descriptor()?;
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(format!("/proc/self/fd/{}", original.as_raw_fd()))?;
        self.require_descriptor(&file)?;
        Ok(file)
    }

    pub(super) fn observe_ready(&self) -> io::Result<Option<MaterialObservation<'_>>> {
        self.require_original()?;
        let original = self.original.original_descriptor()?;
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NONBLOCK)
            .open(format!("/proc/self/fd/{}", original.as_raw_fd()))?;
        self.require_descriptor(&file)?;
        match file.try_lock_shared() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Ok(None),
            Err(error) => return Err(io::Error::other(error)),
        }
        let metadata = file.metadata()?;
        if metadata.len() == 0 {
            self.require_descriptor(&file)?;
            return Ok(None);
        }
        if metadata.len() > 65_536 {
            return Err(io::Error::other(
                "original publication material exceeds bound",
            ));
        }
        let stamp = (
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        );
        let mut bytes = vec![0; metadata.len() as usize];
        file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        let observed = MaterialObservation {
            held: self,
            file,
            stamp,
            bytes,
        };
        observed.require_unchanged()?;
        Ok(Some(observed))
    }

    fn require_descriptor(&self, file: &File) -> io::Result<()> {
        self.original.require_original_file()?;
        let actual = file.metadata()?;
        if !actual.is_file()
            || actual.nlink() != 1
            || (
                actual.dev(),
                actual.ino(),
                actual.uid(),
                actual.gid(),
                actual.mode(),
            ) != (
                self.expected.device,
                self.expected.inode,
                self.expected.uid,
                self.expected.gid,
                self.expected.mode,
            )
        {
            return Err(io::Error::other(
                "original publication material custody changed",
            ));
        }
        self.original.require_original_file()
    }
}

impl MaterialObservation<'_> {
    pub(super) fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub(super) fn require_unchanged(&self) -> io::Result<()> {
        self.held.require_descriptor(&self.file)?;
        for _ in 0..2 {
            let metadata = self.file.metadata()?;
            if (
                metadata.len(),
                metadata.mtime(),
                metadata.mtime_nsec(),
                metadata.ctime(),
                metadata.ctime_nsec(),
            ) != self.stamp
            {
                return Err(io::Error::other(
                    "original publication material cut changed",
                ));
            }
            let mut bytes = vec![0; self.bytes.len()];
            self.file.read_exact_at(&mut bytes, /*offset*/ 0)?;
            if bytes != self.bytes {
                return Err(io::Error::other(
                    "original publication material bytes changed",
                ));
            }
            let after = self.file.metadata()?;
            if (
                after.len(),
                after.mtime(),
                after.mtime_nsec(),
                after.ctime(),
                after.ctime_nsec(),
            ) != self.stamp
            {
                return Err(io::Error::other(
                    "original publication material changed during read",
                ));
            }
        }
        self.held.require_descriptor(&self.file)
    }
}
