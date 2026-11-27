//! Own an acquired lock immediately, including constructor/recovery failures.
//! Cloned or inherited application handles remain unsupported; normal owner
//! exit releases this open description without weakening contender exclusion.

use std::fs::File;
use std::fs::TryLockError;
use std::ops::Deref;
use std::ops::DerefMut;

use crate::DurableLedgerError;

pub(crate) struct LockedFile(File);

impl LockedFile {
    pub(crate) fn acquire(file: File) -> Result<Self, DurableLedgerError> {
        if !file.metadata()?.is_file() {
            return Err(DurableLedgerError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableLedgerError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }

    #[cfg(any(test, feature = "qualification-legacy-write"))]
    pub(crate) fn qualification_bytes(
        &mut self,
        maximum_bytes: u64,
    ) -> Result<Vec<u8>, DurableLedgerError> {
        use std::io::Read;
        use std::io::Seek;
        use std::io::SeekFrom;

        if maximum_bytes == 0 || maximum_bytes > 8 * 1024 * 1024 {
            return Err(DurableLedgerError::InvalidLimit);
        }
        if self.0.metadata()?.len() > maximum_bytes {
            return Err(DurableLedgerError::Capacity);
        }
        let position = self.0.stream_position()?;
        let read = (|| {
            self.0.rewind()?;
            let mut bytes = Vec::new();
            (&mut self.0)
                .take(maximum_bytes + 1)
                .read_to_end(&mut bytes)?;
            if bytes.len() as u64 > maximum_bytes {
                return Err(DurableLedgerError::Capacity);
            }
            Ok(bytes)
        })();
        // Always restore after the attempted read, including read errors. A
        // restoration error is never hidden behind successfully read bytes.
        self.0.seek(SeekFrom::Start(position))?;
        read
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

#[cfg(test)]
#[path = "durable_lock_qualification_tests.rs"]
mod qualification_tests;
