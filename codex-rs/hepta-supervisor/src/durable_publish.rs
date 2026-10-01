use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::path::Path;

/// Read one bounded, stable, single-link state file. On Unix the final path
/// component is opened without following links or blocking on special files.
/// Parent directories remain part of the trusted supervisor-owned boundary.
pub(crate) fn read_regular_bounded(path: &Path, maximum: usize) -> io::Result<Option<Vec<u8>>> {
    read_regular_bounded_at(path, maximum, |_, _| {})
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum ReadBoundary {
    BeforeOpen,
    BeforeRead,
    AfterRead,
}

fn read_regular_bounded_at(
    path: &Path,
    maximum: usize,
    mut boundary: impl FnMut(ReadBoundary, &Path),
) -> io::Result<Option<Vec<u8>>> {
    let read_limit = maximum
        .checked_add(1)
        .and_then(|limit| u64::try_from(limit).ok())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "invalid state-file bound"))?;
    let before = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    validate_read_metadata(&before, maximum)?;
    boundary(ReadBoundary::BeforeOpen, path);
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let mut file = options.open(path).map_err(|error| {
        #[cfg(unix)]
        if error.raw_os_error() == Some(libc::ELOOP) {
            return invalid_read("state path became a symbolic link");
        }
        if error.kind() == io::ErrorKind::NotFound {
            return invalid_read("state file disappeared during open");
        }
        error
    })?;
    let opened = file.metadata()?;
    let named = std::fs::symlink_metadata(path)?;
    validate_read_metadata(&opened, maximum)?;
    validate_read_metadata(&named, maximum)?;
    same_read_file(&before, &opened)?;
    same_read_file(&opened, &named)?;
    boundary(ReadBoundary::BeforeRead, path);
    let mut bytes = Vec::new();
    (&mut file).take(read_limit).read_to_end(&mut bytes)?;
    boundary(ReadBoundary::AfterRead, path);
    if bytes.len() > maximum || bytes.len() as u64 != opened.len() {
        return Err(invalid_read(
            "state file changed during read or exceeds its bound",
        ));
    }
    let after = file.metadata()?;
    let named_after = std::fs::symlink_metadata(path)?;
    validate_read_metadata(&after, maximum)?;
    validate_read_metadata(&named_after, maximum)?;
    same_read_file(&opened, &after)?;
    same_read_file(&after, &named_after)?;
    Ok(Some(bytes))
}

fn invalid_read(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

fn validate_read_metadata(metadata: &std::fs::Metadata, maximum: usize) -> io::Result<()> {
    if !metadata.file_type().is_file() || metadata.len() > maximum as u64 {
        return Err(invalid_read("state path is not a bounded regular file"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // SAFETY: geteuid takes no arguments and has no memory-safety preconditions.
        let owner = unsafe { libc::geteuid() };
        if metadata.uid() != owner || metadata.nlink() != 1 || metadata.mode() & 0o022 != 0 {
            return Err(invalid_read(
                "state-file ownership, links, or permissions are unsafe",
            ));
        }
    }
    Ok(())
}

fn same_read_file(before: &std::fs::Metadata, after: &std::fs::Metadata) -> io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != after.dev()
            || before.ino() != after.ino()
            || before.mode() != after.mode()
            || before.uid() != after.uid()
            || before.gid() != after.gid()
            || before.nlink() != after.nlink()
            || before.mtime() != after.mtime()
            || before.mtime_nsec() != after.mtime_nsec()
            || before.ctime() != after.ctime()
            || before.ctime_nsec() != after.ctime_nsec()
        {
            return Err(invalid_read("state-file identity changed during open/read"));
        }
    }
    if before.len() != after.len() || before.modified()? != after.modified()? {
        return Err(invalid_read("state file changed during open/read"));
    }
    Ok(())
}

/// Write and synchronize one same-directory staging file, then publish it.
/// A directory-sync failure is an ambiguous durable outcome: the destination
/// is valid, but the caller must not report success without the sync receipt.
pub(crate) fn write_atomic(
    staging: &Path,
    destination: &Path,
    bytes: &[u8],
    component: &str,
) -> io::Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(staging)?;
    let result = (|| {
        crate::durability::write_all(&mut file, bytes, component)?;
        crate::durability::sync_all(&file, component)?;
        drop(file);
        publish_at(staging, destination, component)
    })();
    if result.is_err() && staging.exists() {
        let _ = std::fs::remove_file(staging);
    }
    result
}

/// Replace one already-synchronized staging file within the same directory.
pub(crate) fn publish(staging: &Path, destination: &Path) -> io::Result<()> {
    publish_at(staging, destination, "durable_publish")
}

pub(crate) fn publish_at(staging: &Path, destination: &Path, component: &str) -> io::Result<()> {
    let parent = staging.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "durable staging has no parent")
    })?;
    if destination.parent() != Some(parent) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable replacement must remain in the staging directory",
        ));
    }
    publish_same_directory(staging, destination, component)
}

#[cfg(unix)]
fn publish_same_directory(staging: &Path, destination: &Path, component: &str) -> io::Result<()> {
    crate::durability::check(component, "rename")?;
    std::fs::rename(staging, destination)?;
    let parent = destination.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable destination has no parent",
        )
    })?;
    crate::durability::check(component, "directory_sync")?;
    std::fs::File::open(parent)?.sync_all()
}

#[cfg(windows)]
fn publish_same_directory(staging: &Path, destination: &Path, component: &str) -> io::Result<()> {
    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
    use windows_sys::Win32::Storage::FileSystem::MoveFileExW;

    crate::durability::check(component, "rename")?;
    let parent = staging.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "durable staging has no parent")
    })?;
    let parent = if parent.as_os_str().is_empty() {
        Path::new(".")
    } else {
        parent
    };
    let parent = parent.canonicalize()?;
    let staging_name = staging.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable staging has no file name",
        )
    })?;
    let destination_name = destination.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable destination has no file name",
        )
    })?;
    let staging = wide_path(&parent.join(staging_name))?;
    let destination = wide_path(&parent.join(destination_name))?;
    // SAFETY: Both buffers are NUL-terminated UTF-16 paths with no interior NUL,
    // and remain alive for this synchronous call.
    let result = unsafe {
        MoveFileExW(
            staging.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if result == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(windows)]
fn wide_path(path: &Path) -> io::Result<Vec<u16>> {
    use std::os::windows::ffi::OsStrExt;

    let mut wide = Vec::new();
    for unit in path.as_os_str().encode_wide() {
        if unit == 0 || wide.len() >= 32_766 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "durable path contains NUL or exceeds the Windows path limit",
            ));
        }
        wide.push(unit);
    }
    wide.push(/*value*/ 0);
    Ok(wide)
}

#[cfg(not(any(unix, windows)))]
fn publish_same_directory(
    _staging: &Path,
    _destination: &Path,
    _component: &str,
) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "durable publication is unsupported on this platform",
    ))
}

#[cfg(test)]
#[path = "durable_read_tests.rs"]
mod read_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rename_failure_preserves_previous_destination() {
        let dir = tempfile::tempdir().expect("temporary directory");
        let destination = dir.path().join("state.json");
        std::fs::write(&destination, b"old").expect("old state");
        let staging = dir.path().join(".state.tmp");
        crate::durability::with_qualification_fault(
            "test_publish.rename",
            io::ErrorKind::Other,
            || {
                assert!(write_atomic(&staging, &destination, b"new", "test_publish").is_err());
            },
        );
        assert_eq!(std::fs::read(destination).expect("read state"), b"old");
        assert!(!staging.exists());
    }
}
