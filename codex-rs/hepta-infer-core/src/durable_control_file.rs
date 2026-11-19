//! Inspect the actual Linux descriptor without adding an unsafe FFI boundary.

use std::fs::File;
use std::io::Read;
use std::os::fd::AsRawFd;

use super::Error;

pub(super) fn validate_read_append(file: &File) -> Result<(), Error> {
    // These are the Linux asm-generic/x86 flag values, not portable POSIX values.
    // Reject other ABIs rather than guessing their O_APPEND bit. The ordinary
    // path-based constructor remains available on every supported platform.
    if !cfg!(any(
        target_arch = "x86",
        target_arch = "x86_64",
        target_arch = "aarch64"
    )) {
        return Err(Error::InvalidIdentity(
            "owned journal descriptor ABI is unsupported",
        ));
    }
    const O_ACCMODE: u64 = 0o3;
    const O_RDWR: u64 = 0o2;
    const O_APPEND: u64 = 0o2000;
    let path = format!("/proc/self/fdinfo/{}", file.as_raw_fd());
    let mut bytes = Vec::new();
    File::open(path)?.take(4097).read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > 4096 {
        return Err(Error::CorruptJournal(
            "invalid journal descriptor information",
        ));
    }
    let text = std::str::from_utf8(&bytes)
        .map_err(|_| Error::CorruptJournal("invalid journal descriptor information"))?;
    let mut flags = None;
    for line in text.lines() {
        if let Some(value) = line.strip_prefix("flags:") {
            if flags.is_some() {
                return Err(Error::CorruptJournal("duplicate journal descriptor flags"));
            }
            flags = Some(
                u64::from_str_radix(value.trim(), 8)
                    .map_err(|_| Error::CorruptJournal("invalid journal descriptor flags"))?,
            );
        }
    }
    let flags = flags.ok_or(Error::CorruptJournal("missing journal descriptor flags"))?;
    if flags & O_ACCMODE != O_RDWR || flags & O_APPEND == 0 {
        return Err(Error::CorruptJournal(
            "journal requires O_RDWR and O_APPEND",
        ));
    }
    Ok(())
}
