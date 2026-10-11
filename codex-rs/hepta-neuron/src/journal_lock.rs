//! Own an acquired lock immediately, including constructor/recovery failures.
//! Cloned or inherited application handles remain unsupported; normal owner
//! exit releases this open description without weakening contender exclusion.

use std::fs::File;
use std::fs::TryLockError;
use std::ops::Deref;
use std::ops::DerefMut;

use crate::JournalError;

pub(crate) struct LockedFile(File);

impl LockedFile {
    pub(crate) fn acquire(file: File) -> Result<Self, JournalError> {
        if !file.metadata()?.is_file() {
            return Err(JournalError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(JournalError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for LockedFile {
    type Target = File;
    fn deref(&self) -> &File {
        &self.0
    }
}

impl DerefMut for LockedFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}

impl Drop for LockedFile {
    fn drop(&mut self) {
        // Never acknowledge durability here. Commit already synchronizes data.
        // File closure remains the fallback when this best-effort unlock fails.
        let _ = self.0.unlock();
    }
}
