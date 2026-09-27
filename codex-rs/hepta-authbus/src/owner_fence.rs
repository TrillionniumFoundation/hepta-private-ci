use std::collections::HashSet;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::OnceLock;

use crate::AuthBusAuthorityError;

static PROCESS_OWNERS: OnceLock<Mutex<HashSet<PathBuf>>> = OnceLock::new();

/// Single-owner fence on a securely opened inode in an owner-private directory.
///
/// The process reservation MUST precede opening the lock inode: closing even
/// an unsuccessfully acquired descriptor would release this process's existing
/// POSIX record lock. A descriptor-associated flock additionally protects modern
/// owners against unrelated opens/closes. The record lock is retained as a
/// compatibility guard against an already-running legacy SQLite-backed owner.
/// Mixed-version deployments still require a stop/drain/start upgrade; advisory
/// locks do not defend against an uncooperative process with the same OS UID.
pub(crate) struct OwnerFence {
    // Field drop order is intentional: close the descriptor BEFORE releasing
    // the process reservation, otherwise another thread could acquire a record
    // lock which this descriptor's subsequent close would immediately release.
    file: File,
    _process_owner: ProcessOwner,
}

struct ProcessOwner {
    path: PathBuf,
}

impl ProcessOwner {
    fn claim(path: PathBuf) -> Result<Self, AuthBusAuthorityError> {
        let mut owners = PROCESS_OWNERS
            .get_or_init(|| Mutex::new(HashSet::new()))
            .lock()
            .map_err(|_| AuthBusAuthorityError::Storage("owner registry poisoned".into()))?;
        if !owners.insert(path.clone()) {
            return Err(AuthBusAuthorityError::OwnerAlreadyActive);
        }
        Ok(Self { path })
    }
}

impl Drop for ProcessOwner {
    fn drop(&mut self) {
        if let Ok(mut owners) = PROCESS_OWNERS
            .get_or_init(|| Mutex::new(HashSet::new()))
            .lock()
        {
            owners.remove(&self.path);
        }
    }
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
        let process_owner = ProcessOwner::claim(path.clone())?;
        let file = open_lock_file(&path)?;
        validate_open_lock_file(&file, &path)?;
        acquire_process_lock(&file)?;
        // The private directory excludes unprivileged pathname replacement.
        validate_open_lock_file(&file, &path)?;
        Ok(Self {
            file,
            _process_owner: process_owner,
        })
    }
}

impl Drop for OwnerFence {
    fn drop(&mut self) {
        release_process_lock(&self.file);
        // Do not remove PROCESS_OWNERS here. Fields are dropped after this body.
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
fn lock_error(error: rustix::io::Errno) -> AuthBusAuthorityError {
    if error == rustix::io::Errno::AGAIN || error == rustix::io::Errno::ACCESS {
        AuthBusAuthorityError::OwnerAlreadyActive
    } else {
        AuthBusAuthorityError::Storage(error.to_string())
    }
}

#[cfg(unix)]
fn acquire_process_lock(file: &File) -> Result<(), AuthBusAuthorityError> {
    use rustix::fs::FlockOperation;

    rustix::fs::flock(file, FlockOperation::NonBlockingLockExclusive).map_err(lock_error)?;
    if let Err(error) = rustix::fs::fcntl_lock(file, FlockOperation::NonBlockingLockExclusive) {
        let _ = rustix::fs::flock(file, FlockOperation::Unlock);
        return Err(lock_error(error));
    }
    Ok(())
}

#[cfg(not(unix))]
fn acquire_process_lock(_file: &File) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn release_process_lock(file: &File) {
    let _ = rustix::fs::fcntl_lock(file, rustix::fs::FlockOperation::Unlock);
    let _ = rustix::fs::flock(file, rustix::fs::FlockOperation::Unlock);
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
    use std::process::Command;
    use std::time::Duration;
    use std::time::Instant;

    use super::*;

    fn private_root() -> tempfile::TempDir {
        let root = tempfile::tempdir().expect("temporary directory");
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private temporary directory");
        root
    }

    fn probe(database: &Path, mode: &str) -> Command {
        let mut command = Command::new(std::env::current_exe().expect("test executable"));
        command
            .arg("--exact")
            .arg("owner_fence::tests::process_probe")
            .arg("--nocapture")
            .env("AUTHBUS_OWNER_PROBE_DATABASE", database)
            .env("AUTHBUS_OWNER_PROBE_MODE", mode);
        command
    }

    struct ChildGuard(std::process::Child);

    impl Drop for ChildGuard {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    #[tokio::test]
    async fn process_probe() {
        let Some(database) = std::env::var_os("AUTHBUS_OWNER_PROBE_DATABASE") else {
            return;
        };
        let database = PathBuf::from(database);
        let mode = std::env::var("AUTHBUS_OWNER_PROBE_MODE").expect("probe mode");
        if mode == "legacy_busy" {
            let file = open_lock_file(&lock_path(&database).expect("lock path")).expect("lock file");
            assert!(matches!(
                rustix::fs::fcntl_lock(&file, rustix::fs::FlockOperation::NonBlockingLockExclusive),
                Err(error) if error == rustix::io::Errno::AGAIN || error == rustix::io::Errno::ACCESS
            ));
            return;
        }
        if mode == "busy" {
            assert!(matches!(
                OwnerFence::acquire(&database, "probe").await,
                Err(AuthBusAuthorityError::OwnerAlreadyActive)
            ));
            return;
        }
        let _owner = OwnerFence::acquire(&database, "probe").await.expect("probe owner");
        if mode == "hold" {
            std::fs::write(database.with_extension("ready"), b"locked").expect("ready marker");
            std::thread::sleep(Duration::from_secs(30));
        } else {
            assert_eq!(mode, "free");
        }
    }

    #[tokio::test]
    async fn duplicate_rejection_preserves_the_original_cross_process_lock() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let first = OwnerFence::acquire(&database, "first").await.expect("first owner");
        assert!(matches!(
            OwnerFence::acquire(&database, "second").await,
            Err(AuthBusAuthorityError::OwnerAlreadyActive)
        ));
        assert!(probe(&database, "legacy_busy").status().expect("legacy probe").success());
        assert!(probe(&database, "busy").status().expect("modern probe").success());
        drop(first);
        assert!(probe(&database, "free").status().expect("replacement probe").success());
    }

    #[tokio::test]
    async fn unrelated_descriptor_close_does_not_release_the_modern_fence() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let first = OwnerFence::acquire(&database, "first").await.expect("first owner");
        drop(File::open(lock_path(&database).expect("lock path")).expect("unrelated open"));
        assert!(probe(&database, "busy").status().expect("probe").success());
        drop(first);
        assert!(probe(&database, "free").status().expect("replacement probe").success());
    }

    #[tokio::test]
    async fn process_death_releases_owner_without_deleting_the_lock_file() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let mut child = ChildGuard(probe(&database, "hold").spawn().expect("owner process"));
        let deadline = Instant::now() + Duration::from_secs(10);
        while !database.with_extension("ready").exists() {
            assert!(Instant::now() < deadline, "child owner did not become ready");
            assert!(child.0.try_wait().expect("child state").is_none());
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(matches!(
            OwnerFence::acquire(&database, "blocked").await,
            Err(AuthBusAuthorityError::OwnerAlreadyActive)
        ));
        child.0.kill().expect("kill owner process");
        child.0.wait().expect("reap owner process");
        assert!(lock_path(&database).expect("lock path").exists());
        OwnerFence::acquire(&database, "replacement").await.expect("owner after process death");
    }

    #[tokio::test]
    async fn failed_open_does_not_leak_the_process_reservation() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let path = lock_path(&database).expect("lock path");
        std::fs::create_dir(&path).expect("invalid lock file");
        assert!(OwnerFence::acquire(&database, "failed").await.is_err());
        std::fs::remove_dir(&path).expect("remove invalid lock file");
        OwnerFence::acquire(&database, "replacement").await.expect("reservation released");
    }

    #[tokio::test]
    async fn rejects_symlink_without_touching_its_target() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let target = root.path().join("target");
        std::fs::write(&target, b"unchanged").expect("target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o640)).expect("target mode");
        symlink(&target, lock_path(&database).expect("lock path")).expect("symlink");
        assert!(matches!(
            OwnerFence::acquire(&database, "owner").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert_eq!(std::fs::metadata(&target).expect("metadata").mode() & 0o777, 0o640);
        assert_eq!(std::fs::read(&target).expect("contents"), b"unchanged");
    }

    #[tokio::test]
    async fn rejects_a_hard_link() {
        let root = private_root();
        let database = root.path().join("authority.sqlite");
        let target = root.path().join("target");
        std::fs::write(&target, b"unchanged").expect("target");
        std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600)).expect("target mode");
        std::fs::hard_link(&target, lock_path(&database).expect("lock path")).expect("hard link");
        assert!(matches!(
            OwnerFence::acquire(&database, "owner").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        assert_eq!(std::fs::metadata(&target).expect("metadata").nlink(), 2);
        assert_eq!(std::fs::read(&target).expect("contents"), b"unchanged");
    }
}
