//! Bounded host-owned file acquisition for retrieval learning bootstrap.
//! The protected launcher must exclude same-UID writers; metadata checks are
//! not an atomic descriptor-relative traversal or independent WORM retention.

use std::fs::File;
use std::io::Read;
use std::path::Path;

pub(super) fn read(path: &Path, home: &Path, maximum: usize) -> Result<Vec<u8>, String> {
    let file = open(path, home, maximum as u64, false)?;
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err("retrieval learning file exceeded its byte bound".to_string());
    }
    Ok(bytes)
}

#[cfg(unix)]
pub(super) fn open(
    path: &Path,
    home: &Path,
    maximum: u64,
    writable: bool,
) -> Result<File, String> {
    use std::fs::OpenOptions;
    use std::os::unix::fs::MetadataExt;
    if !path.is_absolute()
        || path.starts_with(home)
        || path.canonicalize().map_err(|error| error.to_string())? != path
    {
        return Err("retrieval learning requires canonical paths outside Agent home".to_string());
    }
    let parent = path.parent().ok_or("retrieval learning file has no parent")?;
    for ancestor in parent.ancestors() {
        let metadata = ancestor.metadata().map_err(|error| error.to_string())?;
        let mode = metadata.mode();
        if !metadata.is_dir() || (mode & 0o022 != 0 && (ancestor == parent || mode & 0o1000 == 0)) {
            return Err("retrieval learning directory is not protected".to_string());
        }
    }
    let before = std::fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    let denied = if writable { 0o077 } else { 0o022 };
    if !before.is_file() || before.nlink() != 1 || before.len() > maximum || before.mode() & denied != 0 {
        return Err("retrieval learning requires a protected bounded single-link file".to_string());
    }
    // Never create, truncate, repair by replacement, or retry without an anchor.
    let file = OpenOptions::new()
        .read(true)
        .write(writable)
        .open(path)
        .map_err(|error| error.to_string())?;
    let opened = file.metadata().map_err(|error| error.to_string())?;
    if !opened.is_file()
        || opened.dev() != before.dev()
        || opened.ino() != before.ino()
        || opened.nlink() != 1
        || opened.len() > maximum
        || opened.mode() & denied != 0
    {
        return Err("retrieval learning file changed during acquisition".to_string());
    }
    Ok(file)
}

#[cfg(not(unix))]
pub(super) fn open(
    _path: &Path,
    _home: &Path,
    _maximum: u64,
    _writable: bool,
) -> Result<File, String> {
    Err("retrieval learning bootstrap requires a qualified Unix host".to_string())
}
