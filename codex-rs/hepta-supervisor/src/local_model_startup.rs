//! Publish Root process identity before exposing its actual Unix listener.

use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

use anyhow::Context;
use sha2::Digest;
use sha2::Sha256;
use tokio::net::UnixListener;

use super::Config;
use super::read_proc;
use super::store;
use super::store::protected_directory;

pub(super) fn publish_listener(config: &Config) -> anyhow::Result<UnixListener> {
    rustix::net::SocketAddrUnix::new(&config.issuer_socket)?;
    let parent = config
        .issuer_socket
        .parent()
        .context("issuer socket has no parent")?;
    protected_directory(parent)?;
    if config.issuer_socket.try_exists()? {
        use std::os::unix::fs::FileTypeExt;
        let metadata = std::fs::symlink_metadata(&config.issuer_socket)?;
        anyhow::ensure!(
            metadata.file_type().is_socket() && metadata.uid() == 0,
            "unexpected issuer socket identity"
        );
        anyhow::ensure!(
            std::os::unix::net::UnixStream::connect(&config.issuer_socket).is_err(),
            "model issuer already active"
        );
        std::fs::remove_file(&config.issuer_socket)?;
    }
    let pid = std::process::id();
    let stat = read_proc(pid, "stat")?;
    let (_, fields) = stat
        .rsplit_once(") ")
        .context("invalid issuer process stat")?;
    let start_time_ticks = fields
        .split_whitespace()
        .nth(19)
        .context("issuer start identity missing")?
        .parse()?;
    let executable_sha256 = format!("{:x}", Sha256::digest(std::fs::read("/proc/self/exe")?));
    let identity = codex_hepta_contracts::ModelIssuerProcessIdentity {
        schema_version: 1,
        pid,
        start_time_ticks,
        executable_sha256,
        cgroup_sha256: format!("{:x}", Sha256::digest(read_proc(pid, "cgroup")?.as_bytes())),
        boot_id_sha256: format!(
            "{:x}",
            Sha256::digest(
                std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                    .trim_end()
                    .as_bytes()
            )
        ),
    };
    store::publish_identity(
        &config.process_identity_file,
        &serde_json::to_vec(&identity)?,
        config.socket_gid,
    )?;
    // The original ProtectedFrontier/authority owners already hold their
    // physical exclusive writer locks before this private stage is called.
    // Prepare permissions before atomically exposing the same listener: a
    // non-Root workload never observes the bind-to-chown permission window.
    let temporary = parent.join(format!(
        ".i-{}",
        &uuid::Uuid::new_v4().simple().to_string()[..8]
    ));
    let listener = UnixListener::bind(&temporary)?;
    let publication = (|| -> anyhow::Result<()> {
        std::fs::set_permissions(&temporary, std::fs::Permissions::from_mode(0o660))?;
        std::os::unix::fs::chown(&temporary, Some(0), Some(config.socket_gid))?;
        std::fs::rename(&temporary, &config.issuer_socket)?;
        Ok(())
    })();
    if let Err(error) = publication {
        drop(listener);
        let _ = std::fs::remove_file(&temporary);
        return Err(error);
    }
    Ok(listener)
}

#[cfg(test)]
#[path = "local_model_startup_tests.rs"]
mod tests;
