use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::QualificationError;

pub(crate) fn write_private_new(path: &Path, bytes: &[u8]) -> Result<(), QualificationError> {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    verify_private_regular(path)?;
    sync_directory(
        path.parent()
            .ok_or_else(|| invalid("artifact has no parent"))?,
    )
}

pub(crate) fn read_private_bounded(
    path: &Path,
    max_bytes: usize,
) -> Result<Vec<u8>, QualificationError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    let file = options.open(path)?;
    let opened = file.metadata()?;
    if !opened.is_file() {
        return Err(invalid("private artifact must be a regular file"));
    }
    verify_private_mode(&opened, "private artifact")?;
    let mut bytes = Vec::new();
    file.take(max_bytes.saturating_add(1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > max_bytes {
        return Err(invalid("private artifact exceeds its read bound"));
    }
    Ok(bytes)
}

pub(crate) fn create_or_verify_private_directory(path: &Path) -> Result<(), QualificationError> {
    if !path.exists() {
        create_private_directory(path)?;
    }
    verify_private_directory(path)
}

pub(crate) fn create_private_directory(path: &Path) -> Result<(), QualificationError> {
    #[cfg(unix)]
    let builder = {
        use std::os::unix::fs::DirBuilderExt;
        let mut builder = std::fs::DirBuilder::new();
        builder.mode(0o700);
        builder
    };
    #[cfg(not(unix))]
    let builder = std::fs::DirBuilder::new();
    builder.create(path)?;
    verify_private_directory(path)
}

pub(crate) fn verify_private_directory(path: &Path) -> Result<(), QualificationError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(invalid("private path must be a real directory"));
    }
    verify_private_mode(&metadata, "private directory")
}

pub(crate) fn verify_private_regular(path: &Path) -> Result<(), QualificationError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(invalid("private artifact must be a real regular file"));
    }
    verify_private_mode(&metadata, "private artifact")
}

pub(crate) fn verify_private_tree(root: &Path) -> Result<(), QualificationError> {
    verify_private_directory(root)?;
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(directory)? {
            let entry = entry?;
            let path = entry.path();
            let metadata = std::fs::symlink_metadata(&path)?;
            if metadata.file_type().is_symlink() {
                return Err(invalid("private runtime tree must not contain symlinks"));
            }
            if metadata.is_dir() {
                verify_private_mode(&metadata, "private runtime directory")?;
                pending.push(path);
            } else if metadata.is_file() {
                verify_private_mode(&metadata, "private runtime artifact")?;
            } else {
                return Err(invalid(
                    "private runtime tree must contain only directories and regular files",
                ));
            }
        }
    }
    Ok(())
}

pub(crate) fn sync_directory(path: &Path) -> Result<(), QualificationError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

pub(crate) fn now_millis() -> Result<u128, QualificationError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .map_err(|error| {
            QualificationError::State(format!("system clock is before UNIX epoch: {error}"))
        })
}

pub(crate) fn same_file_snapshot(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        before.dev() == after.dev()
            && before.ino() == after.ino()
            && before.len() == after.len()
            && before.mtime() == after.mtime()
            && before.mtime_nsec() == after.mtime_nsec()
    }
    #[cfg(not(unix))]
    {
        before.len() == after.len() && before.modified().ok() == after.modified().ok()
    }
}

fn verify_private_mode(
    _metadata: &std::fs::Metadata,
    _label: &str,
) -> Result<(), QualificationError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if _metadata.permissions().mode() & 0o077 != 0 {
            return Err(invalid(format!(
                "{_label} must not grant group or other access"
            )));
        }
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}
