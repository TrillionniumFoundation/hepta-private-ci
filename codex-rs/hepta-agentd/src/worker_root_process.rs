//! Kernel observations for the dedicated Worker registration handoff.
//! Numeric identities never substitute for the retained actual Child pidfd.

use super::WorkerProcessIdentityV1;
use super::refused;
use std::fs::File;
use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::path::Path;
use std::process::Child;
use std::time::Instant;

pub(crate) struct PinnedWorkerChild {
    pub(crate) identity: WorkerProcessIdentityV1,
    pub(crate) pidfd: OwnedFd,
}

impl PinnedWorkerChild {
    pub(crate) fn capture(child: &mut Child, end: Instant) -> io::Result<Self> {
        // Child remains borrowed and unreaped until its actual lifetime is
        // pinned. Neither an environment variable nor peer JSON supplies PID.
        if child.try_wait()?.is_some() {
            return Err(refused("Worker child already exited"));
        }
        let pidfd = pin(child.id())?;
        crate::authority_host_runtime::owner_alive(&pidfd, end)?;
        let identity = observe(child.id())?;
        let result = Self { identity, pidfd };
        result.verify(end)?;
        Ok(result)
    }

    pub(crate) fn verify(&self, end: Instant) -> io::Result<()> {
        if matches!(self.identity.uid, 0 | u32::MAX) || matches!(self.identity.gid, 0 | u32::MAX) {
            return Err(refused("dedicated non-Root Worker UID/GID required"));
        }
        verify(&self.identity, &self.pidfd, end)?;
        crate::authority_host_runtime::verify_process_credentials(
            self.identity.pid,
            self.identity.uid,
            self.identity.gid,
        )?;
        verify(&self.identity, &self.pidfd, end)
    }
}

pub(crate) fn pin(pid: u32) -> io::Result<OwnedFd> {
    if pid == 0 || pid > i32::MAX as u32 {
        return Err(refused("invalid kernel process identity"));
    }
    // SAFETY: pidfd_open takes a scalar PID and zero flags. Root calls this
    // with its own PID or a retained actual Child; the consumer pins itself.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: a successful pidfd_open returns exactly one fresh owned FD.
    Ok(unsafe { OwnedFd::from_raw_fd(raw as i32) })
}

pub(crate) fn observe(pid: u32) -> io::Result<WorkerProcessIdentityV1> {
    if pid == 0 || pid > i32::MAX as u32 {
        return Err(refused("invalid kernel process identity"));
    }
    let status = bounded_proc(&format!("/proc/{pid}/status"), 64 * 1024)?;
    let credential = |prefix: &str| -> io::Result<u32> {
        let fields = status
            .lines()
            .find_map(|line| line.strip_prefix(prefix))
            .ok_or_else(|| refused("kernel credential field missing"))?
            .split_whitespace()
            .map(str::parse::<u32>)
            .collect::<Result<Vec<_>, _>>()
            .map_err(io::Error::other)?;
        if fields.len() != 4 || fields.iter().any(|value| *value != fields[0]) {
            return Err(refused("all four kernel UID/GID values must agree"));
        }
        Ok(fields[0])
    };
    let stat = bounded_proc(&format!("/proc/{pid}/stat"), 16 * 1024)?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| refused("kernel process start identity missing"))?;
    let boot_id = bounded_proc("/proc/sys/kernel/random/boot_id", 128)?
        .trim()
        .to_owned();
    if boot_id.is_empty() || boot_id.len() > 64 {
        return Err(refused("kernel boot identity missing"));
    }
    Ok(WorkerProcessIdentityV1 {
        uid: credential("Uid:")?,
        gid: credential("Gid:")?,
        pid,
        boot_id,
        process_start_ticks: start,
    })
}

pub(crate) fn verify(
    expected: &WorkerProcessIdentityV1,
    pidfd: &OwnedFd,
    end: Instant,
) -> io::Result<()> {
    let number = pidfd.as_raw_fd();
    if std::fs::read_link(format!("/proc/self/fd/{number}"))? != Path::new("anon_inode:[pidfd]") {
        return Err(refused("actual process pidfd required"));
    }
    let info = bounded_proc(&format!("/proc/self/fdinfo/{number}"), 4096)?;
    let pinned = info.lines().find_map(|line| {
        line.strip_prefix("Pid:")
            .and_then(|value| value.trim().parse::<u32>().ok())
    });
    if pinned != Some(expected.pid) {
        return Err(refused("pidfd does not pin the registered process"));
    }
    crate::authority_host_runtime::owner_alive(pidfd, end)?;
    if observe(expected.pid)? != *expected {
        return Err(refused("kernel process lifetime or credentials changed"));
    }
    crate::authority_host_runtime::owner_alive(pidfd, end)
}

fn bounded_proc(path: &str, bound: usize) -> io::Result<String> {
    let mut bytes = String::new();
    File::open(path)?
        .take(bound as u64 + 1)
        .read_to_string(&mut bytes)?;
    if bytes.len() > bound {
        return Err(refused("kernel observation exceeds its fixed bound"));
    }
    Ok(bytes)
}
