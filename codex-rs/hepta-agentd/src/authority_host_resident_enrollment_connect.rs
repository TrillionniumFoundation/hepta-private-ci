//! Daemon-side reconstruction only after the original Root handoff is pinned.

use super::wire;
use std::fs::File;
use std::io;
use std::os::fd::OwnedFd;
use std::os::unix::fs::{FileTypeExt, MetadataExt};
use std::time::{Duration, Instant};
use crate::{AgentdIdentity, AgentdRootResidentLearningClientV3, RootResidentLearningReadbackAuthorizationV3};

pub(crate) async fn connect_original_resident_enrollment(
    bootstrap: File,
    held_root_pidfd: OwnedFd,
    root_pid: u32,
    identity: &AgentdIdentity,
    idle_end: Instant,
) -> io::Result<AgentdRootResidentLearningClientV3> {
    let packet = wire::read(bootstrap)?;
    // SAFETY: these calls only inspect the actual final daemon credentials.
    let (uid, gid) = unsafe { (libc::geteuid(), libc::getegid()) };
    if packet.schema_version != 3 || packet.purpose != wire::PURPOSE
        || uid == 0 || gid == 0 || packet.consumer_uid != uid || packet.consumer_gid != gid
        || packet.consumer.pid != std::process::id() || packet.root.pid != root_pid
        || packet.root.pid == std::process::id() || !(1..=30_000).contains(&packet.command_timeout_ms)
    { return Err(io::Error::other("resident sealed purpose or recipient differs")); }
    packet.consumer.require_original()?;
    packet.root.require_original()?;
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), uid, gid)?;
    let connect_end = wire::absolute(packet.connect_before_ns, Duration::from_secs(30))?.min(idle_end);
    let session_end = wire::absolute(packet.session_end_ns, Duration::from_secs(300))?.min(idle_end);
    let trust = super::super::trust::OriginalHostTrust::from_root_enrollment(packet.trusted_evidence.as_bytes())?;
    let profile = packet.profile.original(&trust.verifier)?;
    if profile.initial().request.agent_id.as_str() != identity.agent_id.as_str()
        || packet.socket.file_name().and_then(|name| name.to_str())
            != Some(format!("lr3-{}.sock", &profile.binding().to_string()[..32]).as_str())
    { return Err(io::Error::other("resident profile or fixed socket purpose differs")); }
    validate_socket(&packet.socket, gid, packet.socket_device, packet.socket_inode)?;
    crate::root_observation_stream::check_lifetime(&held_root_pidfd).map_err(io::Error::other)?;
    let connect_timeout = wire::remaining(connect_end)?.min(Duration::from_millis(500));
    // Exactly one connection, after the original credential drop. Unknown
    // connect/handshake outcomes do not obtain a replacement socket or nonce.
    let stream = tokio::time::timeout(connect_timeout, tokio::net::UnixStream::connect(&packet.socket))
        .await.map_err(|_| io::Error::other("resident connect deadline elapsed"))??;
    validate_socket(&packet.socket, gid, packet.socket_device, packet.socket_inode)?;
    packet.consumer.require_original()?;
    packet.root.require_original()?;
    wire::remaining(connect_end)?;
    let root_pin = held_root_pidfd.try_clone()?;
    let timeout = Duration::from_millis(packet.command_timeout_ms);
    let client = match packet.authorization {
        wire::Authorization::Fresh => AgentdRootResidentLearningClientV3::from_original_root_stream(
            stream.into_std()?, packet.root.into_peer(), held_root_pidfd,
            profile, trust.verifier, timeout, wire::remaining(session_end)?,
        ),
        wire::Authorization::Readback { intent, lease } => {
            let authorization = RootResidentLearningReadbackAuthorizationV3::from_original_root(&profile, intent, lease)?;
            AgentdRootResidentLearningClientV3::recover_original_root_stream(
                stream.into_std()?, packet.root.into_peer(), held_root_pidfd,
                profile, authorization, trust.verifier, /*expected*/ None, timeout, wire::remaining(session_end)?,
            )
        }
    }.map_err(io::Error::other)?;
    crate::root_observation_stream::check_lifetime(&root_pin).map_err(io::Error::other)?;
    wire::remaining(connect_end)?;
    wire::remaining(session_end)?;
    Ok(client)
}

fn validate_socket(path: &std::path::PathBuf, gid: u32, device: u64, inode: u64) -> io::Result<()> {
    crate::authority_host_runtime::validate_lane_paths(&[path], gid)?;
    let node = std::fs::symlink_metadata(path)?;
    if !node.file_type().is_socket() || node.uid() != 0 || node.gid() != gid
        || node.nlink() != 1 || node.mode() & 0o7777 != 0o660
        || (node.dev(), node.ino()) != (device, inode)
    { return Err(io::Error::other("original Root resident socket changed")); }
    Ok(())
}
