//! Bounded qualification observations through an owner's original file handle.
//! The caller keeps its exclusive borrow and OS lock throughout the read.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

#[derive(Debug)]
pub(crate) enum ObservationError {
    Capacity,
    Io(io::Error),
}

impl From<io::Error> for ObservationError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

pub(crate) fn read(file: &mut File, maximum_bytes: u64) -> Result<Vec<u8>, ObservationError> {
    if maximum_bytes == 0 || maximum_bytes > 8 * 1024 * 1024 {
        return Err(ObservationError::Capacity);
    }
    if file.metadata()?.len() > maximum_bytes {
        return Err(ObservationError::Capacity);
    }
    let position = file.stream_position()?;
    let observed = (|| {
        file.rewind()?;
        let mut bytes = Vec::new();
        (&mut *file)
            .take(maximum_bytes + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > maximum_bytes {
            return Err(ObservationError::Capacity);
        }
        Ok(bytes)
    })();
    // Restoration also runs after failed reads; its failure cannot be hidden
    // behind successful bytes or an earlier read error.
    file.seek(SeekFrom::Start(position))?;
    observed
}

#[cfg(test)]
#[path = "qualification_file_observation_tests.rs"]
mod tests;
