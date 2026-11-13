//! One fixed resident socket under the original Root-controlled runtime parent.

use super::*;
use codex_hepta_types::Digest32;
use std::path::PathBuf;

pub(crate) struct ResidentSocketGuard { _guard: SocketGuard }

pub(crate) struct ResidentListener {
    listener: tokio::net::UnixListener,
    guard: ResidentSocketGuard,
    path: PathBuf,
    device: u64,
    inode: u64,
}

impl ResidentListener {
    pub(crate) fn bind_original(
        config: &HostAuthorityServiceConfig,
        profile: Digest32,
    ) -> io::Result<Self> {
        // SAFETY: these calls only inspect current credentials.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
            return Err(io::Error::other("resident listener requires original Root"));
        }
        let parent = config.sockets.observation.parent()
            .ok_or_else(|| io::Error::other("missing original runtime parent"))?;
        let path = parent.join(format!("lr3-{}.sock", &profile.to_string()[..32]));
        validate_lane_paths(&[&path], config.peer_gid)?;
        // UnixListener::bind is create-only. Never unlink an occupied name.
        let listener = UnixListener::bind(&path)?;
        let created = std::fs::symlink_metadata(&path)?;
        let guard = SocketGuard(vec![(path.clone(), created.dev(), created.ino())]);
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o660))?;
        let node = std::fs::symlink_metadata(&path)?;
        if node.uid() != 0 || node.gid() != config.peer_gid
            || node.nlink() != 1 || node.mode() & 0o7777 != 0o660
            || (node.dev(), node.ino()) != (created.dev(), created.ino())
        {
            return Err(io::Error::other("original resident socket custody differs"));
        }
        validate_lane_paths(&[&path], config.peer_gid)?;
        listener.set_nonblocking(true)?;
        Ok(Self {
            listener: tokio::net::UnixListener::from_std(listener)?,
            guard: ResidentSocketGuard { _guard: guard }, path, device: node.dev(), inode: node.ino(),
        })
    }

    pub(crate) fn original_node(&self) -> (&PathBuf, u64, u64) {
        (&self.path, self.device, self.inode)
    }

    /// Consume one connection or fail. There is no accept retry after refusal.
    pub(crate) async fn accept_original(self, end: Instant) -> io::Result<(std::os::unix::net::UnixStream, ResidentSocketGuard)> {
        if Instant::now() >= end {
            return Err(io::Error::other("resident handoff deadline elapsed"));
        }
        let (stream, _) = tokio::time::timeout_at(
            tokio::time::Instant::from_std(end), self.listener.accept(),
        ).await.map_err(|_| io::Error::other("resident accept deadline elapsed"))??;
        if Instant::now() >= end {
            return Err(io::Error::other("resident accept completed after deadline"));
        }
        Ok((stream.into_std()?, self.guard))
        // Keep exact pathname custody until the original service finishes.
    }
}
