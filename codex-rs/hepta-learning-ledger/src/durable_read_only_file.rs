//! A shared lock on an independently opened, immutable original descriptor.

use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;

use rustix::fs::OFlags;
use rustix::fs::fcntl_getfl;

use crate::DurableLedgerError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FileStamp {
    device: u64,
    inode: u64,
    owner: u32,
    group: u32,
    mode: u32,
    links: u64,
    length: u64,
    modified: (i64, i64),
    changed: (i64, i64),
}

pub(super) struct ReadOnlyFile {
    file: File,
    original: FileStamp,
    maximum: u64,
}

impl ReadOnlyFile {
    pub(super) fn acquire(file: File, maximum: u64) -> Result<Self, DurableLedgerError> {
        let original = stamp(&file)?;
        if original.length > maximum {
            return Err(DurableLedgerError::Capacity);
        }
        match file.try_lock_shared() {
            Ok(()) => (),
            Err(TryLockError::WouldBlock) => return Err(DurableLedgerError::Busy),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }
        // Only a successfully acquired lock gets a Drop guard. An unsuccessful
        // attempt must never release an original writer's lock through an alias.
        let retained = Self {
            file,
            original,
            maximum,
        };
        if stamp(&retained.file)? != original {
            return Err(DurableLedgerError::Indeterminate);
        }
        Ok(retained)
    }

    pub(super) fn identity(&self) -> (u64, u64) {
        (self.original.device, self.original.inode)
    }

    pub(super) fn read_image(&self) -> Result<Vec<u8>, DurableLedgerError> {
        let before = stamp(&self.file)?;
        if before != self.original {
            return Err(DurableLedgerError::Indeterminate);
        }
        if before.length > self.maximum {
            return Err(DurableLedgerError::Capacity);
        }
        let length = usize::try_from(before.length).map_err(|_| DurableLedgerError::Capacity)?;
        let mut bytes = vec![0; length];
        self.file
            .read_exact_at(&mut bytes, /*offset*/ 0)
            .map_err(|_| DurableLedgerError::Indeterminate)?;
        if stamp(&self.file)? != before {
            return Err(DurableLedgerError::Indeterminate);
        }
        Ok(bytes)
    }
}

impl Drop for ReadOnlyFile {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

fn stamp(file: &File) -> Result<FileStamp, DurableLedgerError> {
    let flags = fcntl_getfl(file).map_err(io::Error::from)?;
    if flags & OFlags::ACCMODE != OFlags::RDONLY {
        return Err(DurableLedgerError::Io(io::ErrorKind::PermissionDenied));
    }
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(DurableLedgerError::NotRegular);
    }
    if metadata.nlink() != 1 {
        return Err(DurableLedgerError::Indeterminate);
    }
    Ok(FileStamp {
        device: metadata.dev(),
        inode: metadata.ino(),
        owner: metadata.uid(),
        group: metadata.gid(),
        mode: metadata.mode(),
        links: metadata.nlink(),
        length: metadata.len(),
        modified: (metadata.mtime(), metadata.mtime_nsec()),
        changed: (metadata.ctime(), metadata.ctime_nsec()),
    })
}
