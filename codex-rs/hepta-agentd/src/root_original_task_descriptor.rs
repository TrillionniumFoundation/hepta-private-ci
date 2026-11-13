//! One sealed, purpose-fixed Root task offer. Its bounded data are not task
//! authority: the receiver still authenticates the same Root on both live
//! lanes, and only the daemon's original signed RunStart can borrow them.

use std::ffi::OsString;
use std::fs::File;
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::os::unix::fs::FileExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use codex_hepta_types::Digest32;

use crate::{AgentdError, AgentdIdentity, CircuitCellRegistryV1, CircuitTaskSourceInputV1};
use crate::circuit_task::root_bootstrap_codec::{BOUND, Reader, Writer};
use codex_hepta_automation::TaskFlowFence;

const DOMAIN: &[u8] = b"HEPTA_ROOT_ORIGINAL_TASK_OFFER_V1";

pub(crate) struct Descriptor {
    pub(crate) root_pid: u32,
    pub(crate) daemon_pid: u32,
    pub(crate) daemon_uid: u32,
    pub(crate) daemon_gid: u32,
    pub(crate) task_path: PathBuf,
    pub(crate) loan_path: PathBuf,
    pub(crate) nonce: [u8; 16],
    pub(crate) end: Instant,
    pub(crate) capacity: usize,
    pub(crate) binding: Digest32,
    pub(crate) fence: TaskFlowFence,
    pub(crate) registry: CircuitCellRegistryV1,
    pub(crate) source: CircuitTaskSourceInputV1,
}

/// Called only while the retained Root factory and Source are still current.
/// No caller supplies a decoded Source, Cell, request or permission object.
pub(crate) fn seal(
    root_pid: u32, daemon_pid: u32, daemon_uid: u32, daemon_gid: u32,
    task_path: &Path, loan_path: &Path, nonce: [u8; 16], end: Instant,
    capacity: usize, binding: Digest32, registry: &[u8], source: &[u8],
) -> Result<File, AgentdError> {
    if root_pid != std::process::id()
        || rustix::process::getuid().as_raw() != 0 || rustix::process::geteuid().as_raw() != 0
        || daemon_pid == 0 || daemon_pid == root_pid || daemon_uid == 0 || daemon_gid == 0
        || nonce == [0; 16] || !(1..=64).contains(&capacity) || binding.is_zero()
    { return Err(refused("original Root task offer identity differs")); }
    let mut out = Writer::new(DOMAIN);
    for value in [root_pid, daemon_pid, daemon_uid, daemon_gid] { out.u32(value).map_err(protocol)?; }
    for path in [task_path, loan_path] {
        validate_path(path)?;
        out.bytes(path.as_os_str().as_bytes()).map_err(protocol)?;
    }
    out.raw(&nonce).map_err(protocol)?;
    out.u64(to_monotonic_end(end)?).map_err(protocol)?;
    out.size(capacity).map_err(protocol)?;
    out.digest(binding).map_err(protocol)?;
    out.bytes(registry).map_err(protocol)?;
    out.bytes(source).map_err(protocol)?;
    require_before(end)?;
    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(&out.finish())?;
    require_before(end)?;
    Ok(sealed)
}

pub(crate) fn read(file: &File, root_pid: u32) -> Result<Descriptor, AgentdError> {
    let length = file.metadata()?.len();
    if length == 0 || length > BOUND as u64 { return Err(refused("bounded task offer required")); }
    crate::authority_host_bootstrap_seal::validate_sealed(file, length)?;
    let mut bytes = vec![0; length as usize];
    file.read_exact_at(&mut bytes, 0)?;
    let mut reader = Reader::new(&bytes, DOMAIN).map_err(protocol)?;
    let captured_root = reader.u32().map_err(protocol)?;
    let daemon_pid = reader.u32().map_err(protocol)?;
    let daemon_uid = reader.u32().map_err(protocol)?;
    let daemon_gid = reader.u32().map_err(protocol)?;
    if captured_root != root_pid || root_pid == std::process::id()
        || daemon_pid != std::process::id() || daemon_uid == 0 || daemon_gid == 0
        || daemon_uid != rustix::process::getuid().as_raw()
        || daemon_uid != rustix::process::geteuid().as_raw()
        || daemon_gid != rustix::process::getgid().as_raw()
        || daemon_gid != rustix::process::getegid().as_raw()
    { return Err(refused("original task offer is for a different real process")); }
    let task_path = read_path(&mut reader)?;
    let loan_path = read_path(&mut reader)?;
    crate::authority_host_runtime::validate_lane_paths(&[&task_path, &loan_path], daemon_gid)?;
    let nonce = reader.take().map_err(protocol)?;
    let end = from_monotonic_end(reader.u64().map_err(protocol)?)?;
    let capacity = reader.size().map_err(protocol)?;
    let binding = reader.digest().map_err(protocol)?;
    let registry = crate::circuit_cell_binding::root_bootstrap::decode(reader.bytes().map_err(protocol)?)
        .map_err(protocol)?;
    let (fence, source) = crate::circuit_task::decode_original_root_source(reader.bytes().map_err(protocol)?)
        .map_err(protocol)?;
    reader.end().map_err(protocol)?;
    if nonce == [0; 16] || !(1..=64).contains(&capacity) || binding.is_zero() {
        return Err(refused("original task offer data differs"));
    }
    require_before(end)?;
    Ok(Descriptor { root_pid, daemon_pid, daemon_uid, daemon_gid, task_path, loan_path,
        nonce, end, capacity, binding, fence, registry, source })
}

impl Descriptor {
    pub(crate) fn require_original_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        let binding = crate::circuit_task::original_root_source_binding(
            identity, &self.fence, &self.registry, &self.source).map_err(protocol)?;
        if self.binding != binding || self.daemon_pid != std::process::id()
            || self.daemon_uid != rustix::process::geteuid().as_raw()
            || self.daemon_gid != rustix::process::getegid().as_raw()
        { return Err(refused("task offer does not match the same original daemon Config")); }
        require_before(self.end)
    }
}

fn read_path(reader: &mut Reader<'_>) -> Result<PathBuf, AgentdError> {
    let path = PathBuf::from(OsString::from_vec(reader.bytes().map_err(protocol)?.to_vec()));
    validate_path(&path)?;
    Ok(path)
}

fn validate_path(path: &Path) -> Result<(), AgentdError> {
    if !path.is_absolute() || path.as_os_str().as_bytes().len() >= 108
        || path.components().any(|part| !matches!(part, std::path::Component::RootDir | std::path::Component::Normal(_)))
    { return Err(refused("canonical absolute original task socket path required")); }
    Ok(())
}

fn monotonic_nanos() -> Result<u64, AgentdError> {
    let mut now = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: clock_gettime writes one initialized scalar timespec.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    if now.tv_sec < 0 || !(0..1_000_000_000).contains(&now.tv_nsec) {
        return Err(refused("invalid original monotonic clock"));
    }
    (now.tv_sec as u64).checked_mul(1_000_000_000)
        .and_then(|value| value.checked_add(now.tv_nsec as u64))
        .ok_or_else(|| refused("original task monotonic clock overflow"))
}

fn to_monotonic_end(end: Instant) -> Result<u64, AgentdError> {
    // Kernel clock first, Instant second: conversion can only shorten the end.
    let now = monotonic_nanos()?;
    let remaining = end.checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero() && *value <= Duration::from_secs(300))
        .ok_or_else(|| refused("original task operation expired"))?;
    now.checked_add(u64::try_from(remaining.as_nanos()).map_err(|_| refused("task end overflow"))?)
        .ok_or_else(|| refused("original task end overflow"))
}

fn from_monotonic_end(end: u64) -> Result<Instant, AgentdError> {
    // Instant first, kernel clock second: receipt never renews Root's end.
    let local = Instant::now();
    let remaining = end.checked_sub(monotonic_nanos()?)
        .filter(|value| *value > 0 && *value <= 300_000_000_000)
        .ok_or_else(|| refused("original task offer expired"))?;
    local.checked_add(Duration::from_nanos(remaining)).ok_or_else(|| refused("task end overflow"))
}

pub(crate) fn require_before(end: Instant) -> Result<(), AgentdError> {
    if Instant::now() >= end { return Err(refused("original task operation expired")); }
    Ok(())
}

pub(crate) fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("original Root task handoff: {error}"))
}

fn refused(message: &str) -> AgentdError { AgentdError::Invalid(message.into()) }
