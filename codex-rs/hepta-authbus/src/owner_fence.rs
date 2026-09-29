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
/// ordering preserves a single in-process owner and prevents a failed duplicate
/// initialization from opening the live lock inode. On Linux, the kernel fence
/// is an open-file-description record lock on the deployed lock pathname. It is
/// released with the final descriptor for this open file description, survives
/// unrelated closes, and conflicts with the legacy process-associated POSIX
/// record lock used by older AuthBus binaries.
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

        // Preserve one in-process owner and avoid opening a second descriptor
        // for the live lock inode on a rejected duplicate initialization.
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
        // Fields are dropped after this method. `file` is declared before the
        // process claim, so the kernel lock descriptor closes before the same-
        // process reservation is released.
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
    // Preserve the deployed lock pathname. Linux OFD record locks conflict with
    // the POSIX record locks used by older binaries, so a rolling replacement
    // cannot establish a second lock domain on this inode.
    name.push(".authbus-owner-lock.sqlite");
    Ok(parent.join(name))
}

#[cfg(target_os = "linux")]
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

#[cfg(not(target_os = "linux"))]
fn validate_parent(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(target_os = "linux")]
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
        || metadata.mode() & 0o077 != 0
        || path.canonicalize().map_err(storage_io)? != path
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn validate_existing_database_path(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
pub(crate) fn harden_authority_state_files(
    database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    use std::io::ErrorKind;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    let parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let parent_metadata = std::fs::metadata(parent).map_err(storage_io)?;
    for suffix in ["", "-wal", "-shm"] {
        let mut raw = database_path.as_os_str().to_os_string();
        raw.push(suffix);
        let path = PathBuf::from(raw);
        let metadata = match std::fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => continue,
            Err(error) => return Err(storage_io(error)),
        };
        if !metadata.file_type().is_file()
            || metadata.nlink() != 1
            || metadata.uid() != parent_metadata.uid()
            || path.canonicalize().map_err(storage_io)? != path
        {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .map_err(storage_io)?;
        let hardened = match std::fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => continue,
            Err(error) => return Err(storage_io(error)),
        };
        if hardened.mode() & 0o077 != 0 {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
    }
    Ok(())
}

#[cfg(not(unix))]
pub(crate) fn harden_authority_state_files(
    _database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(target_os = "linux")]
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

#[cfg(not(target_os = "linux"))]
fn open_lock_file(_path: &Path) -> Result<File, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(target_os = "linux")]
fn whole_file_lock(lock_type: nix::libc::c_short) -> nix::libc::flock {
    nix::libc::flock {
        l_type: lock_type,
        l_whence: nix::libc::SEEK_SET as nix::libc::c_short,
        l_start: 0,
        l_len: 0,
        // Linux requires l_pid to be zero for an OFD lock request.
        l_pid: 0,
    }
}

#[cfg(target_os = "linux")]
fn acquire_process_lock(file: &File) -> Result<(), AuthBusAuthorityError> {
    let lock = whole_file_lock(nix::libc::F_WRLCK as nix::libc::c_short);
    match nix::fcntl::fcntl(file, nix::fcntl::FcntlArg::F_OFD_SETLK(&lock)) {
        Ok(_) => Ok(()),
        Err(error) if error == nix::errno::Errno::EAGAIN || error == nix::errno::Errno::EACCES => {
            Err(AuthBusAuthorityError::OwnerAlreadyActive)
        }
        Err(error) => Err(AuthBusAuthorityError::Storage(format!(
            "open-file-description owner lock unavailable: {error}"
        ))),
    }
}

#[cfg(not(target_os = "linux"))]
fn acquire_process_lock(_file: &File) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(target_os = "linux")]
fn release_process_lock(file: &File) {
    let unlock = whole_file_lock(nix::libc::F_UNLCK as nix::libc::c_short);
    let _ = nix::fcntl::fcntl(file, nix::fcntl::FcntlArg::F_OFD_SETLK(&unlock));
}

#[cfg(not(target_os = "linux"))]
fn release_process_lock(_file: &File) {}

#[cfg(target_os = "linux")]
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

#[cfg(not(target_os = "linux"))]
fn validate_open_lock_file(_file: &File, _path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn storage_io(error: std::io::Error) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(error.to_string())
}

#[cfg(all(test, target_os = "linux"))]
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
