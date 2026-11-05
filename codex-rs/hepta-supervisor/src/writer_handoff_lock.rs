use super::WriterHandoffErrorV1;

use std::fs::File;
use std::fs::TryLockError;
use std::ops::Deref;
use std::ops::DerefMut;

/// Own one successfully acquired journal lock for exactly this logical owner.
///
/// Competing writers must independently open their files. A copied or inherited
/// descriptor is not an independent lock owner, and advisory locking does not
/// replace the domain writer's durable generation fence.
#[derive(Debug)]
pub(super) struct LockedHandoffFile {
    file: File,
    // Only fence destruction of a fork copy. This is not durable owner identity.
    acquiring_pid: u32,
}

impl LockedHandoffFile {
    pub(super) fn acquire(file: File) -> Result<Self, WriterHandoffErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(WriterHandoffErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self {
                file,
                acquiring_pid: std::process::id(),
            }),
            Err(TryLockError::WouldBlock) => Err(WriterHandoffErrorV1::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for LockedHandoffFile {
    type Target = File;

    fn deref(&self) -> &Self::Target {
        &self.file
    }
}

impl DerefMut for LockedHandoffFile {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.file
    }
}

impl Drop for LockedHandoffFile {
    fn drop(&mut self) {
        // Explicitly release our acquired lock, including construction errors.
        // A fork child shares the open file description: it must only close its
        // copied File, because unlocking it would release the parent's lock.
        // Drop emits no successful-release receipt.
        if std::process::id() == self.acquiring_pid {
            let _ = self.file.unlock();
        }
    }
}

#[cfg(all(test, unix))]
#[path = "writer_handoff_lock_tests.rs"]
mod tests;
