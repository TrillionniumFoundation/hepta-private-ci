//! Original process-pinned command framing, with no owner or signing authority.
//! Only typed role clients and servers select a purpose. Existing Root and
//! evidence transports keep their separate 500 ms exchange limit unchanged.

use std::fs::File;
use std::io::Read;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;

use crate::AgentdRootAuthorityPeer;

type Error = HostIssuerTransportError;

pub(crate) fn original_owner_command_channel_v1(
    stream: UnixStream,
    peer: AgentdRootAuthorityPeer,
    uid: u32,
    original_peer_pidfd: OwnedFd,
    timeout: Duration,
    lifetime: Duration,
) -> Result<HostAuthorityPeerChannel, Error> {
    // SAFETY: these calls only observe this process's original credentials.
    let same_uid = uid == unsafe { libc::getuid() } || uid == unsafe { libc::geteuid() };
    if same_uid
        || peer.pid == std::process::id()
        || peer.pid == 0
        || peer.pid > i32::MAX as u32
        || peer.process_start_ticks == 0
        || timeout.is_zero()
        || timeout > Duration::from_secs(30)
        || lifetime.is_zero()
        || lifetime > Duration::from_secs(300)
    {
        return Err(Error::PeerDenied);
    }
    require_original_process(&peer)?;
    let channel = HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid, pid: peer.pid },
            timeout,
            lifetime,
            request_bound: 16_384,
            response_bound: 16_384,
        },
        original_peer_pidfd,
    )?;
    channel.check_peer_lifetime()?;
    require_original_process(&peer)?;
    channel.check_peer_lifetime()?;
    Ok(channel)
}

fn require_original_process(peer: &AgentdRootAuthorityPeer) -> Result<(), Error> {
    if bounded_text("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id {
        return Err(Error::PeerDenied);
    }
    let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok());
    if start != Some(peer.process_start_ticks) {
        return Err(Error::PeerDenied);
    }
    Ok(())
}

fn bounded_text(path: &str, limit: u64) -> Result<String, Error> {
    let mut text = String::new();
    File::open(path)
        .map_err(|_| Error::Unavailable)?
        .take(limit + 1)
        .read_to_string(&mut text)
        .map_err(|_| Error::Unavailable)?;
    if text.len() as u64 > limit {
        return Err(Error::Unavailable);
    }
    Ok(text)
}
