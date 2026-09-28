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
/// The file is opened without following the final symlink, validated through
/// its descriptor and locked non-blockingly. The descriptor remains owned by
/// this value, so normal exit and process death both release the fence. A local
/// registry closes the process-associated `fcntl` same-process gap.
pub(crate) struct OwnerFence {
    // Rust drops fields in declaration order: close BEFORE releasing the
    // in-process reservation, including when another thread is acquiring.
    _file: File,
    _claim: ProcessOwnerClaim,
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
        // Reserve before opening: closing ANY descriptor for a POSIX-locked
        // inode releases this process's locks, even on duplicate-open failure.
        let claim = ProcessOwnerClaim::acquire(&path)?;
        let file = open_lock_file(&path)?;
        validate_open_lock_file(&file, &path)?;
        acquire_process_lock(&file)?;
        // Ensure the pathname still names the locked inode before exposing the
        // host. Protected owner directories exclude unprivileged replacement.
        validate_open_lock_file(&file, &path)?;
        Ok(Self {
            _file: file,
            _claim: claim,
        })
    }
}

// This reservation also rolls back failed open/validation/OS-lock attempts.
struct ProcessOwnerClaim {
    path: PathBuf,
}

impl ProcessOwnerClaim {
    fn acquire(path: &Path) -> Result<Self, AuthBusAuthorityError> {
        claim_process_owner(path)?;
        Ok(Self {
            path: path.to_path_buf(),
        })
    }
}

impl Drop for ProcessOwnerClaim {
    fn drop(&mut self) {
        release_process_owner(&self.path);
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

fn claim_process_owner(path: &Path) -> Result<(), AuthBusAuthorityError> {
    let mut owners = PROCESS_OWNERS
        .get_or_init(|| Mutex::new(HashSet::new()))
        .lock()
        .map_err(|_| AuthBusAuthorityError::Storage("owner registry poisoned".into()))?;
    if !owners.insert(path.to_path_buf()) {
        return Err(AuthBusAuthorityError::OwnerAlreadyActive);
    }
    Ok(())
}

fn release_process_owner(path: &Path) {
    if let Ok(mut owners) = PROCESS_OWNERS
        .get_or_init(|| Mutex::new(HashSet::new()))
        .lock()
    {
        owners.remove(path);
    }
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

    #[expect(clippy::expect_used, reason = "private test fixture setup must fail the test")]
    pub(super) fn private_root() -> tempfile::TempDir {
        let root = tempfile::tempdir().expect("temporary directory");
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private temporary directory");
        root
    }

    #[tokio::test]
    async fn rejects_a_second_live_owner_and_releases_after_drop() {
        let root = private_root();
        let database = root
            .path()
            .canonicalize()
            .expect("canonical root")
            .join("authority.sqlite");
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
        let database = root
            .path()
            .canonicalize()
            .expect("canonical root")
            .join("authority.sqlite");
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
        let database = root
            .path()
            .canonicalize()
            .expect("canonical root")
            .join("authority.sqlite");
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

#[cfg(all(test, unix))]
pub(crate) mod regression_tests {
    use super::*;
    use std::process::Command;
    use std::time::Duration;
    use std::time::Instant;

    #[expect(clippy::expect_used, reason = "subprocess probe failures must fail the calling test")]
    pub(crate) fn probe(database: &Path, expected_blocked: bool) {
        let mut child = Command::new(std::env::current_exe().expect("test executable"))
            .arg("owner_fence::regression_tests::child_probes_os_lock")
            .arg("--exact")
            .arg("--nocapture")
            .env("AUTHBUS_FENCE_PROBE_DB", database)
            .env(
                "AUTHBUS_FENCE_EXPECT_BLOCKED",
                if expected_blocked { "1" } else { "0" },
            )
            .spawn()
            .expect("spawn lock probe");
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if let Some(status) = child.try_wait().expect("poll probe") {
                assert!(status.success(), "OS lock probe failed");
                break;
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("OS lock probe exceeded deadline");
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }

    #[tokio::test]
    async fn duplicate_open_does_not_release_existing_process_lock() {
        let root = super::tests::private_root();
        let database = root
            .path()
            .canonicalize()
            .expect("canonical")
            .join("authority.sqlite");
        let first = OwnerFence::acquire(&database, "first")
            .await
            .expect("first owner");
        for _ in 0..3 {
            assert!(matches!(
                OwnerFence::acquire(&database, "duplicate").await,
                Err(AuthBusAuthorityError::OwnerAlreadyActive)
            ));
        }
        probe(&database, true);
        drop(first);
        probe(&database, false);
    }

    #[tokio::test]
    async fn failed_lock_file_validation_releases_process_reservation() {
        use std::os::unix::fs::PermissionsExt;
        let root = super::tests::private_root();
        let database = root
            .path()
            .canonicalize()
            .expect("canonical")
            .join("authority.sqlite");
        let path = lock_path(&database).expect("lock path");
        std::fs::write(&path, b"").expect("unsafe file");
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).expect("mode");
        assert!(matches!(
            OwnerFence::acquire(&database, "unsafe").await,
            Err(AuthBusAuthorityError::UnsafeCheckpoint)
        ));
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("fix mode");
        let owner = OwnerFence::acquire(&database, "fixed")
            .await
            .expect("reservation rolled back");
        probe(&database, true);
        drop(owner);
    }

    #[tokio::test]
    async fn child_probes_os_lock() {
        let Some(database) = std::env::var_os("AUTHBUS_FENCE_PROBE_DB") else {
            return;
        };
        let expected = std::env::var("AUTHBUS_FENCE_EXPECT_BLOCKED").expect("expected") == "1";
        let result = OwnerFence::acquire(Path::new(&database), "child").await;
        if expected {
            assert!(matches!(
                result,
                Err(AuthBusAuthorityError::OwnerAlreadyActive)
            ));
        } else {
            assert!(result.is_ok(), "unlocked inode should be available");
        }
    }
}
