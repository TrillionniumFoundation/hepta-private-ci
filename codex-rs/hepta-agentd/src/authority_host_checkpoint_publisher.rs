//! Retained kernel process identity for a trusted same-boot publisher handoff.

use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;

use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

/// A pidfd captured while the exact recorded publisher is alive. This is not
/// deserializable. A PID supplied after its owner exited cannot create evidence
/// for that former owner. Root must retain this object across the handoff.
pub struct RetainedCheckpointPublisher {
    pub(super) lifetime: CognitiveCheckpointPeerLifetime,
    descriptor: OwnedFd,
}

/// Kernel-observed retirement after Root lost its old retained pidfd. This is
/// not deserializable and never accepts an exit claim from an ordinary peer.
/// The exact protected predecessor lifetime is checked again by adoption.
pub struct RetiredCheckpointPublisher {
    pub(super) lifetime: CognitiveCheckpointPeerLifetime,
    // When a PID exists, retain the actual kernel object used for observation.
    _descriptor: Option<OwnedFd>,
}

impl RetiredCheckpointPublisher {
    /// Same-boot only. ESRCH, an exited actual pidfd, or an independently
    /// observed different start-time proves that this former life has ended.
    /// UID changes, /proc read failures and unavailable pidfd support do not.
    /// The trusted launcher runs in the original publisher's pinned PID space.
    pub fn observe(lifetime: CognitiveCheckpointPeerLifetime) -> Result<Self, AuthorityTrustError> {
        // SAFETY: geteuid takes no pointers and has no side effects.
        if unsafe { libc::geteuid() } != 0
            || lifetime.uid == 0
            || lifetime.pid == 0
            || lifetime.pid > i32::MAX as u32
            || lifetime.process_start_ticks == 0
        {
            return Err(AuthorityTrustError::Invalid);
        }
        require_same_boot(&lifetime)?;
        // SAFETY: pidfd_open receives an in-range PID, zero flags, no pointers.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, lifetime.pid, 0) };
        if raw < 0 {
            return if std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH) {
                Ok(Self {
                    lifetime,
                    _descriptor: None,
                })
            } else {
                Err(AuthorityTrustError::Unavailable)
            };
        }
        // SAFETY: successful pidfd_open returned a fresh owned descriptor.
        let descriptor = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        if descriptor_exited(&descriptor)? {
            return Ok(Self {
                lifetime,
                _descriptor: Some(descriptor),
            });
        }
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", lifetime.pid));
        let info = std::fs::read_to_string(format!("/proc/self/fdinfo/{}", descriptor.as_raw_fd()));
        // The process may have exited during either read; an actual pidfd exit
        // remains sufficient. An unrelated read error is never an exit proof.
        if descriptor_exited(&descriptor)? {
            return Ok(Self {
                lifetime,
                _descriptor: Some(descriptor),
            });
        }
        let stat = stat.map_err(|_| AuthorityTrustError::Unavailable)?;
        let info = info.map_err(|_| AuthorityTrustError::Unavailable)?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value != 0)
            .ok_or(AuthorityTrustError::Unavailable)?;
        let fd_pid = info
            .lines()
            .find_map(|line| line.strip_prefix("Pid:"))
            .and_then(|value| value.trim().parse::<u32>().ok());
        if fd_pid != Some(lifetime.pid) {
            return Err(AuthorityTrustError::Unavailable);
        }
        if start == lifetime.process_start_ticks {
            return Err(AuthorityTrustError::Conflict);
        }
        Ok(Self {
            lifetime,
            _descriptor: Some(descriptor),
        })
    }

    pub(super) fn require_retired(&self) -> Result<(), AuthorityTrustError> {
        // The observed termination of a former process lifetime is monotonic.
        // A later process at that PID cannot revive the old kernel lifetime.
        require_same_boot(&self.lifetime)
    }
}

fn require_same_boot(
    lifetime: &CognitiveCheckpointPeerLifetime,
) -> Result<(), AuthorityTrustError> {
    let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
        .map_err(|_| AuthorityTrustError::Unavailable)?;
    if boot.trim() == lifetime.boot_id {
        Ok(())
    } else {
        Err(AuthorityTrustError::Invalid)
    }
}

impl RetainedCheckpointPublisher {
    /// Read-only original process identity; this grants no lifetime or exit proof.
    pub(crate) fn lifetime(&self) -> &CognitiveCheckpointPeerLifetime {
        &self.lifetime
    }

    /// Capture before the old publisher exits or the new publisher is released.
    /// The caller still enforces the dedicated UID/capability launch policy.
    pub fn capture(lifetime: CognitiveCheckpointPeerLifetime) -> Result<Self, AuthorityTrustError> {
        // SAFETY: geteuid has no pointers and does not modify process state.
        if unsafe { libc::geteuid() } != 0
            || lifetime.uid == 0
            || lifetime.pid == 0
            || lifetime.pid > i32::MAX as u32
            || lifetime.process_start_ticks == 0
        {
            return Err(AuthorityTrustError::Invalid);
        }
        // SAFETY: pidfd_open receives an in-range PID, zero flags and no pointers.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, lifetime.pid, 0) };
        if raw < 0 {
            return Err(AuthorityTrustError::Unavailable);
        }
        // SAFETY: a successful pidfd_open returned a fresh owned descriptor.
        let descriptor = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        let retained = Self {
            lifetime,
            descriptor,
        };
        retained.require_alive()?;
        let boot = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", retained.lifetime.pid))
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let start = stat
            .rsplit_once(") ")
            .and_then(|(_, fields)| fields.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok());
        let status = std::fs::read_to_string(format!("/proc/{}/status", retained.lifetime.pid))
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let expected_uid = retained.lifetime.uid.to_string();
        let uid_matches = status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:"))
            .is_some_and(|values| {
                let mut values = values.split_whitespace();
                (0..4).all(|_| values.next() == Some(expected_uid.as_str()))
                    && values.next().is_none()
            });
        let info = std::fs::read_to_string(format!(
            "/proc/self/fdinfo/{}",
            retained.descriptor.as_raw_fd()
        ))
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        let fd_pid = info
            .lines()
            .find_map(|line| line.strip_prefix("Pid:"))
            .and_then(|value| value.trim().parse::<u32>().ok());
        if boot.trim() != retained.lifetime.boot_id
            || start != Some(retained.lifetime.process_start_ticks)
            || !uid_matches
            || fd_pid != Some(retained.lifetime.pid)
        {
            return Err(AuthorityTrustError::Invalid);
        }
        retained.require_alive()?;
        Ok(retained)
    }

    pub(super) fn require_alive(&self) -> Result<(), AuthorityTrustError> {
        if self.exited()? {
            Err(AuthorityTrustError::Conflict)
        } else {
            Ok(())
        }
    }

    pub(super) fn require_exited(&self) -> Result<(), AuthorityTrustError> {
        if self.exited()? {
            Ok(())
        } else {
            Err(AuthorityTrustError::Conflict)
        }
    }

    fn exited(&self) -> Result<bool, AuthorityTrustError> {
        descriptor_exited(&self.descriptor)
    }
}

fn descriptor_exited(descriptor: &OwnedFd) -> Result<bool, AuthorityTrustError> {
    let mut poll = libc::pollfd {
        fd: descriptor.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: one valid initialized pollfd is borrowed for a nonblocking call.
    let count = unsafe { libc::poll(&mut poll, 1, 0) };
    if count < 0 || poll.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
        return Err(AuthorityTrustError::Unavailable);
    }
    if count == 0 {
        return Ok(false);
    }
    if poll.revents & libc::POLLIN != 0 {
        return Ok(true);
    }
    Err(AuthorityTrustError::Unavailable)
}
