//! Run-start journal files opened relative to held, no-follow directory FDs.

use std::ffi::CString;
use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use crate::private_directory_fd::directory;
use crate::private_directory_fd::open_at;

use super::RUN_START_DIRECTORY;
use super::RUN_START_FILE;

pub(super) struct RunStartFiles {
    pub(super) directory: File,
    pub(super) journal: File,
}

pub(super) fn open(home_root: &Path) -> io::Result<RunStartFiles> {
    let home = directory(home_root).map_err(|error| {
        error
            .downcast::<io::Error>()
            .unwrap_or_else(io::Error::other)
    })?;
    let name = CString::new(RUN_START_DIRECTORY)?;
    // SAFETY: home owns a live directory FD and name is NUL-terminated.
    let result = unsafe { libc::mkdirat(home.as_raw_fd(), name.as_ptr(), 0o700) };
    let created = if result == 0 {
        true
    } else {
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::AlreadyExists {
            return Err(error);
        }
        false
    };
    let directory = open_at(
        &home,
        RUN_START_DIRECTORY.as_ref(),
        libc::O_RDONLY | libc::O_DIRECTORY,
    )?;
    directory.set_permissions(std::fs::Permissions::from_mode(0o700))?;
    if created {
        home.sync_all()?;
    }
    let (journal, created) = match open_at(
        &directory,
        RUN_START_FILE.as_ref(),
        libc::O_RDWR | libc::O_CREAT | libc::O_EXCL,
    ) {
        Ok(file) => (file, true),
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => (
            open_at(&directory, RUN_START_FILE.as_ref(), libc::O_RDWR)?,
            false,
        ),
        Err(error) => return Err(error),
    };
    let metadata = journal.metadata()?;
    if !metadata.is_file() || metadata.nlink() != 1 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "objective run-start journal must be a single-link regular file",
        ));
    }
    if created {
        journal.set_permissions(std::fs::Permissions::from_mode(0o600))?;
        journal.sync_all()?;
    }
    Ok(RunStartFiles { directory, journal })
}

#[cfg(test)]
#[path = "objective_run_start_files_tests.rs"]
mod tests;
