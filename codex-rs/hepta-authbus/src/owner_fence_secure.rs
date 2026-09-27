use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

use crate::AuthBusAuthorityError;

/// Process-lifetime single-owner fence held on one securely opened inode.
///
/// The file is opened without following the final symlink, validated through
/// its descriptor and locked non-blockingly. The descriptor remains owned by
/// this value, so normal exit and process death both release the fence.
pub(crate) struct OwnerFence {
    _file: File,
    _path: PathBuf,
}

impl OwnerFence {
    pub(crate) async fn acquire(
        database_path: &Path,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        if owner_id.is_empty() || owner_id.len() > 256 || !database_path.is_absolute() {
            return Err(AuthBusAuthorityError::InvalidInput(
                "authority owner identity or database path is invalid",
            ));
        }
        let path = lock_path(database_path)?;
        validate_parent(&path)?;
        let file = open_lock_file(&path)?;
        validate_open_lock_file(&file, &path)?;
        match rustix::fs::flock(&file, rustix::fs::FlockOperation::NonBlockingLockExclusive) {
            Ok(()) => {}
            Err(error) if error == rustix::io::Errno::WOULDBLOCK => {
                return Err(AuthBusAuthorityError::OwnerAlreadyActive);
            }
            Err(error) => return Err(AuthBusAuthorityError::Storage(error.to_string())),
        }
        // Ensure the pathname still names the locked inode before exposing the
        // host. Protected owner directories exclude unprivileged replacement.
        validate_open_lock_file(&file, &path)?;
        Ok(Self {
            _file: file,
            _path: path,
        })
    }
}

fn lock_path(database_path: &Path) -> Result<PathBuf, AuthBusAuthorityError> {
    let parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::InvalidInput(
            "authority database has no parent directory",
        ))?;
    let mut name = database_path
        .file_name()
        .ok_or(AuthBusAuthorityError::InvalidInput(
            "authority database has no file name",
        ))?
        .to_os_string();
    name.push(".authbus-owner.lock");
    Ok(parent.join(name))
}

#[cfg(unix)]
fn validate_parent(path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    if parent.canonicalize().map_err(storage_io)? != parent {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let metadata = std::fs::metadata(parent).map_err(storage_io)?;
    if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_parent(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn open_lock_file(path: &Path) -> Result<File, AuthBusAuthorityError> {
    use rustix::fs::Mode;
    use rustix::fs::OFlags;

    let descriptor = rustix::fs::open(
        path,
        OFlags::RDWR | OFlags::CREATE | OFlags::CLOEXEC | OFlags::NOFOLLOW,
        Mode::RUSR | Mode::WUSR,
    )
    .map_err(|error| {
        if error == rustix::io::Errno::LOOP {
            AuthBusAuthorityError::UnsafeCheckpoint
        } else {
            AuthBusAuthorityError::Storage(error.to_string())
        }
    })?;
    Ok(descriptor.into())
}

#[cfg(not(unix))]
fn open_lock_file(_path: &Path) -> Result<File, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_open_lock_file(file: &File, path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let opened = file.metadata().map_err(storage_io)?;
    let linked = std::fs::symlink_metadata(path).map_err(storage_io)?;
    let parent = std::fs::metadata(
        path.parent()
            .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?,
    )
    .map_err(storage_io)?;
    if !opened.is_file()
        || !linked.file_type().is_file()
        || opened.dev() != linked.dev()
        || opened.ino() != linked.ino()
        || opened.nlink() != 1
        || linked.nlink() != 1
        || opened.uid() != parent.uid()
        || opened.mode() & 0o077 != 0
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_open_lock_file(_file: &File, _path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn storage_io(error: std::io::Error) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(error.to_string())
}

#[cfg(all(test, unix))]
mod tests {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    use super::*;

    fn private_root() -> tempfile::TempDir {
        let root = tempfile::tempdir().expect("temporary directory");
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private temporary directory");
        root
    }

    #[tokio::test]
    async fn rejects_a_second_live_owner_and_releases_after_drop() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let first = OwnerFence::acquire(&database, "owner:first")
            .await
            .expect("first owner");
        assert!(matches!(
            OwnerFence::acquire(&database, "owner:second").await,
            Err(AuthBusAuthorityError::OwnerAlreadyActive)
        ));
        drop(first);
        OwnerFence::acquire(&database, "owner:replacement")
            .await
            .expect("replacement owner after release");
    }

    #[tokio::test]
    async fn rejects_symlink_without_touching_its_target() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let target = root.path().join("target");
        std::fs::write(&target, b"unchanged").expect("target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o640))
            .expect("target mode");
        symlink(&target, lock_path(&database).expect("lock path")).expect("symlink");
        assert!(matches!(
            OwnerFence::acquire(&database, "owner").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        let metadata = std::fs::metadata(&target).expect("target metadata");
        assert_eq!(metadata.mode() & 0o777, 0o640);
        assert_eq!(std::fs::read(&target).expect("target contents"), b"unchanged");
    }

    #[tokio::test]
    async fn rejects_a_hard_link() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let target = root.path().join("target");
        std::fs::write(&target, b"unchanged").expect("target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600))
            .expect("target mode");
        std::fs::hard_link(&target, lock_path(&database).expect("lock path"))
            .expect("hard link");
        assert!(matches!(
            OwnerFence::acquire(&database, "owner").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert_eq!(std::fs::metadata(&target).expect("metadata").nlink(), 2);
        assert_eq!(std::fs::read(&target).expect("target contents"), b"unchanged");
    }
}
