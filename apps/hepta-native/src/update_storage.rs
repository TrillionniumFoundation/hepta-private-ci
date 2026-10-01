use crate::error::ShellError;
use crate::private_state::PrivateStateRoot;
use crate::update_lock::UpdateLock;
use atomic_write_file::AtomicWriteFile;
use serde::Serialize;
use serde::de::DeserializeOwned;
use sha2::Digest as _;
use sha2::Sha256;
use std::fs::File;
use std::io::Read as _;
use std::io::Write as _;
use std::path::Path;
pub(crate) const MAX_PACKAGE_BYTES: u64 = 512 * 1024 * 1024;

pub fn digest_file(path: &Path) -> Result<String, ShellError> {
    digest_open_file(crate::file_input::open_regular_file(path)?)
}

pub(crate) fn digest_private_file(
    root: &PrivateStateRoot,
    path: &Path,
) -> Result<String, ShellError> {
    let file = open_staged_file(root, path)?;
    let digest = digest_open_file(file)?;
    root.verify()?;
    Ok(digest)
}

fn open_staged_file(root: &PrivateStateRoot, path: &Path) -> Result<File, ShellError> {
    // Older releases copied a downloaded package's mode into this owned child.
    // Tighten only a current-principal staging file, using the same descriptor.
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt as _;
        use std::os::unix::fs::PermissionsExt as _;
        root.verify()?;
        if path.parent() != Some(root.path()) {
            return Err(ShellError::Security(
                "staged package is outside its pinned root".into(),
            ));
        }
        let name = path
            .file_name()
            .ok_or_else(|| ShellError::Security("staged package has no name".into()))?;
        let file: File = rustix::fs::openat(
            root.directory_handle(),
            name,
            rustix::fs::OFlags::RDONLY
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::NONBLOCK
                | rustix::fs::OFlags::CLOEXEC,
            rustix::fs::Mode::empty(),
        )
        .map_err(std::io::Error::from)?
        .into();
        let metadata = file.metadata()?;
        if !metadata.is_file() || metadata.uid() != rustix::process::geteuid().as_raw() {
            return Err(ShellError::Security(
                "staged package is not a current-principal regular file".into(),
            ));
        }
        #[cfg(target_os = "macos")]
        codex_utils_private_state::verify_private_permissions(&file)?;
        if metadata.permissions().mode() & 0o777 != 0o600 {
            if metadata.nlink() != 1 {
                return Err(ShellError::Security(
                    "staged permission migration requires a single-link file".into(),
                ));
            }
            file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
        }
        root.verify()?;
        Ok(file)
    }
    #[cfg(not(unix))]
    crate::journal_storage::open_private_file_in(
        root,
        path,
        crate::journal_storage::FileAccess::Read,
        true,
    )
}

pub(crate) fn running_binary_digest() -> Result<String, ShellError> {
    #[cfg(target_os = "linux")]
    {
        // This kernel-owned link resolves the actual loaded executable inode,
        // not an unrelated replacement installed at the same pathname.
        digest_open_file(File::open("/proc/self/exe")?)
    }
    #[cfg(not(target_os = "linux"))]
    {
        digest_file(&std::env::current_exe()?)
    }
}

fn digest_open_file(mut file: File) -> Result<String, ShellError> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        total = total.saturating_add(read as u64);
        if total > MAX_PACKAGE_BYTES {
            return Err(ShellError::Update(format!(
                "file exceeds {MAX_PACKAGE_BYTES} bytes"
            )));
        }
        hasher.update(&buffer[..read]);
    }
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut out, "{byte:02x}");
    }
    Ok(out)
}

pub(crate) fn copy_and_sync(
    source: &Path,
    destination: &Path,
    expected_digest: &str,
) -> Result<(), ShellError> {
    copy_at_boundaries(source, destination, expected_digest, None, None, |_| Ok(()))
}

pub(crate) fn copy_to_private_root(
    root: &PrivateStateRoot,
    source: &Path,
    destination: &Path,
    expected_digest: &str,
) -> Result<(), ShellError> {
    copy_at_boundaries(
        source,
        destination,
        expected_digest,
        None,
        Some(root),
        |_| Ok(()),
    )
}

pub(crate) fn copy_from_private_root(
    root: &PrivateStateRoot,
    source: &Path,
    destination: &Path,
    expected_digest: &str,
) -> Result<(), ShellError> {
    copy_at_boundaries(
        source,
        destination,
        expected_digest,
        Some(root),
        None,
        |_| Ok(()),
    )
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum CopyBoundary {
    ParentVerified,
    Opened,
    FileSynced,
}

fn copy_at_boundaries(
    source: &Path,
    destination: &Path,
    expected_digest: &str,
    source_root: Option<&PrivateStateRoot>,
    private_root: Option<&PrivateStateRoot>,
    mut observe: impl FnMut(CopyBoundary) -> Result<(), ShellError>,
) -> Result<(), ShellError> {
    crate::model::validate_digest(expected_digest, "update copy digest")?;
    if let Some(root) = private_root {
        root.verify()?;
        if destination.parent() != Some(root.path()) {
            return Err(ShellError::Security(
                "staged update is outside its pinned root".into(),
            ));
        }
    } else if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent)?;
    }
    observe(CopyBoundary::ParentVerified)?;
    #[cfg(any(target_os = "macos", windows))]
    if let Some(root) = private_root {
        crate::journal_storage::verify_private_destination(root, destination)?;
    }
    let source_file = if let Some(root) = source_root {
        open_staged_file(root, source)?
    } else {
        crate::file_input::open_regular_file(source)?
    };
    let source_metadata = source_file.metadata()?;
    if source_metadata.len() > MAX_PACKAGE_BYTES {
        return Err(ShellError::Update(
            "copy source exceeds the package bound".into(),
        ));
    }
    let mut destination_file = AtomicWriteFile::open(destination)?;
    #[cfg(unix)]
    if let Some(root) = private_root {
        let directory = destination_file.directory().ok_or_else(|| {
            ShellError::Security("staged update copy lacks its parent descriptor".into())
        })?;
        let actual = rustix::fs::fstat(directory).map_err(std::io::Error::from)?;
        let expected = rustix::fs::fstat(root.directory_handle()).map_err(std::io::Error::from)?;
        if actual.st_dev != expected.st_dev || actual.st_ino != expected.st_ino {
            return Err(ShellError::Security(
                "staged update parent identity changed".into(),
            ));
        }
        #[cfg(target_os = "macos")]
        {
            use std::os::unix::fs::PermissionsExt as _;
            codex_utils_private_state::verify_private_permissions(destination_file.as_file())?;
            destination_file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
        }
    }
    #[cfg(windows)]
    if let Some(root) = private_root {
        root.verify_mutable_file(destination_file.as_file())?;
    }
    observe(CopyBoundary::Opened)?;
    #[cfg(any(target_os = "macos", windows))]
    {
        if let Some(root) = private_root {
            root.verify()?;
            #[cfg(target_os = "macos")]
            codex_utils_private_state::verify_private_permissions(destination_file.as_file())?;
            #[cfg(windows)]
            root.verify_mutable_file(destination_file.as_file())?;
            crate::journal_storage::verify_private_destination(root, destination)?;
        }
        if let Some(root) = source_root {
            root.verify()?;
            #[cfg(target_os = "macos")]
            codex_utils_private_state::verify_private_permissions(&source_file)?;
            #[cfg(windows)]
            root.verify_file(&source_file)?;
        }
    }
    let mut incoming = source_file.take(MAX_PACKAGE_BYTES + 1);
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut copied = 0_u64;
    loop {
        let read = incoming.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        copied += read as u64;
        if copied > MAX_PACKAGE_BYTES {
            return Err(ShellError::Update(
                "copy source grew beyond the package bound".into(),
            ));
        }
        destination_file.write_all(&buffer[..read])?;
        hasher.update(&buffer[..read]);
    }
    // The signature authorizes the bytes copied from this handle, not an
    // earlier pathname read. Reject drift before publishing an executable or
    // replacing the only admitted predecessor backup.
    if format!("{:x}", hasher.finalize()) != expected_digest {
        return Err(ShellError::Security(
            "update copy digest mismatch before atomic replacement".into(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        let mode = if private_root.is_some() {
            0o600
        } else {
            match std::fs::symlink_metadata(destination) {
                Ok(metadata) if metadata.is_file() => metadata.permissions().mode(),
                Ok(_) => {
                    return Err(ShellError::Update(
                        "copy destination is not a regular file".into(),
                    ));
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    source_metadata.permissions().mode()
                }
                Err(error) => return Err(error.into()),
            }
        };
        // New backups retain executable bits. Existing installed binaries keep
        // their mode even when an operator downloads a non-executable package.
        destination_file.set_permissions(std::fs::Permissions::from_mode(mode & 0o777))?;
    }
    destination_file.flush()?;
    destination_file.sync_all()?;
    observe(CopyBoundary::FileSynced)?;
    if let Some(root) = private_root {
        root.verify()?;
        #[cfg(any(target_os = "macos", windows))]
        {
            #[cfg(target_os = "macos")]
            codex_utils_private_state::verify_private_permissions(destination_file.as_file())?;
            #[cfg(windows)]
            root.verify_mutable_file(destination_file.as_file())?;
            crate::journal_storage::verify_private_destination(root, destination)?;
        }
    }
    if let Some(root) = source_root {
        root.verify()?;
        #[cfg(target_os = "macos")]
        codex_utils_private_state::verify_private_permissions(incoming.get_ref())?;
        #[cfg(windows)]
        root.verify_file(incoming.get_ref())?;
    }
    destination_file.commit()?;
    if let Some(root) = private_root {
        sync_private_root(root)?;
    } else {
        sync_parent_directory(destination)?;
    }
    Ok(())
}

pub(crate) fn persist_json_atomic(
    root: &PrivateStateRoot,
    path: &Path,
    value: &impl Serialize,
) -> Result<(), ShellError> {
    persist_json_at_boundary(root, path, value, || Ok(()))
}

fn persist_json_at_boundary(
    root: &PrivateStateRoot,
    path: &Path,
    value: &impl Serialize,
    observe: impl FnOnce() -> Result<(), ShellError>,
) -> Result<(), ShellError> {
    root.verify()?;
    let bytes = serde_json::to_vec(value)?;
    observe()?;
    crate::journal_storage::write_private(root, path, &bytes)
}

pub(crate) fn read_private_json<T: DeserializeOwned>(
    root: &PrivateStateRoot,
    path: &Path,
    maximum: u64,
) -> Result<Option<T>, ShellError> {
    let file = match crate::journal_storage::open_private_file_in(
        root,
        path,
        crate::journal_storage::FileAccess::Read,
        true,
    ) {
        Ok(file) => file,
        Err(ShellError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
            root.verify()?;
            return Ok(None);
        }
        Err(error) => return Err(error),
    };
    if file.metadata()?.len() > maximum {
        return Err(ShellError::Update(
            "private update JSON exceeds its byte limit".into(),
        ));
    }
    let mut bytes = Vec::new();
    file.take(
        maximum
            .checked_add(1)
            .ok_or_else(|| ShellError::Update("private update JSON byte limit overflow".into()))?,
    )
    .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(ShellError::Update(
            "private update JSON grew beyond its byte limit".into(),
        ));
    }
    root.verify()?;
    Ok(Some(serde_json::from_slice(&bytes)?))
}

pub(crate) fn remove_private_file(root: &PrivateStateRoot, path: &Path) -> Result<(), ShellError> {
    root.verify()?;
    match crate::journal_storage::remove_private_file_in(root, path) {
        Ok(()) => sync_private_root(root),
        Err(ShellError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => root.verify(),
        Err(error) => Err(error),
    }
}

fn sync_private_root(root: &PrivateStateRoot) -> Result<(), ShellError> {
    #[cfg(unix)]
    root.directory_handle().sync_all()?;
    root.verify()
}

#[cfg(unix)]
pub(crate) fn sync_parent_directory(path: &Path) -> Result<(), ShellError> {
    if let Some(parent) = path.parent() {
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

#[cfg(not(unix))]
pub(crate) fn sync_parent_directory(_path: &Path) -> Result<(), ShellError> {
    Ok(())
}

// Shared by GUI transitions and the updater helper; never held across GUI life.
pub(crate) fn lock_update_root(root: &PrivateStateRoot) -> Result<UpdateLock, ShellError> {
    lock_named(root, "update-owner.lock", || Ok(()))
}

/// Readiness publication, C consumption, and cancellation contend on one pinned
/// owner. Retry contention only; directory replacement remains an error.
pub(crate) fn lock_update_handoff(root: &PrivateStateRoot) -> Result<UpdateLock, ShellError> {
    lock_handoff_at_contention(root, || Ok(()))
}

fn lock_handoff_at_contention(
    root: &PrivateStateRoot,
    mut observe: impl FnMut() -> Result<(), ShellError>,
) -> Result<UpdateLock, ShellError> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    loop {
        match lock_update_root(root) {
            Err(ShellError::Update(_)) if std::time::Instant::now() < deadline => {
                observe()?;
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            result => return result,
        }
    }
}

pub(crate) fn lock_update_runner(root: &PrivateStateRoot) -> Result<UpdateLock, ShellError> {
    lock_named(root, "update-runner.lock", || Ok(()))
}

fn lock_named(
    root: &PrivateStateRoot,
    name: &str,
    observe: impl FnOnce() -> Result<(), ShellError>,
) -> Result<UpdateLock, ShellError> {
    root.verify()?;
    let path = root.path().join(name);
    let preexisting = !std::fs::symlink_metadata(&path)
        .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound);
    observe()?;
    let file = crate::journal_storage::open_private_file_in(
        root,
        &path,
        crate::journal_storage::FileAccess::Lock,
        preexisting,
    )?;
    let lock = UpdateLock::try_acquire(file).map_err(|error| match error {
        std::fs::TryLockError::WouldBlock => {
            ShellError::Update("another native update transition is in progress".to_owned())
        }
        std::fs::TryLockError::Error(error) => error.into(),
    })?;
    root.verify()?;
    Ok(lock)
}

#[cfg(test)]
#[path = "update_storage_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "update_root_storage_tests.rs"]
mod root_tests;

#[cfg(all(test, target_os = "macos"))]
#[path = "update_storage_macos_tests.rs"]
mod macos_tests;

#[cfg(all(test, windows))]
#[path = "update_storage_windows_tests.rs"]
mod windows_tests;
