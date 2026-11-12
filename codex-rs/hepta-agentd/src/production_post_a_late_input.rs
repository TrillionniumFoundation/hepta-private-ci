//! Data from one pre-existing original file. Empty means pending until the
//! original end; a missing, changed or malformed file is never initialized.

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::os::fd::AsRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use tokio_util::sync::CancellationToken;

use super::OriginalFiles;
use super::post_a_remaining;
use super::refused;
use crate::AgentdError;

type Identity = (u64, u64, u32, u32, u32);
type Stamp = (u64, i64, i64, i64, i64);

pub(super) struct OriginalLateInput {
    path: PathBuf,
    file: File,
    identity: Identity,
    end: Instant,
}

/// The independent producer's shared lock is held through the consuming
/// operation and both full physical byte observations.
pub(super) struct OriginalLateValue {
    original: OriginalLateInput,
    locked: File,
    stamp: Stamp,
    bytes: Vec<u8>,
    fenced: AtomicBool,
}

struct FenceOnDrop<'a> {
    value: &'a OriginalLateValue,
    armed: bool,
}

impl Drop for FenceOnDrop<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.value.fenced.store(true, Ordering::Release);
        }
    }
}

impl OriginalLateInput {
    pub(super) fn open_original(
        path: PathBuf,
        files: &mut OriginalFiles,
        end: Instant,
    ) -> Result<Self, AgentdError> {
        post_a_remaining(end)?;
        let file = files.read(&path)?;
        let identity = identity(&file.metadata()?)?;
        let input = Self {
            path,
            file,
            identity,
            end,
        };
        input.require_original()?;
        Ok(input)
    }

    fn require_original(&self) -> Result<(), AgentdError> {
        post_a_remaining(self.end)?;
        let parent = self
            .path
            .parent()
            .ok_or_else(|| refused("late input parent missing"))?;
        if parent.canonicalize()? != parent
            || identity(&self.file.metadata()?)? != self.identity
            || identity(&std::fs::symlink_metadata(&self.path)?)? != self.identity
            || parent.canonicalize()? != parent
        {
            return Err(refused("original late input custody changed"));
        }
        post_a_remaining(self.end)?;
        Ok(())
    }

    pub(super) async fn wait_original_value(
        self,
        cancelled: &CancellationToken,
    ) -> Result<OriginalLateValue, AgentdError> {
        loop {
            if cancelled.is_cancelled() {
                return Err(refused("original late input cancelled"));
            }
            self.require_original()?;
            let locked = OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_CLOEXEC | libc::O_NONBLOCK)
                .open(format!("/proc/self/fd/{}", self.file.as_raw_fd()))?;
            if identity(&locked.metadata()?)? != self.identity {
                return Err(refused("original late input description changed"));
            }
            let acquired = match locked.try_lock_shared() {
                Ok(()) => true,
                Err(TryLockError::WouldBlock) => false,
                Err(error) => return Err(refused(error)),
            };
            if acquired {
                let physical = locked.metadata()?;
                if physical.len() > 1_048_576 {
                    return Err(refused("original late data exceeds its bound"));
                }
                if physical.len() != 0 {
                    let mut bytes = vec![0; physical.len() as usize];
                    locked.read_exact_at(&mut bytes, /*offset*/ 0)?;
                    let value = OriginalLateValue {
                        original: self,
                        locked,
                        stamp: stamp(&physical),
                        bytes,
                        fenced: AtomicBool::new(false),
                    };
                    value.require_unchanged()?;
                    return Ok(value);
                }
            }
            // Release this actual lock before waiting; retain the original FD
            // and end. Only no bytes and the producer's lock permit waiting.
            drop(locked);
            self.require_original()?;
            tokio::select! {
                _ = cancelled.cancelled() => return Err(refused("original late input cancelled")),
                _ = tokio::time::sleep(post_a_remaining(self.end)?.min(std::time::Duration::from_millis(5))) => {}
            }
        }
    }
}

impl OriginalLateValue {
    /// Parsing the producer's data is enclosed by the same two physical
    /// observations. A failed parse, changed file or panic consumes this
    /// handle's admission permanently, even if old bytes are later restored.
    pub(super) fn with_original_bytes<T>(
        &self,
        read: impl FnOnce(&[u8]) -> Result<T, AgentdError>,
    ) -> Result<T, AgentdError> {
        let mut fence = FenceOnDrop {
            value: self,
            armed: true,
        };
        Self::require_unchanged(self)?;
        let result = read(&self.bytes);
        Self::require_unchanged(self)?;
        if result.is_ok() {
            fence.armed = false;
        }
        result
    }

    pub(super) fn require_unchanged(&self) -> Result<(), AgentdError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(refused("original late value is fenced"));
        }
        let result = self.require_physical_value();
        if result.is_err() {
            self.fenced.store(true, Ordering::Release);
        }
        result
    }

    fn require_physical_value(&self) -> Result<(), AgentdError> {
        self.original.require_original()?;
        if identity(&self.locked.metadata()?)? != self.original.identity {
            return Err(refused("original late value description differs"));
        }
        for _ in 0..2 {
            if stamp(&self.locked.metadata()?) != self.stamp {
                return Err(refused("original late data changed before read"));
            }
            let mut bytes = vec![0; self.bytes.len()];
            self.locked.read_exact_at(&mut bytes, /*offset*/ 0)?;
            if bytes != self.bytes || stamp(&self.locked.metadata()?) != self.stamp {
                return Err(refused("original late data changed during read"));
            }
        }
        self.original.require_original()
    }
}

fn identity(metadata: &std::fs::Metadata) -> Result<Identity, AgentdError> {
    if !metadata.is_file()
        || metadata.nlink() != 1
        || !matches!(metadata.mode() & 0o7777, 0o400 | 0o600)
    {
        return Err(refused("original private late data required"));
    }
    Ok((
        metadata.dev(),
        metadata.ino(),
        metadata.uid(),
        metadata.gid(),
        metadata.mode(),
    ))
}

fn stamp(metadata: &std::fs::Metadata) -> Stamp {
    (
        metadata.len(),
        metadata.mtime(),
        metadata.mtime_nsec(),
        metadata.ctime(),
        metadata.ctime_nsec(),
    )
}
