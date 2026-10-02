//! Descriptor-bound control reads reject special-file substitution before I/O.
//! Existing regular-filesystem calls can still depend on host storage progress.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;

use crate::FleetRegistryError;

pub(crate) fn open(path: &Path, maximum: Option<u64>) -> Result<(File, u64), FleetRegistryError> {
    let before = std::fs::symlink_metadata(path)?;
    let bound = maximum.unwrap_or(before.len());
    if !before.file_type().is_file() || before.len() > bound {
        return Err(FleetRegistryError::Corrupt(format!(
            "control path is not a bounded regular file: {}",
            path.display()
        )));
    }
    #[cfg(all(test, unix))]
    tests::after_metadata(path)?;

    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let file = options.open(path)?;
    let opened = file.metadata()?;
    if !opened.file_type().is_file() || opened.len() > bound {
        return Err(FleetRegistryError::Corrupt(format!(
            "opened control path is not a bounded regular file: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != opened.dev() || before.ino() != opened.ino() {
            return Err(FleetRegistryError::Corrupt(format!(
                "control file identity changed while opening: {}",
                path.display()
            )));
        }
    }
    Ok((file, bound))
}

pub(crate) fn read(path: &Path, maximum: Option<u64>) -> Result<Vec<u8>, FleetRegistryError> {
    let (file, bound) = open(path, maximum)?;
    let mut bytes = Vec::new();
    file.take(read_limit(bound)?).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > bound {
        return Err(FleetRegistryError::Corrupt(format!(
            "control file exceeds its byte bound: {}",
            path.display()
        )));
    }
    Ok(bytes)
}

pub(crate) fn read_limit(bound: u64) -> Result<u64, FleetRegistryError> {
    bound
        .checked_add(1)
        .ok_or_else(|| FleetRegistryError::Corrupt("control file byte bound overflow".to_string()))
}

#[cfg(unix)]
pub(crate) fn sync_directory(path: &Path) -> Result<(), FleetRegistryError> {
    use std::os::unix::fs::OpenOptionsExt;

    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC)
        .open(path)?;
    if !file.metadata()?.is_dir() {
        return Err(FleetRegistryError::Corrupt(format!(
            "opened control path is not a directory: {}",
            path.display()
        )));
    }
    file.sync_all()?;
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "regular_file_tests.rs"]
mod tests;
