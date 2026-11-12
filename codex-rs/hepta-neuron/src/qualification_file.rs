//! Bounded inspection through a mutable borrow of the original owned file.
//! No reopen, duplicated descriptor, lock transition, or durable mutation.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

pub(crate) const MAXIMUM_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Debug)]
pub(crate) enum FileBytesError {
    Capacity,
    Io(io::Error),
}

impl From<io::Error> for FileBytesError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

pub(crate) fn file_bytes(file: &mut File, maximum_bytes: u64) -> Result<Vec<u8>, FileBytesError> {
    if maximum_bytes == 0 || maximum_bytes > MAXIMUM_BYTES {
        return Err(FileBytesError::Capacity);
    }
    if file.metadata()?.len() > maximum_bytes {
        return Err(FileBytesError::Capacity);
    }
    let cursor = file.stream_position()?;
    let observed = (|| {
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        (&mut *file)
            .take(maximum_bytes + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > maximum_bytes {
            return Err(FileBytesError::Capacity);
        }
        if file.metadata()?.len() != bytes.len() as u64 {
            return Err(io::Error::other("qualification file changed during inspection").into());
        }
        Ok(bytes)
    })();
    // Restore even when the read failed, and never acknowledge a failed restore.
    match file.seek(SeekFrom::Start(cursor)) {
        Ok(position) if position == cursor => observed,
        Ok(_) => Err(io::Error::other("qualification file cursor was not restored").into()),
        Err(error) => Err(error.into()),
    }
}
