//! Synchronous, purpose-limited client for the original consumer frontier.

use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::FinalUseFrontier;
use crate::HostConsumerFrontierRequestV1 as Request;
use crate::HostConsumerFrontierResponseV1 as Response;
use crate::HostConsumerFrontierStatusV1 as Status;
use crate::authority_host_issuer_transport::channel::OwnerChannel;
use std::io::Read;
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;

const FRAME_LIMIT: usize = 16 * 1024;

/// Root process incarnation pinned by the trusted launcher before FD transfer.
/// The original pidfd is required; this client never opens one from this PID.
pub struct RootPeerIdentity {
    pub pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
}

struct Channel {
    stream: UnixStream,
    next_request_id: u64,
}

/// The launcher supplies the exclusive connected fourth lane and fixed owner.
/// There is no reconnect, initialization, reset, owner selector or admin RPC.
/// Calls perform synchronous persistence I/O: use only at the original
/// FinalUseAuthority store boundary, never in clock/live-verifier callbacks.
/// Uncertain results map to Unavailable and permanently close the lane because
/// AuthorityTrustError has no Unknown variant. Never retry the uncertain CAS.
pub struct RootFinalUseFrontierClient {
    channel: Mutex<Option<Channel>>,
    root: OwnerChannel,
    owner_id: String,
    timeout: Duration,
}

impl RootFinalUseFrontierClient {
    /// Public construction always requires a UID 0 peer, exact process
    /// incarnation and pre-held pidfd. Caller must transfer sole stream use.
    pub fn from_stream(
        stream: UnixStream,
        owner_id: String,
        peer: RootPeerIdentity,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, AuthorityTrustError> {
        Self::from_stream_for_uid(stream, owner_id, peer, root_pidfd, timeout, lifetime, 0)
    }

    fn from_stream_for_uid(
        stream: UnixStream,
        owner_id: String,
        peer: RootPeerIdentity,
        root_pidfd: OwnedFd,
        timeout: Duration,
        lifetime: Duration,
        uid: u32,
    ) -> Result<Self, AuthorityTrustError> {
        if owner_id.is_empty()
            || owner_id.len() > 256
            || peer.pid == 0
            || peer.pid > i32::MAX as u32
            || peer.process_start_ticks == 0
            || timeout.is_zero()
            || timeout > Duration::from_secs(5)
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let root = OwnerChannel::new(root_pidfd, peer.pid, lifetime).map_err(unavailable)?;
        let actual = rustix::net::sockopt::socket_peercred(&stream).map_err(unavailable)?;
        let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok());
        if actual.uid.as_raw() != uid
            || actual.pid.as_raw_nonzero().get() as u32 != peer.pid
            || bounded_text("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id
            || start != Some(peer.process_start_ticks)
        {
            return Err(AuthorityTrustError::Invalid);
        }
        stream.set_nonblocking(true).map_err(unavailable)?;
        root.check(root.end()).map_err(unavailable)?;
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                stream,
                next_request_id: 1,
            })),
            root,
            owner_id,
            timeout,
        })
    }

    fn exchange(
        &self,
        owner_id: &str,
        update: Option<(&FinalUseFrontier, &FinalUseFrontier)>,
    ) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        // Concurrent original-owner misuse never queues an unbounded wait or
        // interleaves bytes. It emits no request and grants no authority.
        let mut slot = self.channel.try_lock().map_err(unavailable)?;
        let mut channel = slot.take().ok_or(AuthorityTrustError::Unavailable)?;
        let result = (|| {
            let id = channel.next_request_id;
            channel.next_request_id = id.checked_add(1).ok_or(AuthorityTrustError::Unavailable)?;
            let request = match update {
                Some((expected, next)) => Request::CompareAndSet {
                    schema_version: 1,
                    request_id: id,
                    expected: *expected,
                    next: *next,
                },
                None => Request::Load {
                    schema_version: 1,
                    request_id: id,
                },
            };
            let bytes = serde_json::to_vec(&request).map_err(unavailable)?;
            if bytes.is_empty() || bytes.len() > FRAME_LIMIT {
                return Err(AuthorityTrustError::Unavailable);
            }
            let deadline = self.root.deadline(self.timeout);
            self.root.check(deadline).map_err(unavailable)?;
            self.root
                .write_until(
                    &mut channel.stream,
                    &(bytes.len() as u32).to_be_bytes(),
                    deadline,
                )
                .map_err(unavailable)?;
            self.root
                .write_until(&mut channel.stream, &bytes, deadline)
                .map_err(unavailable)?;
            let mut prefix = [0; 4];
            self.root
                .read_until(&mut channel.stream, &mut prefix, deadline)
                .map_err(unavailable)?;
            let length = u32::from_be_bytes(prefix) as usize;
            if length == 0 || length > FRAME_LIMIT {
                return Err(AuthorityTrustError::Unavailable);
            }
            let mut bytes = vec![0; length];
            self.root
                .read_until(&mut channel.stream, &mut bytes, deadline)
                .map_err(unavailable)?;
            let response: Response = serde_json::from_slice(&bytes).map_err(unavailable)?;
            self.root.check(deadline).map_err(unavailable)?;
            if response.schema_version != 1 || response.request_id != id {
                return Err(AuthorityTrustError::Unavailable);
            }
            match response.status {
                Status::Ack => {
                    let frontier = response.frontier.ok_or(AuthorityTrustError::Unavailable)?;
                    if update.is_some_and(|(_, next)| *next != frontier) {
                        return Err(AuthorityTrustError::Unavailable);
                    }
                    Ok(frontier)
                }
                Status::Conflict if update.is_some() => Err(AuthorityTrustError::Conflict),
                Status::Conflict | Status::Unknown => Err(AuthorityTrustError::Unavailable),
            }
        })();
        if result.is_ok() || result == Err(AuthorityTrustError::Conflict) {
            *slot = Some(channel);
        } else {
            let _ = channel.stream.shutdown(Shutdown::Both);
        }
        result
    }
}

impl AuthorityFrontierStore<FinalUseFrontier> for RootFinalUseFrontierClient {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        self.exchange(owner_id, None)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        self.exchange(owner_id, Some((expected, next))).map(|_| ())
    }
}

fn bounded_text(path: &str, limit: u64) -> Result<String, AuthorityTrustError> {
    let mut text = String::new();
    std::fs::File::open(path)
        .map_err(unavailable)?
        .take(limit + 1)
        .read_to_string(&mut text)
        .map_err(unavailable)?;
    if text.len() as u64 > limit {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok(text)
}

fn unavailable<T>(_: T) -> AuthorityTrustError {
    AuthorityTrustError::Unavailable
}

#[cfg(test)]
#[path = "authority_root_frontier_tests.rs"]
mod tests;
