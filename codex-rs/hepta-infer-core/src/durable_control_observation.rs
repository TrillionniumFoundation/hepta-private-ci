//! Qualification reads the original locked control file, never its pathname.

use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

use super::DurableInferenceControl;
use super::Error;

impl DurableInferenceControl {
    /// Read at most 1 MiB through the retained descriptor and restore its cursor.
    /// Failure poisons the owner; successful observation cannot clear poison.
    pub fn qualification_file_bytes(&mut self, max_bytes: usize) -> Result<Vec<u8>, Error> {
        if !(1..=1024 * 1024).contains(&max_bytes) {
            return Err(Error::CapacityExceeded);
        }
        let observed = (|| {
            let position = self.file.stream_position()?;
            let read = (|| {
                let length = self.file.metadata()?.len();
                if length > max_bytes as u64 {
                    return Err(Error::CapacityExceeded);
                }
                self.file.rewind()?;
                let mut bytes = vec![0; length as usize];
                self.file.read_exact(&mut bytes)?;
                let mut extra = [0];
                if self.file.read(&mut extra)? != 0 || self.file.metadata()?.len() != length {
                    return Err(Error::CorruptJournal("file changed during observation"));
                }
                Ok(bytes)
            })();
            self.file.seek(SeekFrom::Start(position))?;
            read
        })();
        if observed.is_err() {
            self.poisoned = true;
        }
        observed
    }
}
