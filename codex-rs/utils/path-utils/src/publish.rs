use std::io;
use std::path::Path;

/// Publishes an already flushed file under its final name in the same directory.
///
/// The caller must finish writing and syncing `temporary` before calling this
/// function, and must arrange the required file permissions and path ownership.
/// Existing destination contents are replaced. Unix synchronizes the parent
/// directory after rename; Windows requests a write-through move, since opening
/// and syncing a directory as a normal read-only file is not supported there.
/// An error after publication does not imply that the old destination remains.
pub fn publish_file_with_sync(temporary: &Path, destination: &Path) -> io::Result<()> {
    let parent = destination.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "destination has no parent directory",
        )
    })?;
    if temporary.parent() != Some(parent) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "temporary and destination must share their parent directory",
        ));
    }
    publish(temporary, destination)
}

#[cfg(not(windows))]
fn publish(temporary: &Path, destination: &Path) -> io::Result<()> {
    std::fs::rename(temporary, destination)?;
    let parent = destination.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "destination has no parent directory",
        )
    })?;
    let parent = if parent.as_os_str().is_empty() {
        Path::new(".")
    } else {
        parent
    };
    std::fs::File::open(parent)?.sync_all()
}

#[cfg(windows)]
fn publish(temporary: &Path, destination: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;

    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
    use windows_sys::Win32::Storage::FileSystem::MoveFileExW;

    let wide_path = |path: &Path| -> io::Result<Vec<u16>> {
        let mut units: Vec<u16> = path.as_os_str().encode_wide().collect();
        if units.contains(&0) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "path contains a null character",
            ));
        }
        units.push(0);
        Ok(units)
    };
    let temporary = wide_path(temporary)?;
    let destination = wide_path(destination)?;
    // SAFETY: both pointers refer to owned, null-terminated UTF-16 buffers that
    // outlive this synchronous call. The same-directory requirement excludes a
    // cross-volume copy. No delayed move or copy fallback is requested.
    let moved = unsafe {
        MoveFileExW(
            temporary.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if moved == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(test)]
#[path = "publish_tests.rs"]
mod tests;
