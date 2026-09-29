use std::fs::OpenOptions;
use std::io;
use std::path::Path;

/// Write and synchronize one same-directory staging file, then publish it.
/// Any pre-publication failure removes the staging file. A directory-sync
/// failure remains an ambiguous durable outcome by design: the destination is
/// already valid, but the caller must not report success without the sync.
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
/// Unix synchronizes the parent directory; Windows uses write-through replace.
pub(crate) fn publish(staging: &Path, destination: &Path) -> io::Result<()> {
    publish_at(staging, destination, "durable_publish")
}

pub(crate) fn publish_at(
    staging: &Path,
    destination: &Path,
    component: &str,
) -> io::Result<()> {
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
fn publish_same_directory(
    staging: &Path,
    destination: &Path,
    component: &str,
) -> io::Result<()> {
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
fn publish_same_directory(
    staging: &Path,
    destination: &Path,
    component: &str,
) -> io::Result<()> {
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
        assert_eq!(std::fs::read(destination).expect("read old state"), b"old");
        assert!(!staging.exists());
    }
}
