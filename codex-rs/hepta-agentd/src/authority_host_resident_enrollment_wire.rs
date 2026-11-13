//! Private sealed V3 enrollment description. Data cannot construct role owners.

use std::fs::File;
use std::io::{self, Read, Seek, Write};
use std::path::PathBuf;
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};

use super::super::inputs::EnrollmentProfile;
use crate::AgentdRootAuthorityPeer;

pub(super) const PURPOSE: &str = "hepta.original-root-resident-enrollment.v3";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Packet {
    pub(super) schema_version: u32,
    pub(super) purpose: String,
    pub(super) root: Process,
    pub(super) consumer: Process,
    pub(super) consumer_uid: u32,
    pub(super) consumer_gid: u32,
    pub(super) profile: EnrollmentProfile,
    pub(super) trusted_evidence: String,
    pub(super) socket: PathBuf,
    pub(super) socket_device: u64,
    pub(super) socket_inode: u64,
    pub(super) connect_before_ns: u64,
    pub(super) session_end_ns: u64,
    pub(super) command_timeout_ms: u64,
    pub(super) authorization: Authorization,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "purpose", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Authorization {
    Fresh,
    Readback {
        intent: codex_hepta_contracts::SignedFinalUseGrant,
        lease: codex_hepta_contracts::authority_lease::AuthorityLease,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Process {
    pub(super) pid: u32,
    pub(super) boot_id: String,
    pub(super) process_start_ticks: u64,
}

impl Process {
    pub(super) fn current() -> io::Result<Self> {
        let pid = std::process::id();
        let boot_id = text("/proc/sys/kernel/random/boot_id", 128)?.trim().to_string();
        Ok(Self { pid, boot_id, process_start_ticks: start(pid)? })
    }

    pub(super) fn from_peer(peer: &AgentdRootAuthorityPeer) -> Self {
        Self { pid: peer.pid, boot_id: peer.boot_id.clone(), process_start_ticks: peer.process_start_ticks }
    }

    pub(super) fn require_original(&self) -> io::Result<()> {
        if self.pid == 0 || self.pid > i32::MAX as u32 || self.process_start_ticks == 0
            || self.boot_id.is_empty() || self.boot_id.len() > 128
            || text("/proc/sys/kernel/random/boot_id", 128)?.trim() != self.boot_id
            || start(self.pid)? != self.process_start_ticks
        {
            return Err(io::Error::other("original resident process identity differs"));
        }
        Ok(())
    }

    pub(super) fn into_peer(self) -> AgentdRootAuthorityPeer {
        AgentdRootAuthorityPeer { pid: self.pid, boot_id: self.boot_id, process_start_ticks: self.process_start_ticks }
    }
}

fn text(path: &str, bound: u64) -> io::Result<String> {
    let mut text = String::new();
    File::open(path)?.take(bound + 1).read_to_string(&mut text)?;
    if text.len() as u64 > bound { return Err(io::Error::other("resident identity bound exceeded")); }
    Ok(text)
}

fn start(pid: u32) -> io::Result<u64> {
    text(&format!("/proc/{pid}/stat"), 8192)?.rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse().ok())
        .ok_or_else(|| io::Error::other("original process start missing"))
}

pub(super) fn now_ns() -> io::Result<u64> {
    let mut now = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: clock_gettime receives one initialized writable timespec.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) } != 0 {
        return Err(io::Error::last_os_error());
    }
    u64::try_from(now.tv_sec).ok()
        .and_then(|seconds| seconds.checked_mul(1_000_000_000))
        .and_then(|seconds| u64::try_from(now.tv_nsec).ok().filter(|n| *n < 1_000_000_000)
            .and_then(|nanos| seconds.checked_add(nanos)))
        .ok_or_else(|| io::Error::other("invalid original monotonic clock"))
}

pub(super) fn absolute(end_ns: u64, maximum: Duration) -> io::Result<Instant> {
    // Sample Instant first so translating an external absolute clock cannot
    // extend its remaining budget by the time spent reading CLOCK_MONOTONIC.
    let instant = Instant::now();
    let remaining = end_ns.checked_sub(now_ns()?).filter(|n| *n != 0)
        .map(Duration::from_nanos).filter(|n| *n <= maximum)
        .ok_or_else(|| io::Error::other("resident absolute deadline differs"))?;
    instant.checked_add(remaining).ok_or_else(|| io::Error::other("resident deadline overflow"))
}

pub(super) fn remaining(end: Instant) -> io::Result<Duration> {
    end.checked_duration_since(Instant::now()).filter(|n| !n.is_zero())
        .ok_or_else(|| io::Error::other("resident original deadline elapsed"))
}

pub(super) fn seal(packet: &Packet) -> io::Result<File> {
    let mut writer = Bounded(Vec::new());
    serde_json::to_writer(&mut writer, packet).map_err(io::Error::other)?;
    crate::authority_host_bootstrap_seal::seal_bytes(&writer.0)
}

pub(super) fn read(mut file: File) -> io::Result<Packet> {
    let size = file.metadata()?.len();
    if size == 0 || size > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
        return Err(io::Error::other("resident sealed descriptor bound exceeded"));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    file.rewind()?;
    let mut raw = Vec::new();
    Read::by_ref(&mut file).take(crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 + 1).read_to_end(&mut raw)?;
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    if raw.len() as u64 != size { return Err(io::Error::other("resident sealed bytes changed")); }
    serde_json::from_slice(&raw).map_err(io::Error::other)
}

struct Bounded(Vec<u8>);
impl Write for Bounded {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND.saturating_sub(self.0.len()) {
            return Err(io::Error::other("resident sealed descriptor bound exceeded"));
        }
        self.0.extend_from_slice(bytes); Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> { Ok(()) }
}

#[cfg(test)]
#[path = "authority_host_resident_enrollment_wire_tests.rs"]
mod tests;
