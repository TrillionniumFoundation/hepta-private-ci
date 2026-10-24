//! The finite G2 trusted installation over the original Root and Agentd owners.
//! Bootstrap bytes discover a role; actual Process/image capability checks,
//! original Registry generations and Root proofs remain independent gates.

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::fs::File;
use std::io;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

#[path = "native_cpu_commands.rs"]
mod commands;
#[path = "native_cpu_evidence.rs"]
mod evidence;
#[path = "native_cpu_host.rs"]
mod host;
#[path = "native_cpu_platform.rs"]
mod platform;
#[path = "native_cpu_root.rs"]
mod root;

const RUNTIME: &str = "/run/hepta-native";
const STATE: &str = "/state/hepta-native";
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";
const LIFETIME: Duration = Duration::from_secs(120);
const IO_TIMEOUT: Duration = Duration::from_secs(5);

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::other(message.into())
}
fn error(value: impl std::fmt::Display) -> io::Error {
    invalid(value.to_string())
}

#[derive(Clone)]
struct NativeBootstrap {
    bytes: [u8; 4096],
    role: u64,
}
impl NativeBootstrap {
    fn read() -> io::Result<Self> {
        // SAFETY: AT_HEPTA_BOOT is emitted by the reviewed kernel initial ELF
        // loader and denotes its one readable, immutable, full bootstrap page.
        // Ordinary processes have no such entry and are refused before use.
        let address = unsafe { libc::getauxval(240) };
        if address == 0 || address % 4096 != 0 {
            return Err(invalid("missing native bootstrap page"));
        }
        let mut bytes = [0; 4096];
        unsafe {
            std::ptr::copy_nonoverlapping(address as *const u8, bytes.as_mut_ptr(), bytes.len())
        };
        let word = |offset| u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap());
        let role = word(16);
        let pid = match role {
            4 => 1,
            1 => 2,
            2 => 3,
            3 => 4,
            _ => 0,
        };
        if &bytes[..8] != b"HOS2BOOT"
            || word(8) != 3
            || word(24) != 200
            || word(144) != 2
            || word(152) != 3
            || word(160) != 4
            || word(192) != 1
            || word(168) != 50_000_000
            || word(176) != 100_000_000
            || word(184) != 300_000_000_000
            || pid == 0
            || std::process::id() != pid
            || bytes[200..].iter().any(|byte| *byte != 0)
            || bytes[96..112].iter().all(|byte| *byte == 0)
            || bytes[112..128] == bytes[128..144]
            || (role != 4 && unsafe { libc::getppid() } != 1)
        {
            return Err(invalid("actual four-role G2 bootstrap required"));
        }
        Ok(Self { bytes, role })
    }
    fn id(&self, offset: usize) -> [u8; 16] {
        self.bytes[offset..offset + 16].try_into().unwrap()
    }
}

/// Run the actual kernel-created role. This is a finite native CPU profile,
/// with explicit fresh Root installation and two pre-created owner slots.
/// Existing/partial authority state is refused; it is never reset on startup.
/// This entry does not claim cross-boot recovery or native-grant renewal.
pub fn run_native_cpu_daemon() -> io::Result<()> {
    let boot = NativeBootstrap::read()?;
    match boot.role {
        4 => root::run(boot),
        1 | 3 => {
            platform::wait_platform()?;
            let device = Arc::new(
                crate::AgentdHos2Device::from_kernel_bootstrap(&boot.bytes).map_err(error)?,
            );
            platform::drop_host_privileges()?;
            host::run(boot, device)
        }
        2 => {
            platform::wait_platform()?;
            platform::run_workload()
        }
        _ => Err(invalid("unsupported native role")),
    }
}

fn peer(pid: u32, uid: u32) -> io::Result<CognitiveCheckpointPeerLifetime> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    if stat.len() > 8192 {
        return Err(invalid("process stat exceeds bound"));
    }
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| invalid("actual process start unavailable"))?;
    let boot_id = std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?;
    if boot_id.trim().len() != 36 {
        return Err(invalid("actual boot identity unavailable"));
    }
    Ok(CognitiveCheckpointPeerLifetime {
        uid,
        pid,
        boot_id: boot_id.trim().into(),
        process_start_ticks: start,
    })
}

fn pidfd(pid: u32) -> io::Result<std::os::fd::OwnedFd> {
    use std::os::fd::FromRawFd;
    // SAFETY: pidfd_open takes only numeric values and returns a fresh FD.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { std::os::fd::OwnedFd::from_raw_fd(fd as i32) })
}

fn now() -> io::Result<u64> {
    codex_hepta_authority_client::boottime_ns().map_err(error)
}
fn end() -> io::Result<u64> {
    now()?
        .checked_add(LIFETIME.as_nanos() as u64)
        .ok_or_else(|| invalid("deadline overflow"))
}
fn remaining(deadline: u64) -> io::Result<Duration> {
    deadline
        .checked_sub(now()?)
        .filter(|value| *value > 0)
        .map(Duration::from_nanos)
        .ok_or_else(|| invalid("native owner deadline elapsed"))
}
fn connect(path: &Path, deadline: u64) -> io::Result<std::os::unix::net::UnixStream> {
    loop {
        remaining(deadline)?;
        match std::os::unix::net::UnixStream::connect(path) {
            Ok(stream) => return Ok(stream),
            Err(e)
                if matches!(
                    e.kind(),
                    io::ErrorKind::NotFound | io::ErrorKind::ConnectionRefused
                ) =>
            {
                std::thread::sleep(Duration::from_millis(5))
            }
            Err(e) => return Err(e),
        }
    }
}
fn runtime() -> io::Result<tokio::runtime::Runtime> {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
}
