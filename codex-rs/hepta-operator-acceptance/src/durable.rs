use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use serde::Serialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

use crate::AcceptanceError;

pub(crate) const MAX_SMALL_FILE_BYTES: usize = 1024 * 1024;
pub(crate) const MAX_ARTIFACT_BYTES: u64 = 2 * 1024 * 1024 * 1024;

pub(crate) fn canonical_json<T: Serialize>(value: &T) -> Result<Vec<u8>, AcceptanceError> {
    let mut value = serde_json::to_value(value)
        .map_err(|error| AcceptanceError::Serialization(error.to_string()))?;
    sort_value(&mut value);
    serde_json::to_vec(&value).map_err(|error| AcceptanceError::Serialization(error.to_string()))
}

pub(crate) fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(crate) fn secure_root(path: &Path, label: &str) -> Result<PathBuf, AcceptanceError> {
    if !path.is_absolute() {
        return Err(invalid(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(invalid(format!(
            "{label} must already be canonical and contain no symlink components"
        )));
    }
    verify_secure_directory(&canonical, label)?;
    Ok(canonical)
}

pub(crate) fn secure_canonical_file_path(
    path: &Path,
    label: &str,
) -> Result<PathBuf, AcceptanceError> {
    if !path.is_absolute() {
        return Err(invalid(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(invalid(format!(
            "{label} must already be canonical and contain no symlink components"
        )));
    }
    let metadata = std::fs::symlink_metadata(&canonical)?;
    verify_regular_metadata(&metadata, label)?;
    Ok(canonical)
}

pub(crate) fn verify_secure_directory(path: &Path, label: &str) -> Result<(), AcceptanceError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(invalid(format!("{label} must be a real directory")));
    }
    verify_private_mode(&metadata, label)
}

pub(crate) fn secure_read(path: &Path, max_bytes: usize) -> Result<Vec<u8>, AcceptanceError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    let mut file = options.open(path)?;
    let before = file.metadata()?;
    verify_regular_metadata(&before, "input artifact")?;
    if before.len() > max_bytes as u64 {
        return Err(invalid("input artifact exceeds its read bound"));
    }
    let mut bytes = Vec::new();
    (&mut file)
        .take(max_bytes.saturating_add(1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > max_bytes {
        return Err(invalid("input artifact exceeds its read bound"));
    }
    let after_fd = file.metadata()?;
    let after_path = std::fs::metadata(path)?;
    let after_link = std::fs::symlink_metadata(path)?;
    if after_link.file_type().is_symlink()
        || !same_file_snapshot(&before, &after_fd)
        || !same_file_snapshot(&before, &after_path)
    {
        return Err(invalid("input artifact changed while it was read"));
    }
    Ok(bytes)
}

pub(crate) fn secure_hash(path: &Path) -> Result<(String, u64), AcceptanceError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    let mut file = options.open(path)?;
    let before = file.metadata()?;
    verify_regular_metadata(&before, "manifest artifact")?;
    if before.len() > MAX_ARTIFACT_BYTES {
        return Err(invalid("manifest artifact exceeds the 2 GiB bound"));
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 128 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    let after_fd = file.metadata()?;
    let after_path = std::fs::metadata(path)?;
    let after_link = std::fs::symlink_metadata(path)?;
    if after_link.file_type().is_symlink()
        || !same_file_snapshot(&before, &after_fd)
        || !same_file_snapshot(&before, &after_path)
    {
        return Err(invalid("manifest artifact changed while it was hashed"));
    }
    Ok((format!("{:x}", hasher.finalize()), before.len()))
}

pub(crate) fn write_private_new(path: &Path, bytes: &[u8]) -> Result<(), AcceptanceError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("sidecar artifact has no parent"))?;
    verify_secure_directory(parent, "sidecar directory")?;
    let parent_before = std::fs::symlink_metadata(parent)?;
    let mut options = OpenOptions::new();
    options.create_new(true).read(true).write(true);
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
    let fd_after = file.metadata()?;
    let path_after = std::fs::metadata(path)?;
    let link_after = std::fs::symlink_metadata(path)?;
    verify_regular_metadata(&link_after, "sidecar artifact")?;
    if link_after.file_type().is_symlink()
        || !same_file_snapshot(&fd_after, &path_after)
        || !same_file_snapshot(&fd_after, &link_after)
    {
        return Err(invalid(
            "sidecar artifact path changed during durable write",
        ));
    }
    file.seek(SeekFrom::Start(0))?;
    let mut fd_bytes = Vec::with_capacity(bytes.len());
    file.read_to_end(&mut fd_bytes)?;
    if fd_bytes != bytes || secure_read(path, bytes.len())? != bytes {
        return Err(invalid("sidecar artifact differs after durable write"));
    }
    let parent_after = std::fs::symlink_metadata(parent)?;
    if parent_after.file_type().is_symlink() || !same_file_identity(&parent_before, &parent_after) {
        return Err(invalid("sidecar parent changed during durable write"));
    }
    File::open(parent)?.sync_all()?;
    Ok(())
}

pub(crate) fn write_private_atomic_replace(
    path: &Path,
    temporary_path: &Path,
    bytes: &[u8],
) -> Result<(), AcceptanceError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("sidecar artifact has no parent"))?;
    if temporary_path.parent() != Some(parent) || temporary_path == path {
        return Err(invalid(
            "atomic sidecar temporary path must be a distinct sibling",
        ));
    }
    verify_secure_directory(parent, "sidecar directory")?;
    if let Ok(metadata) = std::fs::symlink_metadata(path) {
        verify_regular_metadata(&metadata, "replaced sidecar artifact")?;
    }
    write_private_new(temporary_path, bytes)?;
    let parent_before = std::fs::symlink_metadata(parent)?;
    let rename_result = std::fs::rename(temporary_path, path);
    if rename_result.is_err() {
        let _ = std::fs::remove_file(temporary_path);
    }
    rename_result?;
    let parent_after = std::fs::symlink_metadata(parent)?;
    if parent_after.file_type().is_symlink() || !same_file_identity(&parent_before, &parent_after) {
        return Err(invalid("sidecar parent changed during atomic replace"));
    }
    let persisted = secure_read(path, bytes.len())?;
    if persisted != bytes {
        return Err(invalid("atomic sidecar artifact differs after persistence"));
    }
    File::open(parent)?.sync_all()?;
    Ok(())
}

pub(crate) struct SidecarLock {
    _file: File,
}

pub(crate) fn lock_sidecar(root: &Path) -> Result<SidecarLock, AcceptanceError> {
    open_sidecar_lock(root, /*create*/ true)
}

pub(crate) fn lock_existing_sidecar(root: &Path) -> Result<SidecarLock, AcceptanceError> {
    open_sidecar_lock(root, /*create*/ false)
}

fn open_sidecar_lock(root: &Path, create: bool) -> Result<SidecarLock, AcceptanceError> {
    verify_secure_directory(root, "sidecar directory")?;
    let path = root.join(".operator-acceptance.lock");
    let mut options = OpenOptions::new();
    options.create(create).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW);
    }
    let file = options.open(&path).map_err(|error| {
        if !create && error.kind() == std::io::ErrorKind::NotFound {
            invalid("read-only receipt verification requires the existing sidecar lock")
        } else {
            error.into()
        }
    })?;
    let fd_metadata = file.metadata()?;
    let path_metadata = std::fs::metadata(&path)?;
    let link_metadata = std::fs::symlink_metadata(&path)?;
    verify_regular_metadata(&fd_metadata, "sidecar lock")?;
    if link_metadata.file_type().is_symlink()
        || !same_file_snapshot(&fd_metadata, &path_metadata)
        || !same_file_snapshot(&fd_metadata, &link_metadata)
    {
        return Err(invalid("sidecar lock path changed while it was opened"));
    }
    #[cfg(unix)]
    {
        use std::os::fd::AsRawFd;
        // SAFETY: `flock` receives a live file descriptor and integer flags;
        // it does not dereference application memory.
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(invalid(
                "another operator-acceptance process holds the sidecar lock",
            ));
        }
    }
    Ok(SidecarLock { _file: file })
}

impl Drop for SidecarLock {
    fn drop(&mut self) {
        #[cfg(unix)]
        {
            use std::os::fd::AsRawFd;
            // SAFETY: `flock` receives the still-live descriptor owned by this
            // guard and does not dereference application memory.
            let _ = unsafe { libc::flock(self._file.as_raw_fd(), libc::LOCK_UN) };
        }
    }
}

pub(crate) fn ensure_disjoint_roots(
    sidecar: &Path,
    qualification: &Path,
    product_audit: &Path,
) -> Result<(), AcceptanceError> {
    if sidecar.starts_with(qualification)
        || qualification.starts_with(sidecar)
        || sidecar.starts_with(product_audit)
        || product_audit.starts_with(sidecar)
    {
        return Err(invalid(
            "sidecar root must be disjoint from both immutable evidence roots",
        ));
    }
    Ok(())
}

fn verify_regular_metadata(
    metadata: &std::fs::Metadata,
    label: &str,
) -> Result<(), AcceptanceError> {
    if !metadata.is_file() {
        return Err(invalid(format!("{label} must be a regular file")));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1 {
            return Err(invalid(format!("{label} must have exactly one hard link")));
        }
    }
    verify_private_mode(metadata, label)
}

#[cfg(unix)]
fn verify_private_mode(metadata: &std::fs::Metadata, label: &str) -> Result<(), AcceptanceError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(invalid(format!(
            "{label} must not grant group or other access"
        )));
    }
    // SAFETY: `geteuid` takes no arguments, has no preconditions, and does
    // not expose or mutate memory.
    let effective_uid = unsafe { libc::geteuid() };
    if metadata.uid() != effective_uid {
        return Err(invalid(format!(
            "{label} must be owned by the effective user"
        )));
    }
    Ok(())
}

#[cfg(not(unix))]
fn verify_private_mode(_metadata: &std::fs::Metadata, _label: &str) -> Result<(), AcceptanceError> {
    Ok(())
}

fn same_file_snapshot(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        before.dev() == after.dev()
            && before.ino() == after.ino()
            && before.len() == after.len()
            && before.mtime() == after.mtime()
            && before.mtime_nsec() == after.mtime_nsec()
            && before.ctime() == after.ctime()
            && before.ctime_nsec() == after.ctime_nsec()
            && before.mode() == after.mode()
            && before.nlink() == after.nlink()
    }
    #[cfg(not(unix))]
    {
        before.len() == after.len() && before.modified().ok() == after.modified().ok()
    }
}

fn same_file_identity(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        before.dev() == after.dev() && before.ino() == after.ino()
    }
    #[cfg(not(unix))]
    {
        before.is_dir() == after.is_dir()
    }
}

fn sort_value(value: &mut Value) {
    match value {
        Value::Array(items) => items.iter_mut().for_each(sort_value),
        Value::Object(map) => {
            let mut entries = std::mem::take(map).into_iter().collect::<Vec<_>>();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            for (_, item) in &mut entries {
                sort_value(item);
            }
            map.extend(entries);
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

fn invalid(message: impl Into<String>) -> AcceptanceError {
    AcceptanceError::Invalid(message.into())
}
