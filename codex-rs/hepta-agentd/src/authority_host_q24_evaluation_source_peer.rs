//! The configured source process is additional custody separation. Independent
//! authority still requires the Root-fixed Generator and Observer signatures.

use std::io;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

pub(super) struct OriginalBSourcePeer {
    pub(super) lifetime: CognitiveCheckpointPeerLifetime,
    descriptor: OwnedFd,
}

impl OriginalBSourcePeer {
    pub(super) fn capture(
        lifetime: &CognitiveCheckpointPeerLifetime,
        learner_uid: u32,
        learner_pid: u32,
    ) -> io::Result<Self> {
        crate::authority_host_service::generation_initial::original_root()?;
        if lifetime.uid == 0
            || lifetime.uid == learner_uid
            || lifetime.pid == learner_pid
            || lifetime.pid == 0
            || lifetime.pid > i32::MAX as u32
            || lifetime.process_start_ticks == 0
        {
            return Err(io::Error::other(
                "original independent B source peer required",
            ));
        }
        // SAFETY: an in-range original PID and zero flags; no borrowed memory.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, lifetime.pid, 0) };
        if raw < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: successful pidfd_open transfers one fresh descriptor.
        let descriptor = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        let held = Self {
            lifetime: lifetime.clone(),
            descriptor,
        };
        held.require_live()?;
        Ok(held)
    }

    pub(super) fn require_live(&self) -> io::Result<()> {
        crate::root_observation_stream::check_lifetime(&self.descriptor)
            .map_err(io::Error::other)?;
        let life = &self.lifetime;
        let boot = bounded_text("/proc/sys/kernel/random/boot_id", 128)?;
        let stat = bounded_text(&format!("/proc/{}/stat", life.pid), 8192)?;
        let status = bounded_text(&format!("/proc/{}/status", life.pid), 16_384)?;
        let info = bounded_text(
            &format!("/proc/self/fdinfo/{}", self.descriptor.as_raw_fd()),
            4096,
        )?;
        let expected = life.uid.to_string();
        if boot.trim() != life.boot_id
            || stat
                .rsplit_once(") ")
                .and_then(|(_, fields)| fields.split_whitespace().nth(19))
                .and_then(|value| value.parse::<u64>().ok())
                != Some(life.process_start_ticks)
            || info
                .lines()
                .find_map(|line| line.strip_prefix("Pid:")?.trim().parse::<u32>().ok())
                != Some(life.pid)
            || !status
                .lines()
                .find_map(|line| line.strip_prefix("Uid:"))
                .is_some_and(|values| {
                    let mut values = values.split_whitespace();
                    (0..4).all(|_| values.next() == Some(expected.as_str()))
                        && values.next().is_none()
                })
        {
            return Err(io::Error::other("original B source incarnation changed"));
        }
        crate::root_observation_stream::check_lifetime(&self.descriptor).map_err(io::Error::other)
    }

    pub(super) fn original_descriptor(&self) -> io::Result<OwnedFd> {
        self.require_live()?;
        self.descriptor.try_clone()
    }
}

fn bounded_text(path: &str, maximum: u64) -> io::Result<String> {
    let mut text = String::new();
    std::fs::File::open(path)?
        .take(maximum + 1)
        .read_to_string(&mut text)?;
    if text.len() as u64 > maximum {
        return Err(io::Error::other("original B peer metadata oversized"));
    }
    Ok(text)
}
