//! Existing Root control records are observed before opening the generic store.
//! Its lock open may use O_CREAT; a missing original lock must never be repaired
//! by this history path. Only the existing successor CAS may replace its record.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

type Stamp = (u64, u64, u64, i64, i64, i64, i64);

struct OriginalControlFile {
    path: PathBuf,
    file: File,
    stamp: Stamp,
    bytes: Vec<u8>,
}

impl OriginalControlFile {
    fn stamp(metadata: &std::fs::Metadata) -> io::Result<Stamp> {
        if !metadata.is_file()
            || metadata.uid() != 0
            || metadata.mode() & 0o7777 != 0o600
            || metadata.nlink() != 1
            || metadata.len() > 16 * 1024
        {
            return Err(io::Error::other(
                "existing bounded Root control file required",
            ));
        }
        Ok((
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        ))
    }

    fn open(path: PathBuf) -> io::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&path)?;
        let stamp = Self::stamp(&file.metadata()?)?;
        let mut bytes = vec![0; usize::try_from(stamp.2).map_err(io::Error::other)?];
        file.read_exact_at(&mut bytes, /*offset*/ 0)?;
        let held = Self {
            path,
            file,
            stamp,
            bytes,
        };
        held.require_unchanged()?;
        Ok(held)
    }

    fn require_unchanged(&self) -> io::Result<()> {
        for _ in 0..2 {
            if Self::stamp(&std::fs::symlink_metadata(&self.path)?)? != self.stamp
                || Self::stamp(&self.file.metadata()?)? != self.stamp
            {
                return Err(io::Error::other("original Root control file changed"));
            }
            let mut bytes = vec![0; self.bytes.len()];
            self.file.read_exact_at(&mut bytes, /*offset*/ 0)?;
            if bytes != self.bytes
                || Self::stamp(&self.file.metadata()?)? != self.stamp
                || Self::stamp(&std::fs::symlink_metadata(&self.path)?)? != self.stamp
            {
                return Err(io::Error::other("original Root control bytes changed"));
            }
        }
        Ok(())
    }
}

pub(crate) struct OriginalControlRecord {
    primary: OriginalControlFile,
    lock: OriginalControlFile,
}

impl OriginalControlRecord {
    pub(crate) fn open(root: &Path, owner: &str) -> io::Result<Self> {
        super::original_root()?;
        let name = format!("frontier-v1-{}.json", Digest32::of_bytes(owner.as_bytes()));
        let held = Self {
            primary: OriginalControlFile::open(root.join(&name))?,
            lock: OriginalControlFile::open(root.join(format!("{name}.lock")))?,
        };
        held.require_unchanged()?;
        Ok(held)
    }

    pub(crate) fn require_unchanged(&self) -> io::Result<()> {
        self.primary.require_unchanged()?;
        self.lock.require_unchanged()
    }

    pub(crate) fn require_original_lock(&self) -> io::Result<()> {
        self.lock.require_unchanged()
    }
}
