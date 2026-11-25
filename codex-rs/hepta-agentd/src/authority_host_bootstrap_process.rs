//! Actual process checks, separate from a pidfd's numeric PID identity.
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::fs::File;
use std::io;
use std::io::Read;

pub(super) const CONSUMER_UID: u32 = 60001;

fn bounded(path: impl AsRef<std::path::Path>, bound: usize) -> io::Result<String> {
    let mut text = String::new();
    File::open(path)?.take(bound as u64 + 1).read_to_string(&mut text)?;
    if text.len() > bound {
        return Err(io::Error::other("process metadata exceeds bound"));
    }
    Ok(text)
}

fn start_ticks(pid: u32) -> io::Result<u64> {
    bounded(format!("/proc/{pid}/stat"), 8192)?
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("invalid actual process start"))
}

fn exact_ids(status: &str, field: &str, expected: u32) -> bool {
    let mut entries = status.lines().filter_map(|line| line.strip_prefix(field));
    let Some(value) = entries.next() else { return false; };
    let ids: Vec<_> = value.split_whitespace().map(str::parse::<u32>).collect();
    entries.next().is_none() && ids.len() == 4 && ids.iter().all(|id| *id == Ok(expected))
}

pub(super) fn current_root() -> io::Result<CognitiveCheckpointPeerLifetime> {
    // SAFETY: geteuid has no arguments and reads only the actual caller UID.
    if unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, "actual Root required"));
    }
    let pid = std::process::id();
    if !exact_ids(&bounded("/proc/self/status", 16 * 1024)?, "Uid:", 0) {
        return Err(io::Error::other("Root process must have four actual Root UIDs"));
    }
    Ok(CognitiveCheckpointPeerLifetime {
        uid: 0,
        pid,
        boot_id: bounded("/proc/sys/kernel/random/boot_id", 128)?.trim().into(),
        process_start_ticks: start_ticks(pid)?,
    })
}

pub(super) fn verify_consumer(peer: &CognitiveCheckpointPeerLifetime) -> io::Result<()> {
    if peer.uid != CONSUMER_UID || peer.pid == 0 || peer.pid > i32::MAX as u32
        || peer.process_start_ticks == 0
        || bounded("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id
        || start_ticks(peer.pid)? != peer.process_start_ticks
    {
        return Err(io::Error::other("fixed Host lifetime mismatch"));
    }
    let status = bounded(format!("/proc/{}/status", peer.pid), 16 * 1024)?;
    if !exact_ids(&status, "Uid:", CONSUMER_UID)
        || !exact_ids(&status, "Gid:", CONSUMER_UID)
        || !status.lines().any(|line| line == "NoNewPrivs:\t1")
        || ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"].iter().any(|field| {
            !status.lines().any(|line| line.strip_prefix(field)
                .is_some_and(|value| value == ":\t0000000000000000"))
        })
        || !status.lines().any(|line| line.strip_prefix("Groups:")
            .is_some_and(|groups| groups.split_whitespace().next().is_none()))
    {
        return Err(io::Error::other("Host must retain dedicated UID/GID, zero caps/groups and NNP"));
    }
    Ok(())
}

pub(super) fn verify_root(root: &CognitiveCheckpointPeerLifetime) -> io::Result<()> {
    if current_root()? != *root {
        return Err(io::Error::other("bootstrap Root lifetime changed"));
    }
    Ok(())
}
