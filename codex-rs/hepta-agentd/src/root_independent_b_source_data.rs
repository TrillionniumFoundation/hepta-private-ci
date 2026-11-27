//! A single original DATA writer. This is not a learning journal or owner.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::time::Instant;

use crate::root_independent_b_source_protocol::SOURCE_BOUND;
use crate::root_independent_b_source_protocol::SourceBootstrap;

pub(super) fn write_original_source(
    file: File,
    bootstrap: &SourceBootstrap,
    bytes: &[u8],
    end: Instant,
) -> io::Result<()> {
    require_original_source_file(&file, bootstrap)?;
    if bytes.is_empty() || bytes.len() > SOURCE_BOUND || Instant::now() >= end {
        return Err(io::Error::other("bounded original source bytes required"));
    }
    file.try_lock().map_err(io::Error::other)?;
    let written = (|| {
        if file.metadata()?.len() != 0 {
            return Err(io::Error::other("original B source was already written"));
        }
        file.write_all_at(bytes, /*offset*/ 0)?;
        file.sync_all()?;
        for _ in 0..2 {
            require_original_source_file(&file, bootstrap)?;
            let before = file.metadata()?;
            let mut observed = vec![0; bytes.len()];
            file.read_exact_at(&mut observed, /*offset*/ 0)?;
            let after = file.metadata()?;
            if observed != bytes
                || before.len() != bytes.len() as u64
                || stamp(&before) != stamp(&after)
                || Instant::now() >= end
            {
                return Err(io::Error::other("original B source changed during write"));
            }
        }
        Ok(())
    })();
    let unlocked = file.unlock();
    // Ownership is consumed even on partial I/O. There is no retry writer or
    // truncate/repair path, and Root cannot mistake those bytes for admission.
    drop(file);
    written?;
    unlocked
}

pub(crate) fn require_original_source_file(
    file: &File,
    bootstrap: &SourceBootstrap,
) -> io::Result<()> {
    let metadata = file.metadata()?;
    // SAFETY: F_GETFL observes this actual owned descriptor's access flags.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    if flags < 0 {
        return Err(io::Error::last_os_error());
    }
    if flags & libc::O_ACCMODE != libc::O_RDWR
        || flags & (libc::O_PATH | libc::O_APPEND) != 0
        || !metadata.is_file()
        || metadata.uid() != 0
        || metadata.mode() & 0o7777 != 0o600
        || metadata.nlink() != 1
        || metadata.dev() != bootstrap.source_device
        || metadata.ino() != bootstrap.source_inode
        || metadata.len() > SOURCE_BOUND as u64
    {
        return Err(io::Error::other(
            "original Root source DATA descriptor differs",
        ));
    }
    Ok(())
}

fn stamp(meta: &std::fs::Metadata) -> (u64, i64, i64, i64, i64) {
    (
        meta.len(),
        meta.mtime(),
        meta.mtime_nsec(),
        meta.ctime(),
        meta.ctime_nsec(),
    )
}
