//! Qualification observes the locked descriptor without a second file handle.

use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

use super::LockedFileCasErrorV1;
use super::LockedFileFinalHoldoutCasStoreV1;
use super::io_error;

impl LockedFileFinalHoldoutCasStoreV1 {
    /// Read physical bytes through the retained owner, bounded to at most 1 MiB.
    /// The lock remains held and the cursor is restored, including on failure.
    /// An I/O or consistency error poisons this store; cached state is not used.
    pub fn qualification_file_bytes(
        &mut self,
        max_bytes: usize,
    ) -> Result<Vec<u8>, LockedFileCasErrorV1> {
        if !(1..=1024 * 1024).contains(&max_bytes) {
            return Err(LockedFileCasErrorV1::Capacity);
        }
        let observed = (|| {
            let position = self.file.stream_position().map_err(io_error)?;
            let read = (|| {
                let length = self.file.metadata().map_err(io_error)?.len();
                if length > max_bytes as u64 {
                    return Err(LockedFileCasErrorV1::Capacity);
                }
                self.file.rewind().map_err(io_error)?;
                let mut bytes = vec![0; length as usize];
                self.file.read_exact(&mut bytes).map_err(io_error)?;
                let mut extra = [0];
                if self.file.read(&mut extra).map_err(io_error)? != 0
                    || self.file.metadata().map_err(io_error)?.len() != length
                {
                    return Err(LockedFileCasErrorV1::Corrupt);
                }
                Ok(bytes)
            })();
            self.file
                .seek(SeekFrom::Start(position))
                .map_err(io_error)?;
            read
        })();
        if observed.is_err() {
            self.poisoned = true;
        }
        observed
    }
}
