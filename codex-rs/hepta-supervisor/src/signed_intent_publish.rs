//! Publish the already-synchronized staging file without a cross-volume copy.
//! A reported failure never permits the caller to acknowledge the new intent.

use std::io;
use std::path::Path;

pub(super) fn publish(staging: &Path, destination: &Path) -> io::Result<()> {
    let parent = staging.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "intent staging has no parent")
    })?;
    if destination.parent() != Some(parent) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "intent replacement must remain in the staging directory",
        ));
    }
    publish_same_directory(staging, destination)
}

#[cfg(unix)]
fn publish_same_directory(staging: &Path, destination: &Path) -> io::Result<()> {
    std::fs::rename(staging, destination)?;
    let parent = destination.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "intent destination has no parent",
        )
    })?;
    std::fs::File::open(parent)?.sync_all()
}

#[cfg(windows)]
fn publish_same_directory(staging: &Path, destination: &Path) -> io::Result<()> {
    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
    use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
    use windows_sys::Win32::Storage::FileSystem::MoveFileExW;

    // Canonicalizing the existing common parent supplies the OS verbatim
    // prefix, preserving std::fs::rename's support for paths above MAX_PATH.
    // The destination itself need not exist on the initial publication.
    let parent = staging.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "intent staging has no parent")
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
            "intent staging has no file name",
        )
    })?;
    let destination_name = destination.file_name().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "intent destination has no file name",
        )
    })?;
    let staging = wide_path(&parent.join(staging_name))?;
    let destination = wide_path(&parent.join(destination_name))?;
    // SAFETY: Both buffers are NUL-terminated UTF-16 paths with no interior NUL,
    // and remain alive for the synchronous call. No delayed or copy fallback is
    // allowed. WRITE_THROUGH waits for the move to reach disk before success:
    // https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-movefileexw
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
                "intent path contains NUL or exceeds the Windows path limit",
            ));
        }
        wide.push(unit);
    }
    wide.push(/*value*/ 0);
    Ok(wide)
}

#[cfg(not(any(unix, windows)))]
fn publish_same_directory(_staging: &Path, _destination: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "durable intent publication is unsupported on this platform",
    ))
}

#[cfg(test)]
#[path = "signed_intent_publish_tests.rs"]
mod tests;
