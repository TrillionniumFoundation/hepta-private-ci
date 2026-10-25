//! Strict discovery boundaries for the original process-bound HOS2 device.
//! These pages select existing kernel slots; they never install authority.

use super::read16;
use super::read64;
use codex_hepta_memory::HOS2_CPU_PERIOD_NS;

#[derive(Clone, Copy)]
pub(super) struct ProcessIdentity {
    pub(super) pid: u32,
    pub(super) parent_pid: libc::pid_t,
}

impl ProcessIdentity {
    pub(super) fn current() -> Self {
        Self {
            pid: std::process::id(),
            // SAFETY: getppid has no pointer arguments and returns the current
            // process's parent. It does not acquire or manufacture a kernel role.
            parent_pid: unsafe { libc::getppid() },
        }
    }
}

#[derive(Clone, Copy)]
pub(super) enum Attachment {
    QualificationV2,
    InitialOwnerV3(ProcessIdentity),
    SuccessorOwnerV4(ProcessIdentity),
}

impl Attachment {
    pub(super) fn validate(self, bootstrap: &[u8]) -> Result<(), String> {
        let (version, declared_bytes) = match self {
            Self::QualificationV2 => (2, 192),
            Self::InitialOwnerV3(_) => (3, 200),
            Self::SuccessorOwnerV4(_) => (4, 240),
        };
        if (!matches!(self, Self::QualificationV2) && bootstrap.len() > 4096)
            || bootstrap.len() < declared_bytes
            || &bootstrap[..8] != b"HOS2BOOT"
            || read64(bootstrap, /*offset*/ 8)? != version
            || read64(bootstrap, /*offset*/ 24)? != declared_bytes as u64
            || bootstrap[declared_bytes..].iter().any(|byte| *byte != 0)
            || read64(bootstrap, /*offset*/ 176)? != HOS2_CPU_PERIOD_NS
        {
            return Err("invalid sealed HOS2 bootstrap discovery page".to_string());
        }
        let process = match self {
            Self::QualificationV2 => return Ok(()),
            Self::InitialOwnerV3(process) | Self::SuccessorOwnerV4(process) => process,
        };
        if read64(bootstrap, /*offset*/ 192)? != 1
            || process.parent_pid != 1
            || read64(bootstrap, /*offset*/ 168)? != 50_000_000
            || read64(bootstrap, /*offset*/ 184)? != 300_000_000_000
        {
            return Err("G2 bootstrap differs from the bounded original Root profile".to_string());
        }
        let pids = [
            read64(bootstrap, /*offset*/ 144)?,
            read64(bootstrap, /*offset*/ 152)?,
            read64(bootstrap, /*offset*/ 160)?,
        ];
        if pids.iter().any(|pid| !(2..=i32::MAX as u64).contains(pid))
            || pids[0] == pids[1]
            || pids[0] == pids[2]
            || pids[1] == pids[2]
        {
            return Err("G2 role process identities are invalid or aliased".to_string());
        }
        let role = read64(bootstrap, /*offset*/ 16)?;
        let (pid, local_space, handles) = match role {
            1 => (
                pids[0],
                read16(bootstrap, /*offset*/ 112)?,
                [1, 1, 2, 1, 3, 1, 0, 0],
            ),
            3 => (
                pids[2],
                read16(bootstrap, /*offset*/ 128)?,
                [1, 1, 2, 1, 3, 1, 4, 1],
            ),
            // Root, workload and history-only images must not acquire a
            // management adapter merely because they can copy a boot page.
            _ => return Err("this G2 bootstrap role has no native management slot".to_string()),
        };
        if pid != u64::from(process.pid) {
            return Err("G2 bootstrap belongs to another actual process".to_string());
        }
        for (index, expected) in handles.into_iter().enumerate() {
            if read64(bootstrap, 32 + index * 8)? != expected {
                return Err("G2 bootstrap differs from its original capability slots".to_string());
            }
        }
        if let Self::SuccessorOwnerV4(_) = self
            && (read64(bootstrap, /*offset*/ 200)? != pid
                || read16(bootstrap, /*offset*/ 208)? != local_space
                || read64(bootstrap, /*offset*/ 224)? == 0
                || bootstrap[232..240].iter().any(|byte| *byte != 0))
        {
            return Err("G2 successor image identity or generation is invalid".to_string());
        }
        Ok(())
    }
}
