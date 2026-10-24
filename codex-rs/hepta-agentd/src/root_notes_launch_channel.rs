//! One typed launch stream. This pins transport identity, never authority.

use super::root_notes_launch_io as sys;
use super::root_notes_launch_wire::ROOT_NOTES_LAUNCH_FRAME_BOUND;
use super::root_notes_launch_wire::ROOT_NOTES_TOTAL_PREPARATION_NS;
use super::root_notes_launch_wire::RootNotesLaunchFrame;
use super::root_notes_launch_wire::invalid;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::io::Read;
use std::io::{self};
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

/// A bounded communication channel to a peer already selected by the trusted
/// launcher. Root/Host wrappers must separately require their fixed role UIDs.
/// This type grants no Current, writer, issuer or effect permission. Its original
/// peer guard is constructed from THIS stream, never accepted from another one.
pub struct RootNotesLaunchChannel {
    stream: Option<UnixStream>,
    guard: HostAuthorityPeerChannel,
    pidfd: OwnedFd,
    peer: CognitiveCheckpointPeerLifetime,
    end: u64,
    closed: Arc<AtomicBool>,
}

/// Cancellation capability with no read/write or descriptor accessor. Dropping
/// an armed capability permanently shuts down the channel, including a worker
/// currently blocked in a bounded poll. Successful handoff must call disarm.
pub struct RootNotesLaunchAbort {
    stream: Option<UnixStream>,
    closed: Arc<AtomicBool>,
}
impl RootNotesLaunchAbort {
    pub fn disarm(mut self) {
        self.stream.take();
    }
}
impl Drop for RootNotesLaunchAbort {
    fn drop(&mut self) {
        if let Some(stream) = &self.stream {
            self.closed.store(true, Ordering::Release);
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}

impl RootNotesLaunchChannel {
    /// No connect, pidfd-open, retry, role selection or lifetime renewal occurs.
    /// `peer` and the already held pidfd must come from the trusted launcher;
    /// matching SO_PEERCRED alone does not establish that trust provenance.
    pub fn from_peer_stream(
        stream: UnixStream,
        peer: CognitiveCheckpointPeerLifetime,
        pidfd: OwnedFd,
        end_boottime_ns: u64,
    ) -> io::Result<Self> {
        let lifetime = remaining(end_boottime_ns)?;
        if lifetime.as_nanos() > u128::from(ROOT_NOTES_TOTAL_PREPARATION_NS)
            || peer.pid == 0
            || peer.pid > i32::MAX as u32
            || peer.process_start_ticks == 0
        {
            return Err(invalid());
        }
        validate_process(&peer)?;
        let guard = HostAuthorityPeerChannel::from_stream(
            stream.try_clone()?,
            policy(&peer, lifetime),
            pidfd.try_clone()?,
        )
        .map_err(io::Error::other)?;
        let channel = Self {
            stream: Some(stream),
            guard,
            pidfd,
            peer,
            end: end_boottime_ns,
            closed: Arc::new(AtomicBool::new(false)),
        };
        channel.check(end_boottime_ns)?;
        Ok(channel)
    }
    pub fn peer(&self) -> &CognitiveCheckpointPeerLifetime {
        &self.peer
    }
    pub fn check(&self, deadline_boottime_ns: u64) -> io::Result<()> {
        let result = (|| {
            if self.closed.load(Ordering::Acquire) {
                return Err(invalid());
            }
            remaining(deadline_boottime_ns.min(self.end))?;
            self.guard.check_peer_lifetime().map_err(io::Error::other)?;
            validate_process(&self.peer)?;
            remaining(deadline_boottime_ns.min(self.end))?;
            Ok(())
        })();
        if result.is_err() {
            self.close();
        }
        result
    }
    pub fn abort_handle(&self) -> io::Result<RootNotesLaunchAbort> {
        self.check(self.end)?;
        Ok(RootNotesLaunchAbort {
            stream: Some(self.stream.as_ref().ok_or_else(invalid)?.try_clone()?),
            closed: Arc::clone(&self.closed),
        })
    }
    /// Validate a later descriptor against the same pinned peer and same actual
    /// stream. This does not replace the original pidfd or extend its deadline.
    pub fn require_same_peer_pidfd(
        &self,
        pidfd: &OwnedFd,
        deadline_boottime_ns: u64,
    ) -> io::Result<()> {
        let result = (|| {
            self.check(deadline_boottime_ns)?;
            let guard = HostAuthorityPeerChannel::from_stream(
                self.stream.as_ref().ok_or_else(invalid)?.try_clone()?,
                policy(&self.peer, remaining(deadline_boottime_ns.min(self.end))?),
                pidfd.try_clone()?,
            )
            .map_err(io::Error::other)?;
            guard.check_peer_lifetime().map_err(io::Error::other)?;
            self.check(deadline_boottime_ns)
        })();
        if result.is_err() {
            self.close();
        }
        result
    }
    /// Receive exactly one frame under the supplied absolute phase deadline.
    /// Waiting for byte one uses that deadline; the rest of the frame also has
    /// a 500ms bound from byte one. Rights are accepted only with that byte.
    pub fn read(
        &mut self,
        deadline_boottime_ns: u64,
    ) -> io::Result<(RootNotesLaunchFrame, Vec<OwnedFd>)> {
        let stream = self.stream.take().ok_or_else(invalid)?;
        let result = self.read_inner(&stream, deadline_boottime_ns.min(self.end));
        self.finish(stream, result.is_ok());
        result
    }
    fn read_inner(
        &self,
        stream: &UnixStream,
        end: u64,
    ) -> io::Result<(RootNotesLaunchFrame, Vec<OwnedFd>)> {
        let mut header = [0; 4];
        let mut descriptors = Vec::new();
        let end = self.read_exact(
            stream,
            &mut header[..1],
            &mut descriptors,
            Rights::FirstByte,
            end,
        )?;
        self.read_exact(
            stream,
            &mut header[1..],
            &mut descriptors,
            Rights::Forbidden,
            end,
        )?;
        let length = u32::from_be_bytes(header) as usize;
        if length == 0 || length > ROOT_NOTES_LAUNCH_FRAME_BOUND {
            return Err(invalid());
        }
        let mut bytes = vec![0; length];
        self.read_exact(stream, &mut bytes, &mut descriptors, Rights::Forbidden, end)?;
        let frame: RootNotesLaunchFrame = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
        frame.validate()?;
        if descriptors.len() != frame.descriptor_count() {
            return Err(invalid());
        }
        self.check(end)?;
        Ok((frame, descriptors))
    }
    fn read_exact(
        &self,
        stream: &UnixStream,
        mut bytes: &mut [u8],
        descriptors: &mut Vec<OwnedFd>,
        mut rights: Rights,
        mut end: u64,
    ) -> io::Result<u64> {
        while !bytes.is_empty() {
            self.wait(stream, libc::POLLIN, end)?;
            // Sample before the successful nonblocking first-byte read. A
            // scheduling delay or later process checks must not renew 500ms.
            let before_read = now()?;
            let (count, received) = match sys::receive(stream, bytes) {
                Err(error) if transient(&error) => continue,
                result => result?,
            };
            if matches!(rights, Rights::FirstByte) {
                end = end.min(before_read.saturating_add(500_000_000));
            }
            self.check(end)?;
            if (!matches!(rights, Rights::FirstByte) && !received.is_empty())
                || descriptors.len() + received.len() > 2
            {
                return Err(invalid());
            }
            descriptors.extend(received);
            rights = Rights::Forbidden;
            bytes = &mut bytes[count..];
        }
        Ok(end)
    }
    /// Send a complete frame within 500ms and the supplied absolute deadline.
    pub fn send(
        &mut self,
        frame: &RootNotesLaunchFrame,
        descriptors: &[OwnedFd],
        deadline_boottime_ns: u64,
    ) -> io::Result<()> {
        let stream = self.stream.take().ok_or_else(invalid)?;
        let result = self.send_inner(
            &stream,
            frame,
            descriptors,
            deadline_boottime_ns.min(self.end),
        );
        self.finish(stream, result.is_ok());
        result
    }
    fn send_inner(
        &self,
        stream: &UnixStream,
        frame: &RootNotesLaunchFrame,
        descriptors: &[OwnedFd],
        end: u64,
    ) -> io::Result<()> {
        frame.validate()?;
        if descriptors.len() != frame.descriptor_count() {
            return Err(invalid());
        }
        let body = serde_json::to_vec(frame).map_err(io::Error::other)?;
        if body.is_empty() || body.len() > ROOT_NOTES_LAUNCH_FRAME_BOUND {
            return Err(invalid());
        }
        let mut raw = (body.len() as u32).to_be_bytes().to_vec();
        raw.extend(body);
        let end = end.min(now()?.saturating_add(500_000_000));
        let mut offset = 0;
        while offset < raw.len() {
            self.wait(stream, libc::POLLOUT, end)?;
            let count = match sys::send(
                stream,
                &raw[offset..],
                if offset == 0 { descriptors } else { &[] },
            ) {
                Err(error) if transient(&error) => continue,
                result => result?,
            };
            self.check(end)?;
            offset += count;
        }
        Ok(())
    }
    fn wait(&self, stream: &UnixStream, events: i16, end: u64) -> io::Result<()> {
        loop {
            self.check(end)?;
            let millis = remaining(end.min(self.end))?
                .as_nanos()
                .div_ceil(1_000_000)
                .min(10) as i32;
            let ready = match sys::poll(&self.pidfd, stream, events, millis) {
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                result => result?,
            };
            self.check(end)?;
            if ready {
                return Ok(());
            }
        }
    }
    fn close(&self) {
        self.closed.store(true, Ordering::Release);
        if let Some(stream) = &self.stream {
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
    fn finish(&mut self, stream: UnixStream, success: bool) {
        if success {
            self.stream = Some(stream);
        } else {
            self.closed.store(true, Ordering::Release);
            let _ = stream.shutdown(Shutdown::Both);
        }
    }
}
impl Drop for RootNotesLaunchChannel {
    fn drop(&mut self) {
        self.close();
    }
}

enum Rights {
    FirstByte,
    Forbidden,
}
fn transient(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::Interrupted | io::ErrorKind::WouldBlock
    )
}
fn policy(peer: &CognitiveCheckpointPeerLifetime, lifetime: Duration) -> HostAuthorityPeerPolicy {
    HostAuthorityPeerPolicy {
        peer: HostIssuerPeer {
            uid: peer.uid,
            pid: peer.pid,
        },
        timeout: Duration::from_millis(500),
        lifetime,
        request_bound: ROOT_NOTES_LAUNCH_FRAME_BOUND,
        response_bound: ROOT_NOTES_LAUNCH_FRAME_BOUND,
    }
}
fn now() -> io::Result<u64> {
    crate::root_observation_cache::boottime_ns().map_err(io::Error::other)
}
fn remaining(end: u64) -> io::Result<Duration> {
    end.checked_sub(now()?)
        .filter(|value| *value > 0)
        .map(Duration::from_nanos)
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "Root Notes launch deadline"))
}
fn bounded_text(path: &str, bound: usize) -> io::Result<String> {
    let mut value = String::new();
    std::fs::File::open(path)?
        .take(bound as u64 + 1)
        .read_to_string(&mut value)?;
    if value.len() > bound {
        return Err(invalid());
    }
    Ok(value)
}
pub(crate) fn validate_process(peer: &CognitiveCheckpointPeerLifetime) -> io::Result<()> {
    let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
    let status = bounded_text(&format!("/proc/{}/status", peer.pid), 8192)?;
    let fields: Vec<_> = stat
        .rsplit_once(") ")
        .ok_or_else(invalid)?
        .1
        .split_whitespace()
        .collect();
    let uids: Vec<u32> = status
        .lines()
        .find_map(|line| line.strip_prefix("Uid:"))
        .ok_or_else(invalid)?
        .split_whitespace()
        .map(str::parse)
        .collect::<Result<_, _>>()
        .map_err(|_| invalid())?;
    if fields
        .first()
        .is_none_or(|value| matches!(*value, "Z" | "X"))
        || fields.get(19).and_then(|value| value.parse::<u64>().ok())
            != Some(peer.process_start_ticks)
        || uids != vec![peer.uid; 4]
        || bounded_text("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id
    {
        return Err(invalid());
    }
    Ok(())
}

#[cfg(test)]
#[path = "root_notes_launch_channel_tests.rs"]
mod tests;
