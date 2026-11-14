//! Bounded owner configuration reads anchored to a private Windows directory.

use std::io;
use std::io::Read;
use std::path::Path;

use codex_utils_path::normalize_for_native_workdir;
use codex_utils_path::windows_private_fs::PrivateDirectory;
use codex_utils_path::windows_private_fs::snapshot_private_file;

pub(crate) fn read(path: &Path, home: &Path, maximum_bytes: u64) -> io::Result<Vec<u8>> {
    let normalized_path = normalize_for_native_workdir(path);
    let normalized_home = normalize_for_native_workdir(home);
    if !path.is_absolute()
        || normalized_path.parent() != Some(normalized_home.as_path())
        || normalize_for_native_workdir(home.canonicalize()?) != normalized_home
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "owner configuration must be a direct child of the canonical Agent home",
        ));
    }
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid owner configuration name",
            )
        })?;
    let directory = PrivateDirectory::open_existing_read_only(home)?;
    let root_before = snapshot_private_file(directory.as_file())?;
    let mut file = directory.open_read(name)?;
    let before = snapshot_private_file(&file)?;
    if before.len() > maximum_bytes {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "owner configuration exceeds its byte bound",
        ));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let current = directory.open_read(name)?;
    let current_root = PrivateDirectory::open_existing_read_only(home)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || snapshot_private_file(&file)? != before
        || snapshot_private_file(&current)? != before
        || !snapshot_private_file(current_root.as_file())?.same_file(&root_before)
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "owner configuration changed while reading",
        ));
    }
    directory.validate()?;
    Ok(bytes)
}

#[cfg(test)]
#[path = "private_owner_file_windows_tests.rs"]
mod tests;
