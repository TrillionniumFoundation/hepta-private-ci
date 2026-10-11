use std::fs;
use std::path::Path;

use crate::MatrixDurableError;

pub(super) fn create_private_directory(path: &Path) -> Result<(), MatrixDurableError> {
    // Validate ancestors before creating anything. A check after create_dir_all
    // would already have written through a pre-existing ancestor symlink.
    for directory in path.ancestors().collect::<Vec<_>>().into_iter().rev() {
        match fs::symlink_metadata(directory) {
            Ok(metadata) if metadata.file_type().is_dir() => {}
            Ok(_) => return Err(MatrixDurableError::AccessDenied),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                fs::create_dir(directory).map_err(|_| MatrixDurableError::Unavailable)?;
            }
            Err(_) => return Err(MatrixDurableError::Unavailable),
        }
    }
    if path
        .canonicalize()
        .map_err(|_| MatrixDurableError::Unavailable)?
        != path
    {
        return Err(MatrixDurableError::AccessDenied);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))
            .map_err(|_| MatrixDurableError::Unavailable)?;
    }
    Ok(())
}

pub(super) fn validate_database_paths(path: &Path) -> Result<(), MatrixDurableError> {
    let filename = path.file_name().ok_or(MatrixDurableError::Invalid)?;
    for suffix in ["", "-wal", "-shm", "-journal"] {
        let mut name = filename.to_os_string();
        name.push(suffix);
        let candidate = path.with_file_name(name);
        let metadata = match fs::symlink_metadata(candidate) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => return Err(MatrixDurableError::Unavailable),
        };
        if !metadata.file_type().is_file() {
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
