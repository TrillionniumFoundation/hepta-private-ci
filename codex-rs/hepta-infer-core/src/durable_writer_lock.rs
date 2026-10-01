//! A journal generation can be renamed; its lifecycle lock must not be.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use super::Error;

pub(super) fn acquire(path: &Path) -> Result<(PathBuf, File), Error> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let name = path
        .file_name()
        .ok_or(Error::InvalidIdentity("native journal path"))?;
    let path = fs::canonicalize(parent)?.join(name);
    // Existing symlink aliases must share the same lifecycle lock. For a new
    // journal, the canonical parent and basename identify its future path.
    let path = match fs::canonicalize(&path) {
        Ok(path) => path,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            if let Ok(metadata) = fs::symlink_metadata(&path)
                && metadata.file_type().is_symlink()
            {
                // Creating its target would lock the alias while compaction
                // later replaces the alias itself, splitting the generations.
                return Err(Error::InvalidIdentity("native dangling journal symlink"));
            }
            path
        }
        Err(error) => return Err(error.into()),
    };
    let name = path
        .file_name()
        .ok_or(Error::InvalidIdentity("native journal path"))?;
    let digest = Digest32::of_bytes(name.as_encoded_bytes());
    let lock_path = path.with_file_name(format!(".hepta-inference-{digest}.lock"));
    if let Ok(metadata) = fs::symlink_metadata(&lock_path)
        && !metadata.file_type().is_file()
    {
        return Err(Error::InvalidIdentity("native writer lock file"));
    }
    let mut options = OpenOptions::new();
    options.create(true).truncate(false).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let lock = options.open(&lock_path)?;
    lock.try_lock().map_err(|_| Error::WriterUnavailable)?;
    let metadata = fs::symlink_metadata(&lock_path)?;
    if !metadata.file_type().is_file() {
        return Err(Error::InvalidIdentity("native writer lock file"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;
        let opened = lock.metadata()?;
        if metadata.dev() != opened.dev()
            || metadata.ino() != opened.ino()
            || opened.permissions().mode() & 0o077 != 0
        {
            return Err(Error::InvalidIdentity("native writer lock identity"));
        }
    }
    // Never remove this file on shutdown: another opener may already hold it.
    Ok((path, lock))
}

#[cfg(test)]
#[path = "durable_writer_lock_tests.rs"]
mod tests;
