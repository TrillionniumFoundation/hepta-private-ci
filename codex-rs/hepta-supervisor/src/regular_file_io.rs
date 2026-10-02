//! Descriptor-bound reads for inputs whose contract requires regular files.
//! Nonblocking open rejects special files before a FIFO can wait for a writer.

use std::fs::File;
use std::io;
use std::io::Read;
use std::path::Path;

pub(crate) fn open_regular_file(path: &Path, maximum: u64) -> io::Result<File> {
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let file = options.open(path)?;
    let opened = file.metadata()?;
    if !opened.file_type().is_file() || opened.len() > maximum {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "opened input must be a bounded regular file",
        ));
    }
    Ok(file)
}

/// Read into caller-owned storage so private key callers retain zeroization.
pub(crate) fn read_bounded(file: &mut File, bytes: &mut Vec<u8>, maximum: u64) -> io::Result<()> {
    let limit = maximum.checked_add(1).ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "regular input bound overflow")
    })?;
    file.take(limit).read_to_end(bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "regular input exceeds its byte bound",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "regular_file_io_tests.rs"]
pub(crate) mod tests;
