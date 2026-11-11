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

/// Inspect only the original owner's file, retaining its lock and cursor.
#[derive(Debug)]
#[cfg(any(test, feature = "qualification-owned-file-read"))]
pub(crate) enum QualificationFileReadError {
    InvalidLimit,
    Capacity,
    Io(std::io::Error),
}

#[cfg(any(test, feature = "qualification-owned-file-read"))]
impl From<std::io::Error> for QualificationFileReadError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

#[cfg(any(test, feature = "qualification-owned-file-read"))]
pub(crate) fn qualification_file_bytes(
    file: &mut File,
    max_bytes: usize,
) -> Result<Vec<u8>, QualificationFileReadError> {
    use std::io::Read;
    use std::io::Seek;
    use std::io::SeekFrom;

    if !(1..=1024 * 1024).contains(&max_bytes) {
        return Err(QualificationFileReadError::InvalidLimit);
    }
    let position = file.stream_position()?;
    let read = (|| {
        let length = file.metadata()?.len();
        if length > max_bytes as u64 {
            return Err(QualificationFileReadError::Capacity);
        }
        file.rewind()?;
        let mut bytes = vec![0; length as usize];
        file.read_exact(&mut bytes)?;
        let mut extra = [0];
        if file.read(&mut extra)? != 0 || file.metadata()?.len() != length {
            return Err(std::io::Error::other("qualification file length changed").into());
        }
        Ok(bytes)
    })();
    // Attempt restoration even after read failure; never hide its failure
    // behind either successfully read bytes or a cached logical snapshot.
    file.seek(SeekFrom::Start(position))?;
    read
}

#[cfg(test)]
#[path = "journal_lock_qualification_tests.rs"]
mod qualification_tests;
