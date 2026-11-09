//! Bounded private configuration observations from the opened descriptor.

use std::io;
use std::path::Path;

#[cfg(unix)]
pub(crate) fn read(path: &Path, maximum: u64) -> io::Result<Vec<u8>> {
    use std::fs::File;
    use std::io::Read;
    use std::os::unix::fs::MetadataExt;

    use rustix::fs::Mode;
    use rustix::fs::OFlags;

    if !path.is_absolute() || maximum == 0 {
        return invalid("private file must have an absolute path and a byte bound");
    }
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("private file has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| io::Error::other("private file has no name"))?;
    let directory: File = rustix::fs::open(
        parent,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    )?
    .into();
    let parent_metadata = directory.metadata()?;
    let uid = rustix::process::geteuid().as_raw();
    if parent_metadata.uid() != uid || parent_metadata.mode() & 0o022 != 0 {
        return invalid("private file parent ownership or mode is unsafe");
    }
    // NONBLOCK prevents a substituted FIFO from blocking before fstat. No
    // pre-open path observation is trusted as the opened file's identity.
    let mut file: File = rustix::fs::openat(
        &directory,
        name,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    )?
    .into();
    let initial = file.metadata()?;
    let validate = |metadata: &std::fs::Metadata| {
        metadata.is_file()
            && metadata.uid() == uid
            && metadata.mode() & 0o077 == 0
            && metadata.nlink() == 1
            && metadata.len() > 0
            && metadata.len() <= maximum
    };
    if !validate(&initial) || path.canonicalize()?.as_os_str() != path.as_os_str() {
        return invalid("private file must be a bounded canonical owner-only regular file");
    }
    let length = usize::try_from(initial.len())
        .map_err(|_| io::Error::other("private file length overflow"))?;
    let mut bytes = vec![0; length];
    file.read_exact(&mut bytes)?;
    let mut extra = [0; 1];
    if file.read(&mut extra)? != 0 {
        return invalid("private file grew during its bounded observation");
    }
    let final_metadata = file.metadata()?;
    let named = std::fs::symlink_metadata(path)?;
    if !validate(&final_metadata)
        || final_metadata.len() != initial.len()
        || final_metadata.mtime() != initial.mtime()
        || final_metadata.mtime_nsec() != initial.mtime_nsec()
        || final_metadata.ctime() != initial.ctime()
        || final_metadata.ctime_nsec() != initial.ctime_nsec()
        || named.file_type().is_symlink()
        || named.dev() != initial.dev()
        || named.ino() != initial.ino()
    {
        return invalid("private file changed during its bounded observation");
    }
    Ok(bytes)
}

#[cfg(not(unix))]
pub(crate) fn read(_path: &Path, _maximum: u64) -> io::Result<Vec<u8>> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "private PQ authority files require Unix ownership checks",
    ))
}

#[cfg(unix)]
fn invalid<T>(message: &str) -> io::Result<T> {
    Err(io::Error::new(io::ErrorKind::InvalidData, message))
}

#[cfg(all(test, unix))]
#[path = "protected_file_tests.rs"]
mod tests;
