//! Stable endpoint ownership shared by the actual secrets role services.
use crate::ConsumerPortError;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use tokio::net::UnixListener;
pub(crate) struct BoundSocket {
    path: PathBuf,
    identity: (u64, u64),
    _lock: std::fs::File,
    listener: Option<std::os::unix::net::UnixListener>,
}

impl BoundSocket {
    pub(crate) fn bind(path: &Path, group: u32) -> Result<Self, ConsumerPortError> {
        let parent = path.parent().ok_or(ConsumerPortError::Invalid)?;
        let directory = std::fs::symlink_metadata(parent).map_err(unavailable)?;
        let uid = rustix::process::geteuid().as_raw();
        if !path.is_absolute()
            || directory.file_type().is_symlink()
            || !directory.is_dir()
            || directory.uid() != uid
            || directory.gid() != group
            || directory.mode() & 0o027 != 0
        {
            return Err(ConsumerPortError::Invalid);
        }
        let lock_path = path.with_extension("stable-writer.lock");
        let lock = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .mode(0o600)
            .custom_flags(
                (rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32,
            )
            .open(lock_path)
            .map_err(unavailable)?;
        let metadata = lock.metadata().map_err(unavailable)?;
        if !metadata.is_file()
            || metadata.uid() != uid
            || metadata.nlink() != 1
            || metadata.mode() & 0o077 != 0
        {
            return Err(ConsumerPortError::Invalid);
        }
        lock.try_lock().map_err(unavailable)?;
        if let Ok(metadata) = std::fs::symlink_metadata(path) {
            if !metadata.file_type().is_socket() || metadata.uid() != uid || metadata.nlink() != 1 {
                return Err(ConsumerPortError::Invalid);
            }
            let address = rustix::net::SocketAddrUnix::new(path).map_err(unavailable)?;
            let descriptor = rustix::net::socket_with(
                rustix::net::AddressFamily::UNIX,
                rustix::net::SocketType::STREAM,
                rustix::net::SocketFlags::NONBLOCK | rustix::net::SocketFlags::CLOEXEC,
                None,
            )
            .map_err(unavailable)?;
            match rustix::net::connect(&descriptor, &address) {
                Err(rustix::io::Errno::CONNREFUSED) => {
                    // Stable writer ownership and this exact stale inode were
                    // verified before unlink. A busy/live socket is never removed.
                    let current = std::fs::symlink_metadata(path).map_err(unavailable)?;
                    if (metadata.dev(), metadata.ino()) != (current.dev(), current.ino()) {
                        return Err(ConsumerPortError::Unavailable);
                    }
                    std::fs::remove_file(path).map_err(unavailable)?;
                }
                _ => return Err(ConsumerPortError::Unavailable),
            }
        }
        let listener = std::os::unix::net::UnixListener::bind(path).map_err(unavailable)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))
            .map_err(unavailable)?;
        listener.set_nonblocking(true).map_err(unavailable)?;
        let metadata = std::fs::symlink_metadata(path).map_err(unavailable)?;
        Ok(Self {
            path: path.to_owned(),
            identity: (metadata.dev(), metadata.ino()),
            _lock: lock,
            listener: Some(listener),
        })
    }
    pub(crate) fn listener(&mut self) -> Result<UnixListener, ConsumerPortError> {
        UnixListener::from_std(self.listener.take().ok_or(ConsumerPortError::Unavailable)?)
            .map_err(unavailable)
    }
}

impl Drop for BoundSocket {
    fn drop(&mut self) {
        if let Ok(metadata) = std::fs::symlink_metadata(&self.path)
            && (metadata.dev(), metadata.ino()) == self.identity
            && metadata.file_type().is_socket()
        {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
