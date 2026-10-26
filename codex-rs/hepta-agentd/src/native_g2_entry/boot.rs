//! Read kernel discovery without treating copied bytes as an authority grant.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;

const AUX_HEPTA_BOOT: libc::c_ulong = 240;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Role {
    Root,
    Manager,
    Workload,
    Recovery,
}

pub(super) struct Boot {
    pub(super) page: [u8; 4096],
    pub(super) role: Role,
    pub(super) pids: [u32; 3],
}

impl Boot {
    pub(super) fn read() -> io::Result<Self> {
        // SAFETY: getauxval reads the current process's initial auxiliary vector.
        let address = unsafe { libc::getauxval(AUX_HEPTA_BOOT) } as usize;
        if address == 0
            || address % 4096 != 0
            || address.checked_add(4096).is_none_or(|end| end > (1 << 47))
        {
            return Err(invalid("native sealed bootstrap page is absent"));
        }
        let mut page = [0_u8; 4096];
        // SAFETY: AT_HEPTA_BOOT is the original loader's read-only, page-aligned
        // 4096-byte mapping in this trusted initial image. No external address is
        // accepted. Subsequent original HOS2 QueryAbi still authenticates slots.
        page.copy_from_slice(unsafe { std::slice::from_raw_parts(address as *const u8, 4096) });
        if &page[..8] != b"HOS2BOOT"
            || word(&page, 8) != 3
            || word(&page, 24) != 200
            || word(&page, 192) != 1
            || page[200..].iter().any(|byte| *byte != 0)
            || word(&page, 168) != 50_000_000
            || word(&page, 176) != 100_000_000
            || word(&page, 184) != 300_000_000_000
        {
            return Err(invalid(
                "native initial bootstrap differs from original G2 profile",
            ));
        }
        let role = match word(&page, 16) {
            4 => Role::Root,
            1 => Role::Manager,
            2 => Role::Workload,
            3 => Role::Recovery,
            _ => return Err(invalid("unknown initial G2 role")),
        };
        let mut pids = [0_u32; 3];
        for (index, pid) in pids.iter_mut().enumerate() {
            *pid = u32::try_from(word(&page, 144 + index * 8))
                .map_err(|_| invalid("role PID out of range"))?;
            if *pid < 2 || *pid > i32::MAX as u32 {
                return Err(invalid("role PID out of range"));
            }
        }
        if pids[0] == pids[1] || pids[0] == pids[2] || pids[1] == pids[2] {
            return Err(invalid("native role PIDs alias"));
        }
        let expected = match role {
            Role::Root => 1,
            Role::Manager => pids[0],
            Role::Workload => pids[1],
            Role::Recovery => pids[2],
        };
        // SAFETY: these functions read actual process identity only.
        if std::process::id() != expected
            || (role != Role::Root && unsafe { libc::getppid() } != 1)
            || (role == Role::Workload && unsafe { libc::geteuid() } != 60002)
            || (role != Role::Workload && unsafe { libc::geteuid() } != 0)
        {
            return Err(invalid("bootstrap does not belong to this actual process"));
        }
        Ok(Self { page, role, pids })
    }

    pub(super) fn open_control(&self) -> io::Result<File> {
        if self.role == Role::Workload {
            return Err(invalid("workload cannot open management control"));
        }
        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open("/dev/hepta-control")
    }

    pub(super) fn authenticate_root(&self, control: &File) -> io::Result<()> {
        if self.role != Role::Root || self.page[32..96].iter().any(|byte| *byte != 0) {
            return Err(invalid("Root has no native management/history slots"));
        }
        let mut query = [0_u8; 128];
        query[..8].copy_from_slice(b"HOS2LAUN");
        query[8..16].copy_from_slice(&1_u64.to_le_bytes());
        // SAFETY: the fixed original launcher ioctl synchronously reads and
        // writes this live 128-byte buffer. The kernel authenticates this exact
        // Root ProcessImageKey; copied bootstrap/UID/argv do not grant access.
        if unsafe {
            libc::ioctl(
                control.as_raw_fd(),
                0xc080_4803 as libc::c_ulong,
                query.as_mut_ptr(),
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }
        let word = |offset| {
            let mut value = [0_u8; 8];
            value.copy_from_slice(&query[offset..offset + 8]);
            u64::from_le_bytes(value)
        };
        if &query[..8] != b"HOS2LRES"
            || word(8) != 1
            || word(16) != 1
            || word(24) != 0
            || word(32) != 1
            || word(40) != u64::from(self.pids[1])
            || word(48) != u64::from(self.pids[0])
            || word(56) != u64::from(self.pids[2])
            || word(64) != 0
            || word(72) != 0
            || query[80..96] != self.page[112..128]
            || query[96..112] != self.page[128..144]
            || query[112..].iter().any(|byte| *byte != 0)
        {
            return Err(invalid(
                "actual initial Root launcher receipt differs from native discovery",
            ));
        }
        Ok(())
    }
}

fn word(page: &[u8; 4096], offset: usize) -> u64 {
    let mut value = [0_u8; 8];
    value.copy_from_slice(&page[offset..offset + 8]);
    u64::from_le_bytes(value)
}

fn invalid(message: &str) -> io::Error {
    io::Error::other(message)
}
