//! Linux admission for reads whose authority is bound to a proved file handle.
//!
//! The initial descriptor pins the inode while openat2 rejects symlink and magic-link
//! traversal during the secure reopen. Admission ends with matching namespace, mount,
//! device/inode, physical path, regular-file type and single-link metadata. Subsequent
//! reads use only that admitted descriptor. Unlike Darwin O_UNIQUE, Linux checks link
//! count after opening; this is not a claim of identical atomic kernel semantics.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::LazyLock;

use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;
use rustix::fs::AtFlags;
use rustix::fs::Mode;
use rustix::fs::OFlags;
use rustix::fs::ResolveFlags;
use rustix::fs::StatxFlags;
use tokio::io::AsyncReadExt;

use crate::FILE_READ_CHUNK_SIZE;
use crate::FileSystemSandboxContext;
use crate::local_file_system::authorize_stable_file_path;
use crate::local_file_system::authorized_read_error;
use crate::local_file_system::authorized_read_limit;
use crate::local_file_system::redact_file_access_error;

#[derive(Debug)]
struct MountNamespace {
    // Keep the namespace alive so its identity cannot be recycled during admission.
    descriptor: File,
    device: u64,
    inode: u64,
}

impl MountNamespace {
    fn capture() -> io::Result<Self> {
        let descriptor =
            File::open("/proc/thread-self/ns/mnt").map_err(redact_file_access_error)?;
        let metadata = descriptor.metadata().map_err(redact_file_access_error)?;
        Ok(Self {
            descriptor,
            device: metadata.dev(),
            inode: metadata.ino(),
        })
    }

    fn ensure_current(&self) -> io::Result<()> {
        let current = Self::capture()?;
        let pinned = self
            .descriptor
            .metadata()
            .map_err(redact_file_access_error)?;
        if current.device != pinned.dev()
            || current.inode != pinned.ino()
            || self.device != pinned.dev()
            || self.inode != pinned.ino()
        {
            return Err(authorized_read_error(io::ErrorKind::PermissionDenied));
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub(super) struct UniqueFileIdentity {
    device: u64,
    inode: u64,
    mount: u64,
    namespace: Arc<MountNamespace>,
}

fn file_identity(file: &File, namespace: Arc<MountNamespace>) -> io::Result<UniqueFileIdentity> {
    namespace.ensure_current()?;
    let metadata = file.metadata().map_err(redact_file_access_error)?;
    if !metadata.is_file() || metadata.nlink() != 1 {
        return Err(authorized_read_error(io::ErrorKind::PermissionDenied));
    }
    let stat = rustix::fs::statx(file, "", AtFlags::EMPTY_PATH, StatxFlags::MNT_ID)
        .map_err(|error| redact_file_access_error(error.into()))?;
    if stat.stx_mask & StatxFlags::MNT_ID.bits() == 0 {
        return Err(authorized_read_error(io::ErrorKind::PermissionDenied));
    }
    Ok(UniqueFileIdentity {
        device: metadata.dev(),
        inode: metadata.ino(),
        mount: stat.stx_mnt_id,
        namespace,
    })
}

pub(super) fn stable_file_path(file: &impl AsRawFd) -> io::Result<AbsolutePathBuf> {
    let fd = file.as_raw_fd();
    let path = std::fs::read_link(format!("/proc/thread-self/fd/{fd}"))
        .map_err(redact_file_access_error)?;
    if !path.is_absolute() || path.as_os_str().as_encoded_bytes().ends_with(b" (deleted)") {
        return Err(authorized_read_error(io::ErrorKind::PermissionDenied));
    }
    AbsolutePathBuf::from_absolute_path_checked(path)
        .map_err(|_| authorized_read_error(io::ErrorKind::PermissionDenied))
}

fn verify_identity(file: &File, path: &Path, expected: &UniqueFileIdentity) -> io::Result<()> {
    expected.namespace.ensure_current()?;
    if stable_file_path(file)?.as_path() != path {
        return Err(authorized_read_error(io::ErrorKind::PermissionDenied));
    }
    // This final fstat and mount check precede admission; a link introduced after
    // admission does not invalidate the already-proved descriptor.
    let actual = file_identity(file, Arc::clone(&expected.namespace))?;
    if actual.device != expected.device
        || actual.inode != expected.inode
        || actual.mount != expected.mount
    {
        return Err(authorized_read_error(io::ErrorKind::PermissionDenied));
    }
    Ok(())
}

fn secure_reopen(path: &Path, expected: &UniqueFileIdentity) -> io::Result<File> {
    expected.namespace.ensure_current()?;
    let fd = rustix::fs::openat2(
        rustix::fs::CWD,
        path,
        OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NONBLOCK | OFlags::NOCTTY,
        Mode::empty(),
        ResolveFlags::NO_SYMLINKS | ResolveFlags::NO_MAGICLINKS,
    )
    .map_err(|error| redact_file_access_error(error.into()))?;
    let file = File::from(fd);
    verify_identity(&file, path, expected)?;
    Ok(file)
}

fn admit(path: &Path, sandbox: &FileSystemSandboxContext) -> io::Result<File> {
    let namespace = Arc::new(MountNamespace::capture()?);
    let original = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK | libc::O_CLOEXEC | libc::O_NOCTTY)
        .open(path)
        .map_err(redact_file_access_error)?;
    let identity = file_identity(&original, namespace)?;
    let physical_path = stable_file_path(&original)?;
    authorize_stable_file_path(physical_path.as_path(), sandbox)?;
    let admitted = secure_reopen(physical_path.as_path(), &identity)?;
    let reopened_path = stable_file_path(&admitted)?;
    authorize_stable_file_path(reopened_path.as_path(), sandbox)?;
    verify_identity(&admitted, physical_path.as_path(), &identity)?;
    // `original` remains alive through the final identity check, preventing inode ABA.
    drop(original);
    Ok(admitted)
}

pub(super) async fn read_bounded_authorized(
    path: &PathUri,
    sandbox: &FileSystemSandboxContext,
    max_bytes: usize,
) -> io::Result<Vec<u8>> {
    if !available() {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "bounded authorized file reads are unsupported",
        ));
    }
    let limit = authorized_read_limit(max_bytes)?;
    let path = path
        .to_abs_path()
        .map_err(|_| authorized_read_error(io::ErrorKind::InvalidInput))?;
    let sandbox = sandbox.clone();
    // All path and namespace work stays on one thread. After admission, async reads
    // can move between executor threads because they use only the returned descriptor.
    let file = tokio::task::spawn_blocking(move || admit(path.as_path(), &sandbox))
        .await
        .map_err(|_| authorized_read_error(io::ErrorKind::PermissionDenied))??;
    let mut bytes = Vec::with_capacity(max_bytes.min(FILE_READ_CHUNK_SIZE));
    tokio::fs::File::from_std(file)
        .take(limit)
        .read_to_end(&mut bytes)
        .await
        .map_err(redact_file_access_error)?;
    if bytes.len() > max_bytes {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "authorized file read exceeds bound",
        ));
    }
    Ok(bytes)
}

static AVAILABLE: LazyLock<bool> = LazyLock::new(|| {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::symlink;

    let probe_dir = std::env::temp_dir().join(format!(
        "codex-linux-authorized-read-probe-{}-{}",
        std::process::id(),
        uuid::Uuid::new_v4()
    ));
    let mut builder = std::fs::DirBuilder::new();
    builder.mode(0o700);
    if builder.create(&probe_dir).is_err() {
        return false;
    }
    let result = (|| -> io::Result<bool> {
        let probe_dir = std::fs::canonicalize(&probe_dir)?;
        let path = probe_dir.join("original");
        let alias = probe_dir.join("alias");
        let link = probe_dir.join("symlink");
        std::fs::write(&path, b"probe")?;
        let original = File::open(&path)?;
        let identity = file_identity(&original, Arc::new(MountNamespace::capture()?))?;
        let physical_path = stable_file_path(&original)?;
        let admitted = secure_reopen(physical_path.as_path(), &identity)?;
        if physical_path.as_path() != path {
            return Ok(false);
        }
        // Exercise each kernel resolution flag directly: a later descriptor-path
        // comparison alone cannot prove that openat2 rejected link traversal.
        let probe_open = |path: &Path, resolve| {
            rustix::fs::openat2(
                rustix::fs::CWD,
                path,
                OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NONBLOCK | OFlags::NOCTTY,
                Mode::empty(),
                resolve,
            )
        };
        symlink(&path, &link)?;
        let ordinary_symlink_allowed = probe_open(&link, ResolveFlags::NO_MAGICLINKS).is_ok();
        let symlink_rejected = matches!(
            probe_open(&link, ResolveFlags::NO_SYMLINKS),
            Err(rustix::io::Errno::LOOP)
        );
        let fd = original.as_raw_fd();
        let magic_link_rejected = matches!(
            probe_open(
                Path::new(&format!("/proc/thread-self/fd/{fd}")),
                ResolveFlags::NO_MAGICLINKS,
            ),
            Err(rustix::io::Errno::LOOP)
        );
        std::fs::hard_link(&path, &alias)?;
        let hardlink_rejected = secure_reopen(&path, &identity).is_err();
        std::fs::remove_file(&alias)?;
        verify_identity(&admitted, &path, &identity)?;
        std::fs::remove_file(&path)?;
        let deleted_rejected = stable_file_path(&original).is_err()
            && file_identity(&original, Arc::clone(&identity.namespace)).is_err();
        Ok(ordinary_symlink_allowed
            && symlink_rejected
            && magic_link_rejected
            && hardlink_rejected
            && deleted_rejected)
    })()
    .unwrap_or(false);
    let _ = std::fs::remove_dir_all(&probe_dir);
    result
});

pub(super) fn available() -> bool {
    *AVAILABLE
}

#[cfg(test)]
pub(super) async fn unique_file_identity(file: &tokio::fs::File) -> io::Result<UniqueFileIdentity> {
    let namespace = Arc::new(MountNamespace::capture()?);
    let file = file.try_clone().await?.into_std().await;
    file_identity(&file, namespace)
}

#[cfg(test)]
pub(super) async fn secure_reopen_matching_identity(
    path: &Path,
    expected: UniqueFileIdentity,
) -> io::Result<tokio::fs::File> {
    let path = path.to_path_buf();
    let file = tokio::task::spawn_blocking(move || secure_reopen(&path, &expected))
        .await
        .map_err(|_| authorized_read_error(io::ErrorKind::PermissionDenied))??;
    Ok(tokio::fs::File::from_std(file))
}

#[cfg(test)]
#[path = "linux_authorized_read_tests.rs"]
mod tests;
