use std::fs;
use std::io::ErrorKind;
use std::path::Component;
use std::path::Path;

use crate::MatrixDurableError;

/// Prepare Matrix-owned storage without following existing linked directories.
/// The caller must supply an absolute path within its authorized agent layout.
pub fn prepare_matrix_storage_directory(path: &Path) -> Result<(), MatrixDurableError> {
    if !path.is_absolute()
        || path.file_name().is_none()
        || path.components().any(|part| part == Component::ParentDir)
    {
        return Err(MatrixDurableError::Invalid);
    }

    let builder = fs::DirBuilder::new();
    #[cfg(unix)]
    let builder = {
        use std::os::unix::fs::DirBuilderExt;
        let mut builder = builder;
        builder.mode(0o700);
        builder
    };
    for directory in path.ancestors().collect::<Vec<_>>().into_iter().rev() {
        match fs::symlink_metadata(directory) {
            Ok(metadata) => require_directory(&metadata)?,
            Err(error) if error.kind() == ErrorKind::NotFound => {
                if let Err(error) = builder.create(directory)
                    && error.kind() != ErrorKind::AlreadyExists
                {
                    return Err(MatrixDurableError::Unavailable);
                }
                let metadata =
                    fs::symlink_metadata(directory).map_err(|_| MatrixDurableError::Unavailable)?;
                require_directory(&metadata)?;
            }
            Err(_) => return Err(MatrixDurableError::Unavailable),
        }
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if path
            .canonicalize()
            .map_err(|_| MatrixDurableError::Unavailable)?
            != path
        {
            return Err(MatrixDurableError::AccessDenied);
        }
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))
            .map_err(|_| MatrixDurableError::Unavailable)?;
    }
    Ok(())
}

fn require_directory(metadata: &fs::Metadata) -> Result<(), MatrixDurableError> {
    if !metadata.file_type().is_dir() || is_reparse_point(metadata) {
        return Err(MatrixDurableError::AccessDenied);
    }
    Ok(())
}

/// Reject linked or non-regular existing SQLite databases and their sidecars.
pub fn validate_matrix_database_paths(path: &Path) -> Result<(), MatrixDurableError> {
    let filename = path.file_name().ok_or(MatrixDurableError::Invalid)?;
    for suffix in ["", "-wal", "-shm", "-journal"] {
        let mut sidecar = filename.to_os_string();
        sidecar.push(suffix);
        let metadata = match fs::symlink_metadata(path.with_file_name(sidecar)) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => continue,
            Err(_) => return Err(MatrixDurableError::Unavailable),
        };
        if !metadata.file_type().is_file() || is_reparse_point(&metadata) {
            return Err(MatrixDurableError::AccessDenied);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.nlink() != 1 {
                return Err(MatrixDurableError::AccessDenied);
            }
        }
    }
    Ok(())
}

#[cfg(windows)]
fn is_reparse_point(metadata: &fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
fn is_reparse_point(_metadata: &fs::Metadata) -> bool {
    false
}
