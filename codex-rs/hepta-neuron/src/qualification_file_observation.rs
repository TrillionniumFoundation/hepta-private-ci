//! Bounded qualification reads through a borrowed, already locked file.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;

pub(crate) fn read(file: &mut File, maximum_bytes: u64) -> io::Result<Vec<u8>> {
    if maximum_bytes == 0 || maximum_bytes > 8 * 1024 * 1024 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid observation limit",
        ));
    }
    if file.metadata()?.len() > maximum_bytes {
        return Err(io::Error::other("file observation exceeds limit"));
    }
    let position = file.stream_position()?;
    let read = (|| {
        file.rewind()?;
        let mut bytes = Vec::new();
        (&mut *file)
            .take(maximum_bytes + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > maximum_bytes {
            return Err(io::Error::other("file observation exceeds limit"));
        }
        Ok(bytes)
    })();
    // Restore after every attempted read. A restoration error is never success.
    file.seek(SeekFrom::Start(position))?;
    read
}
