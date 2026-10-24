//! Own only a child created by this Root launcher. No numeric-PID adoption.

use codex_hepta_contracts::HostAuthorityOwnerLifetime;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::process::ExitStatusExt;
use std::process::ExitStatus;
use std::time::Duration;

/// Real, unreaped child and its launcher's held pidfd, fixed boot/start and
/// non-renewing lifetime. Dropping it terminates/reaps ONLY this owned child.
/// This guard supplies process custody; it issues no authority or kernel role.
pub struct RootRoleChild {
    pid: libc::pid_t,
    pidfd: OwnedFd,
    peer: CognitiveCheckpointPeerLifetime,
    owner: HostAuthorityOwnerLifetime,
    end: u64,
    status: Option<ExitStatus>,
}

impl RootRoleChild {
    pub fn peer(&self) -> &CognitiveCheckpointPeerLifetime { &self.peer }

    pub fn check_alive(&self) -> io::Result<()> {
        remaining(self.end)?;
        self.owner.check_alive().map_err(io::Error::other)?;
        crate::root_notes_launch_channel::validate_process(&self.peer)?;
        verify_credentials(self.pid, self.peer.uid)?;
        self.owner.check_alive().map_err(io::Error::other)?;
        remaining(self.end).map(|_| ())
    }

    /// Clone only the already held actual pidfd. No claimed PID is opened.
    pub fn try_clone_pidfd(&self) -> io::Result<OwnedFd> {
        self.check_alive()?;
        self.pidfd.try_clone()
    }

    pub fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
        if let Some(status) = self.status { return Ok(Some(status)); }
        let mut raw = 0;
        // SAFETY: this PID remains our own unreaped child until waitpid succeeds.
        let result = unsafe { libc::waitpid(self.pid, &mut raw, libc::WNOHANG) };
        if result < 0 { return Err(io::Error::last_os_error()); }
        if result == self.pid { self.status = Some(ExitStatus::from_raw(raw)); }
        Ok(self.status)
    }

    /// The supplied bound can only shorten the original launch lifetime.
    /// Deadline failure terminates and reaps our child before returning.
    pub fn wait_until(&mut self, end_boottime_ns: u64) -> io::Result<ExitStatus> {
        loop {
            if let Some(status) = self.try_wait()? { return Ok(status); }
            let wait = remaining(self.end.min(end_boottime_ns));
            let nanos = match wait {
                Ok(nanos) => nanos,
                Err(error) => { self.terminate_and_reap()?; return Err(error); }
            };
            let mut poll = libc::pollfd { fd:self.pidfd.as_raw_fd(), events:libc::POLLIN, revents:0 };
            // SAFETY: poll points to one live initialized descriptor record.
            if unsafe { libc::poll(&mut poll, 1, nanos.div_ceil(1_000_000).min(10) as i32) } < 0
                && io::Error::last_os_error().kind() != io::ErrorKind::Interrupted
            { return Err(io::Error::last_os_error()); }
        }
    }

    pub fn terminate_and_reap(&mut self) -> io::Result<ExitStatus> {
        if let Some(status) = self.try_wait()? { return Ok(status); }
        terminate(self.pid)?;
        let mut status = 0;
        loop {
            // SAFETY: no other API reaps or adopts this exclusively owned child.
            if unsafe { libc::waitpid(self.pid, &mut status, 0) } == self.pid { break; }
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::Interrupted { return Err(error); }
        }
        let status = ExitStatus::from_raw(status);
        self.status = Some(status);
        Ok(status)
    }

    pub(super) fn from_executed(pid: libc::pid_t, pidfd: OwnedFd, uid: u32, end: u64) -> io::Result<Self> {
        // The PID and held pidfd come only from our successful fork, before any
        // wait/reap. No external PID can enter this private constructor.
        let result = (|| {
            let lifetime = Duration::from_nanos(remaining(end)?);
            if lifetime > Duration::from_secs(300) { return Err(io::Error::other("role lifetime exceeds 300s")); }
            let owner = HostAuthorityOwnerLifetime::from_pidfd(pidfd.try_clone()?, pid as u32, lifetime)
                .map_err(io::Error::other)?;
            let peer = capture(pid, uid)?;
            verify_credentials(pid, uid)?;
            owner.check_alive().map_err(io::Error::other)?;
            remaining(end)?;
            Ok(Self { pid, pidfd, peer, owner, end, status:None })
        })();
        if result.is_err() { reap_failed_fork(pid); }
        result
    }
}

impl Drop for RootRoleChild {
    fn drop(&mut self) { let _ = self.terminate_and_reap(); }
}

pub(super) fn reap_failed_fork(pid: libc::pid_t) {
    let _ = terminate(pid);
    loop {
        // SAFETY: only the new child of our immediately preceding fork is used.
        if unsafe { libc::waitpid(pid, std::ptr::null_mut(), 0) } >= 0 { break; }
        if io::Error::last_os_error().kind() != io::ErrorKind::Interrupted { break; }
    }
}

fn terminate(pid: libc::pid_t) -> io::Result<()> {
    // The child has not been reaped. This PID cannot refer to another process.
    if unsafe { libc::kill(pid, libc::SIGKILL) } < 0 {
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(libc::ESRCH) { return Err(error); }
    }
    Ok(())
}

pub(super) fn now() -> io::Result<u64> {
    crate::root_observation_cache::boottime_ns().map_err(io::Error::other)
}
pub(super) fn remaining(end: u64) -> io::Result<u64> {
    end.checked_sub(now()?).filter(|n| *n > 0)
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "Root role launch deadline"))
}
pub(super) fn bounded(path: impl AsRef<std::path::Path>) -> io::Result<String> {
    let mut text = String::new();
    std::fs::File::open(path)?.take(16 * 1024 + 1).read_to_string(&mut text)?;
    if text.len() > 16 * 1024 { return Err(io::Error::other("bounded role process metadata")); }
    Ok(text)
}
pub(super) fn capture(pid: libc::pid_t, uid: u32) -> io::Result<CognitiveCheckpointPeerLifetime> {
    let stat = bounded(format!("/proc/{pid}/stat"))?;
    let start = stat.rsplit_once(") ").and_then(|(_, rest)| rest.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok()).filter(|n| *n > 0)
        .ok_or_else(|| io::Error::other("actual role start ticks required"))?;
    let peer = CognitiveCheckpointPeerLifetime { uid, pid:pid as u32,
        boot_id:bounded("/proc/sys/kernel/random/boot_id")?.trim().into(), process_start_ticks:start };
    crate::root_notes_launch_channel::validate_process(&peer)?;
    Ok(peer)
}
pub(super) fn verify_credentials(pid: libc::pid_t, uid: u32) -> io::Result<()> {
    let text = bounded(format!("/proc/{pid}/status"))?;
    for field in ["Uid:", "Gid:"] {
        let values = text.lines().filter_map(|line| line.strip_prefix(field)).collect::<Vec<_>>();
        if values.len() != 1 || values[0].split_whitespace().map(str::parse::<u32>)
            .collect::<Result<Vec<_>, _>>().map_err(io::Error::other)? != vec![uid;4]
        { return Err(io::Error::other("four actual fixed role UIDs/GIDs required")); }
    }
    for field in ["CapInh:","CapPrm:","CapEff:","CapBnd:","CapAmb:"] {
        let values = text.lines().filter_map(|line| line.strip_prefix(field)).collect::<Vec<_>>();
        if values.len() != 1 || values[0].trim() != "0000000000000000" {
            return Err(io::Error::other("all role capabilities must be zero"));
        }
    }
    if !text.lines().any(|line| line == "NoNewPrivs:\t1")
        || !text.lines().any(|line| line.strip_prefix("Groups:").is_some_and(|v| v.trim().is_empty()))
    { return Err(io::Error::other("role requires NNP and empty supplementary groups")); }
    Ok(())
}
