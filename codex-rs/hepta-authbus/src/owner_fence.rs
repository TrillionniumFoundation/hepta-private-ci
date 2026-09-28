use std::collections::HashSet;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::OnceLock;

use crate::AuthBusAuthorityError;

static PROCESS_OWNERS: OnceLock<Mutex<HashSet<PathBuf>>> = OnceLock::new();

/// Process-lifetime single-owner fence held on one securely opened inode.
///
/// The process-local claim is acquired before the lock file is opened. That
/// ordering is security-sensitive: traditional POSIX record locks are process
/// associated, so closing a second descriptor for the same inode can release a
/// lock held through the first descriptor. Rejecting duplicate same-process
/// owners before `open(2)` prevents a failed duplicate initialization from
/// weakening the live owner's cross-process fence.
///
/// Existing authority databases must also be canonical, regular, single-link
/// files owned by the private database directory owner. This prevents a second
/// pathname from selecting the same SQLite inode while deriving a different
/// owner-lock pathname.
pub(crate) struct OwnerFence {
    file: File,
    _process_claim: ProcessOwnerClaim,
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
        validate_existing_database_path(database_path)?;

        // This claim must precede opening the lock inode. See the type-level
        // comment above for the POSIX close/release hazard it prevents.
        let process_claim = ProcessOwnerClaim::acquire(&path)?;
        let file = open_lock_file(&path)?;
        validate_open_lock_file(&file, &path)?;
        acquire_process_lock(&file)?;

        // Ensure the pathname still names the locked inode before exposing the
        // host. Protected owner directories exclude unprivileged replacement.
        if let Err(error) = validate_open_lock_file(&file, &path) {
            release_process_lock(&file);
            return Err(error);
        }
        Ok(Self {
            file,
            _process_claim: process_claim,
        })
    }
}

impl Drop for OwnerFence {
    fn drop(&mut self) {
        release_process_lock(&self.file);
        // Fields are dropped after this method. The file descriptor closes
        // before `_process_claim` releases the same-process reservation.
    }
}

struct ProcessOwnerClaim {
    path: PathBuf,
}

impl ProcessOwnerClaim {
    fn acquire(path: &Path) -> Result<Self, AuthBusAuthorityError> {
        let mut owners = PROCESS_OWNERS
            .get_or_init(|| Mutex::new(HashSet::new()))
            .lock()
            .map_err(|_| AuthBusAuthorityError::Storage("owner registry poisoned".into()))?;
        if !owners.insert(path.to_path_buf()) {
            return Err(AuthBusAuthorityError::OwnerAlreadyActive);
        }
        Ok(Self {
            path: path.to_path_buf(),
        })
    }
}

impl Drop for ProcessOwnerClaim {
    fn drop(&mut self) {
        if let Ok(mut owners) = PROCESS_OWNERS
            .get_or_init(|| Mutex::new(HashSet::new()))
            .lock()
        {
            owners.remove(&self.path);
        }
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
    // Preserve the deployed lock pathname so a new process conflicts with an
    // older SQLite-backed owner during a rolling upgrade.
    name.push(".authbus-owner-lock.sqlite");
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
fn validate_existing_database_path(path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::io::ErrorKind;
    use std::os::unix::fs::MetadataExt;

    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(storage_io(error)),
    };
    let parent_metadata = std::fs::metadata(parent).map_err(storage_io)?;
    if !metadata.file_type().is_file()
        || metadata.nlink() != 1
        || metadata.uid() != parent_metadata.uid()
        || path.canonicalize().map_err(storage_io)? != path
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_existing_database_path(_path: &Path) -> Result<(), AuthBusAuthorityError> {
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
fn acquire_process_lock(file: &File) -> Result<(), AuthBusAuthorityError> {
    match rustix::fs::fcntl_lock(file, rustix::fs::FlockOperation::NonBlockingLockExclusive) {
        Ok(()) => Ok(()),
        Err(error) if error == rustix::io::Errno::AGAIN || error == rustix::io::Errno::ACCESS => {
            Err(AuthBusAuthorityError::OwnerAlreadyActive)
        }
        Err(error) => Err(AuthBusAuthorityError::Storage(error.to_string())),
    }
}

#[cfg(not(unix))]
fn acquire_process_lock(_file: &File) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn release_process_lock(file: &File) {
    let _ = rustix::fs::fcntl_lock(file, rustix::fs::FlockOperation::Unlock);
}

#[cfg(not(unix))]
fn release_process_lock(_file: &File) {}

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
    async fn rejects_duplicate_owner_before_open_and_releases_after_drop() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let first = OwnerFence::acquire(&database, "owner:first")
            .await
            .expect("first owner");
        assert!(matches!(
            OwnerFence::acquire(&database, "owner:second").await,
            Err(AuthBusAuthorityError::OwnerAlreadyActive)
        ));
        assert!(matches!(
            OwnerFence::acquire(&database, "owner:third").await,
            Err(AuthBusAuthorityError::OwnerAlreadyActive)
        ));
        drop(first);
        OwnerFence::acquire(&database, "owner:replacement")
            .await
            .expect("replacement owner after release");
    }

    #[tokio::test]
    async fn rejects_database_symlink_alias_before_creating_a_lock() {
        let root = private_root();
        let target = root.path().join("authority-target.sqlite");
        let database = root.path().join("authority.sqlite");
        std::fs::write(&target, b"database").expect("database target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600))
            .expect("database target mode");
        symlink(&target, &database).expect("database symlink");

        assert!(matches!(
            OwnerFence::acquire(&database, "owner").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert!(!lock_path(&database).expect("lock path").exists());
        assert_eq!(
            std::fs::read(&target).expect("database target contents"),
            b"database"
        );
    }

    #[tokio::test]
    async fn rejects_database_hard_link_alias_before_creating_a_lock() {
        let root = private_root();
        let target = root.path().join("authority-target.sqlite");
        let database = root.path().join("authority.sqlite");
        std::fs::write(&target, b"database").expect("database target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600))
            .expect("database target mode");
        std::fs::hard_link(&target, &database).expect("database hard link");

        assert!(matches!(
            OwnerFence::acquire(&database, "owner").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert!(!lock_path(&database).expect("lock path").exists());
        assert_eq!(std::fs::metadata(&target).expect("metadata").nlink(), 2);
        assert_eq!(
            std::fs::read(&target).expect("database target contents"),
            b"database"
        );
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
        assert_eq!(
            std::fs::read(&target).expect("target contents"),
            b"unchanged"
        );
    }

    #[tokio::test]
    async fn rejects_a_hard_link() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let target = root.path().join("target");
        std::fs::write(&target, b"unchanged").expect("target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600))
            .expect("target mode");
        std::fs::hard_link(&target, lock_path(&database).expect("lock path")).expect("hard link");
        assert!(matches!(
            OwnerFence::acquire(&database, "owner").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert_eq!(std::fs::metadata(&target).expect("metadata").nlink(), 2);
        assert_eq!(
            std::fs::read(&target).expect("target contents"),
            b"unchanged"
        );
    }
}
