//! Transport for the original kernel Root's bounded frozen-image factory.
//! The kernel authenticates the actual Process and image on every call. This
//! module cannot grant a role to a fork, exec, PID, path or caller-selected ELF.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;

const IOCTL: libc::c_ulong = 0xc080_4803;
const BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KernelLaunchMode {
    ManagerRecovery,
    HistoryOnly,
}

/// Actual immutable response retained by the original kernel transaction.
/// Private fields prevent callers from substituting arbitrary process IDs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KernelLaunchReceipt {
    boot_id: [u8; 16],
    bytes: [u8; BYTES],
    mode: KernelLaunchMode,
}

impl KernelLaunchReceipt {
    pub fn boot_id(&self) -> [u8; 16] {
        self.boot_id
    }
    pub fn bytes(&self) -> &[u8; BYTES] {
        &self.bytes
    }
    pub fn generation(&self) -> u64 {
        word(&self.bytes, 24)
    }
    pub fn previous_generation(&self) -> u64 {
        word(&self.bytes, 72)
    }
    pub fn mode(&self) -> KernelLaunchMode {
        self.mode
    }
    pub fn root_pid(&self) -> u32 {
        word(&self.bytes, 32) as u32
    }
    pub fn workload_pid(&self) -> u32 {
        word(&self.bytes, 40) as u32
    }
    pub fn manager_pid(&self) -> Option<u32> {
        nonzero_pid(word(&self.bytes, 48))
    }
    pub fn recovery_pid(&self) -> Option<u32> {
        nonzero_pid(word(&self.bytes, 56))
    }
    pub fn history_pid(&self) -> Option<u32> {
        nonzero_pid(word(&self.bytes, 64))
    }
    pub fn history_spaces(&self) -> [[u8; 16]; 2] {
        [id(&self.bytes, 80), id(&self.bytes, 96)]
    }
}

/// The original CPU owner's terminal at the exact policy-replacement cut.
/// This observation is never an HOS2 D, a writer outcome or a Current token.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KernelPolicyRetirement {
    boot_id: [u8; 16],
    bytes: [u8; BYTES],
}

impl KernelPolicyRetirement {
    pub fn boot_id(&self) -> [u8; 16] {
        self.boot_id
    }
    pub fn bytes(&self) -> &[u8; BYTES] {
        &self.bytes
    }
    pub fn generation(&self) -> u64 {
        word(&self.bytes, 16)
    }
    pub fn policy_retired(&self) -> bool {
        word(&self.bytes, 120) & 1 != 0
    }
    pub fn watchdog_status(&self) -> u64 {
        word(&self.bytes, 24)
    }
    pub fn evaluated_ns(&self) -> Option<u64> {
        (word(&self.bytes, 120) & 2 != 0).then(|| word(&self.bytes, 32))
    }
    pub fn previous_history_spaces(&self) -> [[u8; 16]; 2] {
        [id(&self.bytes, 88), id(&self.bytes, 104)]
    }
}

pub struct RootKernelLauncher {
    file: File,
    boot_id: [u8; 16],
}

impl RootKernelLauncher {
    /// Open in the SAME original Root Process, after platform mounts. The
    /// sealed initial page and exact current Root credentials are mandatory.
    pub fn open(bootstrap: &[u8]) -> io::Result<Self> {
        super::validate_root(bootstrap).map_err(|error| invalid(error.to_string()))?;
        // A caller-provided slice must not become the durable boot identity.
        // SAFETY: this path has already required the actual initial Root PID
        // and credentials. AT_HEPTA_BOOT is the kernel's immutable full page;
        // an ordinary Linux process has no such auxiliary-vector entry.
        let address = unsafe { libc::getauxval(240) };
        if address == 0 || address % 4096 != 0 {
            return Err(invalid("native Root has no actual sealed bootstrap page"));
        }
        let actual = unsafe { std::slice::from_raw_parts(address as *const u8, 4096) };
        if actual[..200] != bootstrap[..200] || actual[200..].iter().any(|byte| *byte != 0) {
            return Err(invalid(
                "Root discovery differs from its actual kernel bootstrap",
            ));
        }
        let boot_id: [u8; 16] = bootstrap[96..112].try_into().unwrap();
        if boot_id == [0; 16] {
            return Err(invalid("native Root boot identity is zero"));
        }
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open("/dev/hepta-control")?;
        let launcher = Self { file, boot_id };
        let _ = launcher.query()?;
        Ok(launcher)
    }

    pub fn boot_id(&self) -> [u8; 16] {
        self.boot_id
    }

    pub fn query(&self) -> io::Result<KernelLaunchReceipt> {
        parse_launch(self.boot_id, self.exchange(0, 0)?)
    }

    /// No retry is hidden here. If copyout is lost, querying/replaying the
    /// same expected generation uses the kernel's original immutable receipt.
    /// A live or unreaped previous child, or an unacknowledged retirement,
    /// returns the kernel's actual EBUSY before publication.
    pub fn advance(&self, previous: &KernelLaunchReceipt) -> io::Result<KernelLaunchReceipt> {
        self.check_boot(previous.boot_id)?;
        let next = previous
            .generation()
            .checked_add(1)
            .ok_or_else(|| invalid("launch generation overflow"))?;
        let receipt = parse_launch(self.boot_id, self.exchange(1, previous.generation())?)?;
        if receipt.generation() != next || receipt.previous_generation() != previous.generation() {
            return Err(invalid(
                "kernel launch response differs from exact predecessor",
            ));
        }
        Ok(receipt)
    }

    pub fn read_retirement(
        &self,
        launch: &KernelLaunchReceipt,
    ) -> io::Result<KernelPolicyRetirement> {
        self.check_boot(launch.boot_id)?;
        if launch.generation() == 0 {
            return Err(invalid("initial launch has no retired policy"));
        }
        parse_retirement(launch, self.exchange(2, launch.generation())?)
    }

    /// The trusted Root composition must first save the full boot identity,
    /// launch and retirement bytes through its original protected durable
    /// administration path, including file and directory fsync. This transport
    /// does not replace that persistence boundary or issue a Current witness.
    pub fn acknowledge_saved(
        &self,
        launch: &KernelLaunchReceipt,
        retirement: &KernelPolicyRetirement,
    ) -> io::Result<()> {
        self.check_boot(launch.boot_id)?;
        self.check_boot(retirement.boot_id)?;
        if launch.generation() == 0 || retirement.generation() != launch.generation() {
            return Err(invalid("retirement acknowledgement generation differs"));
        }
        let acknowledged = parse_launch(self.boot_id, self.exchange(3, launch.generation())?)?;
        if &acknowledged != launch {
            return Err(invalid("retirement acknowledgement changed launch receipt"));
        }
        Ok(())
    }

    fn check_boot(&self, boot_id: [u8; 16]) -> io::Result<()> {
        if self.boot_id != boot_id {
            return Err(invalid("native launch belongs to a different boot"));
        }
        Ok(())
    }

    fn exchange(&self, command: u64, expected: u64) -> io::Result<[u8; BYTES]> {
        let mut bytes = [0; BYTES];
        bytes[..8].copy_from_slice(b"HOS2LAUN");
        for (offset, value) in [(8, 1_u64), (16, command), (24, expected)] {
            bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
        }
        // SAFETY: this initialized in/out buffer is exactly the kernel ABI's
        // 128 bytes and is borrowed only for the one synchronous ioctl. Kernel
        // input is snapshotted before publication and no Rust pointer escapes.
        let result = unsafe { libc::ioctl(self.file.as_raw_fd(), IOCTL, bytes.as_mut_ptr()) };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(bytes)
    }
}

fn parse_launch(boot_id: [u8; 16], bytes: [u8; BYTES]) -> io::Result<KernelLaunchReceipt> {
    if boot_id == [0; 16]
        || &bytes[..8] != b"HOS2LRES"
        || word(&bytes, 8) != 1
        || word(&bytes, 32) != 1
        || word(&bytes, 40) != 3
        || bytes[112..].iter().any(|byte| *byte != 0)
        || id(&bytes, 80) == [0; 16]
        || id(&bytes, 96) == [0; 16]
        || id(&bytes, 80) == id(&bytes, 96)
    {
        return Err(invalid("invalid native launch receipt"));
    }
    let generation = word(&bytes, 24);
    let previous = word(&bytes, 72);
    if (generation == 0 && previous != 0)
        || (generation != 0 && previous.checked_add(1) != Some(generation))
    {
        return Err(invalid(
            "native launch receipt generation is not contiguous",
        ));
    }
    let (manager, recovery, history) = (word(&bytes, 48), word(&bytes, 56), word(&bytes, 64));
    let valid_pid = |pid| (5..=i32::MAX as u64).contains(&pid);
    let mode = match word(&bytes, 16) {
        1 if history == 0
            && ((generation == 0 && manager == 2 && recovery == 4)
                || (generation > 0
                    && valid_pid(manager)
                    && valid_pid(recovery)
                    && manager != recovery)) =>
        {
            KernelLaunchMode::ManagerRecovery
        }
        2 if generation > 0 && manager == 0 && recovery == 0 && valid_pid(history) => {
            KernelLaunchMode::HistoryOnly
        }
        _ => return Err(invalid("native launch receipt process topology differs")),
    };
    Ok(KernelLaunchReceipt {
        boot_id,
        bytes,
        mode,
    })
}

fn parse_retirement(
    launch: &KernelLaunchReceipt,
    bytes: [u8; BYTES],
) -> io::Result<KernelPolicyRetirement> {
    let flags = word(&bytes, 120);
    let status = word(&bytes, 24);
    let evaluated = word(&bytes, 32);
    let spaces = [id(&bytes, 88), id(&bytes, 104)];
    let policy_retired = flags & 1 != 0;
    if &bytes[..8] != b"HOS2LWDR"
        || word(&bytes, 8) != 1
        || word(&bytes, 16) == 0
        || word(&bytes, 16) != launch.generation()
        || flags & !3 != 0
        || status > 7
        || policy_retired != (launch.mode == KernelLaunchMode::ManagerRecovery)
        || (flags & 2 == 0 && evaluated != 0)
        || (status == 0 && (flags & 2 != 0 || evaluated != 0))
        || (!policy_retired && (flags != 0 || status != 0))
        || spaces[0] == [0; 16]
        || spaces[1] == [0; 16]
        || spaces[0] == spaces[1]
        || (!policy_retired && spaces != launch.history_spaces())
        || (policy_retired
            && spaces
                .iter()
                .any(|space| launch.history_spaces().contains(space)))
    {
        return Err(invalid("invalid native policy-retirement binding"));
    }
    if status == 1 {
        if id(&bytes, 40) == [0; 16]
            || word(&bytes, 56) == 0
            || word(&bytes, 56).checked_add(1) != Some(word(&bytes, 64))
            || flags & 2 == 0
            || word(&bytes, 72) > evaluated
            || word(&bytes, 80) > word(&bytes, 72) % 100_000_000
        {
            return Err(invalid("invalid original watchdog Restored receipt"));
        }
    } else if bytes[40..88].iter().any(|byte| *byte != 0) {
        return Err(invalid(
            "non-Restored watchdog contains resource receipt fields",
        ));
    }
    Ok(KernelPolicyRetirement {
        boot_id: launch.boot_id,
        bytes,
    })
}

fn word(bytes: &[u8; BYTES], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap())
}
fn id(bytes: &[u8; BYTES], offset: usize) -> [u8; 16] {
    bytes[offset..offset + 16].try_into().unwrap()
}
fn nonzero_pid(value: u64) -> Option<u32> {
    (value != 0).then_some(value as u32)
}
fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

#[cfg(test)]
#[path = "kernel_launcher_tests.rs"]
mod tests;
