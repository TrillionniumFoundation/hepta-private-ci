//! Private host configuration reads shared by production and an isolated test target.
use std::fs;
use std::io::Read;
use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub(crate) enum ProtectedFileError {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

pub(crate) fn read_protected_file(
    path: &Path,
    max_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, ProtectedFileError> {
    if !path.is_absolute() {
        return Err(ProtectedFileError::Invalid(format!(
            "{label} must be absolute"
        )));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(ProtectedFileError::Invalid(format!(
            "{label} must be canonical and symlink-free"
        )));
    }
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ProtectedFileError::Invalid(format!(
            "{label} must be a regular non-symlink file"
        )));
    }
    if metadata.len() == 0 || metadata.len() > max_bytes {
        return Err(ProtectedFileError::Invalid(format!(
            "{label} is empty or too large"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(ProtectedFileError::Invalid(format!(
                "{label} must not be group/world accessible"
            )));
        }
    }
    let mut file = open_protected_file(path)?;
    let opened = file.metadata()?;
    #[cfg(unix)]
    let unchanged = |other: &fs::Metadata| {
        use std::os::unix::fs::MetadataExt;
        other.dev() == metadata.dev()
            && other.ino() == metadata.ino()
            && other.len() == metadata.len()
            && other.mtime() == metadata.mtime()
            && other.mtime_nsec() == metadata.mtime_nsec()
            && other.ctime() == metadata.ctime()
            && other.ctime_nsec() == metadata.ctime_nsec()
    };
    #[cfg(not(unix))]
    let unchanged = |other: &fs::Metadata| {
        other.len() == metadata.len() && other.modified().ok() == metadata.modified().ok()
    };
    if !unchanged(&opened) {
        return Err(ProtectedFileError::Invalid(format!(
            "{label} changed while opening"
        )));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(max_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = fs::symlink_metadata(path)?;
    if bytes.is_empty()
        || u64::try_from(bytes.len()).unwrap_or(u64::MAX) > max_bytes
        || !after.is_file()
        || !unchanged(&after)
        || !unchanged(&file.metadata()?)
    {
        return Err(ProtectedFileError::Invalid(format!(
            "{label} changed while reading"
        )));
    }
    Ok(bytes)
}

fn open_protected_file(path: &Path) -> Result<fs::File, ProtectedFileError> {
    #[cfg(unix)]
    let file: fs::File = rustix::fs::open(
        path,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::NONBLOCK
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(std::io::Error::from)?
    .into();
    #[cfg(not(unix))]
    let file = fs::File::open(path)?;
    if !file.metadata()?.is_file() {
        return Err(ProtectedFileError::Invalid(
            "protected configuration is not a regular file".to_string(),
        ));
    }
    Ok(file)
}

#[cfg(all(test, unix))]
#[path = "automation_protected_file_tests.rs"]
mod tests;
