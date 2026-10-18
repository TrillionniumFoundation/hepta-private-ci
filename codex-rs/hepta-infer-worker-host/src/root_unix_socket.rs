//! Bind the original finite Root endpoints in their enrolled Unix namespace.
//! This transport helper carries no process registry, journal or effect owner.
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;
use anyhow::ensure;
use tokio::net::UnixListener;
use tokio::net::UnixStream;

pub(super) struct SocketGuard {
    path: PathBuf,
    dev: u64,
    ino: u64,
}

impl Drop for SocketGuard {
    fn drop(&mut self) {
        if std::fs::symlink_metadata(&self.path).is_ok_and(|metadata| {
            metadata.file_type().is_socket()
                && metadata.dev() == self.dev
                && metadata.ino() == self.ino
        }) {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

pub(super) async fn bind_socket(path: &Path, group: u32) -> Result<(UnixListener, SocketGuard)> {
    ensure!(
        rustix::process::geteuid().as_raw() == 0,
        "endpoint binding requires actual Root"
    );
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("missing socket directory"))?;
    ensure!(
        parent.is_absolute() && parent.canonicalize()? == parent,
        "socket directory must be canonical"
    );
    for ancestor in parent.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        ensure!(
            metadata.is_dir() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0,
            "socket namespace must be Root protected"
        );
    }
    let metadata = std::fs::symlink_metadata(parent)?;
    ensure!(
        metadata.gid() == group && metadata.mode() & 0o7777 == 0o750,
        "runtime directory must be Root:enrolled-group 0750"
    );
    match std::fs::symlink_metadata(path) {
        Ok(before) => {
            ensure!(
                before.file_type().is_socket() && before.uid() == 0 && before.gid() == group,
                "existing endpoint is not an owned socket"
            );
            match UnixStream::connect(path).await {
                Err(error) if error.kind() == std::io::ErrorKind::ConnectionRefused => {
                    let after = std::fs::symlink_metadata(path)?;
                    ensure!(
                        after.file_type().is_socket()
                            && before.dev() == after.dev()
                            && before.ino() == after.ino(),
                        "socket namespace changed"
                    );
                    std::fs::remove_file(path)?;
                }
                _ => anyhow::bail!("endpoint listener already present"),
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let listener = UnixListener::bind(path)?;
    let before = std::fs::symlink_metadata(path)?;
    let guard = SocketGuard {
        path: path.to_owned(),
        dev: before.dev(),
        ino: before.ino(),
    };
    ensure!(
        before.file_type().is_socket() && before.uid() == 0,
        "new endpoint is not a Root socket"
    );
    // A 0750 directory does not confer its group on new sockets. Explicitly
    // bind the enrolled group even when Root's effective group is different.
    std::os::unix::fs::chown(path, Some(0), Some(group))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))?;
    let after = std::fs::symlink_metadata(path)?;
    ensure!(
        after.file_type().is_socket()
            && after.dev() == guard.dev
            && after.ino() == guard.ino
            && after.uid() == 0
            && after.gid() == group
            && after.mode() & 0o7777 == 0o660,
        "bound endpoint identity or enrollment changed"
    );
    Ok((listener, guard))
}

#[cfg(test)]
#[path = "root_unix_socket_tests.rs"]
mod tests;
