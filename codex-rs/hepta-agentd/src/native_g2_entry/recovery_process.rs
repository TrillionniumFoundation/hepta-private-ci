//! Actual old-child exit and original watchdog observations, without fake status.
use super::evidence;
use super::supervisor;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

pub(super) fn wait_signal_nine(pin: &OwnedFd, pid: u32) -> io::Result<i16> {
    let mut poll = libc::pollfd {
        fd: pin.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: this is the actual held Manager pidfd, never a numeric fallback.
    if unsafe { libc::poll(&mut poll, 1, 2000) } != 1 || poll.revents != libc::POLLIN {
        return Err(io::Error::other(
            "actual Manager pidfd exit was not observed",
        ));
    }
    // SAFETY: waitid initializes the standard SIGCHLD record. WNOWAIT leaves
    // the original Supervisor driver as the sole process reaper.
    let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
    if unsafe {
        libc::waitid(
            libc::P_PIDFD,
            pin.as_raw_fd() as libc::id_t,
            &mut info,
            libc::WEXITED | libc::WNOWAIT | libc::WNOHANG,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    if unsafe { info.si_pid() } != pid as i32
        || info.si_code != libc::CLD_KILLED
        || unsafe { info.si_status() } != 9
    {
        return Err(io::Error::other(
            "Manager did not actually exit through signal nine",
        ));
    }
    Ok(poll.revents)
}

pub(super) fn cpu_stat_path(workload: u32) -> io::Result<PathBuf> {
    let mut selected = None;
    let entries = std::fs::read_dir("/hepta-cgroup")?.collect::<Result<Vec<_>, _>>()?;
    if entries.len() > 64 {
        return Err(io::Error::other("unexpected native cgroup geometry"));
    }
    for entry in entries {
        let name = entry.file_name();
        if !name.as_encoded_bytes().starts_with(b"hepta-g1d-") {
            continue;
        }
        let procs = entry.path().join("cgroup.procs");
        let text = evidence::bounded_text(
            procs
                .to_str()
                .ok_or_else(|| io::Error::other("native cgroup path"))?,
            1024,
        )?;
        let pids = text
            .split_whitespace()
            .map(str::parse::<u32>)
            .collect::<Result<Vec<_>, _>>()
            .map_err(io::Error::other)?;
        if pids == [workload] {
            if selected.replace(entry.path().join("cpu.stat")).is_some() {
                return Err(io::Error::other(
                    "actual workload appears in multiple CPU owners",
                ));
            }
        }
    }
    selected.ok_or_else(|| io::Error::other("actual workload CPU membership absent"))
}

pub(super) fn watchdog(workload: u32) -> io::Result<(String, String)> {
    let path = cpu_stat_path(workload)?;
    let path = path
        .to_str()
        .ok_or_else(|| io::Error::other("native cpu.stat path"))?;
    let end = Instant::now() + Duration::from_secs(7);
    loop {
        let first = evidence::bounded_text(path, 32768)?;
        if first.lines().any(|line| line == "hepta_watchdog_status 1") {
            std::thread::sleep(Duration::from_millis(100));
            let second = evidence::bounded_text(path, 32768)?;
            return Ok((first, second));
        }
        if Instant::now() >= end {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "original five-second watchdog did not report restoration",
            ));
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

pub(super) fn wait_expired(expires_ms: u64) -> Result<u64, Box<dyn std::error::Error>> {
    let end = Instant::now() + Duration::from_secs(25);
    loop {
        let now = super::provision::now_ms()?;
        if now >= expires_ms {
            return Ok(now);
        }
        if Instant::now() >= end {
            return Err(
                "actual original writer lease did not expire in the finite native window".into(),
            );
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

pub(super) fn start_successor(
    supervisor: &mut supervisor::NativeSupervisor,
    agent: &codex_hepta_contracts::AgentId,
) -> Result<(), Box<dyn std::error::Error>> {
    let report = supervisor.tick(Instant::now());
    if !report.faults.is_empty()
        || supervisor
            .snapshot(agent)
            .is_none_or(|snapshot| snapshot.active)
    {
        return Err("original Supervisor did not retire its actual exited Manager".into());
    }
    supervisor.start(agent, supervisor::actual_command()?, Instant::now())?;
    Ok(())
}
