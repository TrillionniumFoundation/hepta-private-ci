use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

pub type Result<T> = anyhow::Result<T>;
pub const ROOT: &str = "/var/lib/hepta-native";
pub const STATE: &str = "/var/lib/hepta-native/g2-owner";
pub const DATA: &str = "/mnt/hepta-store/agent-owner/g2-owner";
pub const LOCAL: &str = "/mnt/hepta-store/consumer-local/g2-owner";
pub const RUN: &str = "/run/hepta-native";
pub const OWNER: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

pub struct Boot {
    pub bytes: Vec<u8>,
    pub role: u64,
    pub root_pid: u32,
    pub workload_pid: u32,
    pub agent_pid: u32,
}
impl Boot {
    pub fn read() -> Result<Self> {
        // SAFETY: getauxval reads the current process's kernel-created vector.
        let address = unsafe { libc::getauxval(240) } as usize;
        anyhow::ensure!(
            address != 0 && address.is_multiple_of(4096),
            "sealed bootstrap absent"
        );
        // SAFETY: the dedicated kernel profile provides a complete read-only
        // page at AT_HEPTA_BOOT; this executable never runs without that profile.
        let bytes = unsafe { std::slice::from_raw_parts(address as *const u8, 4096) }.to_vec();
        anyhow::ensure!(
            &bytes[..8] == b"HOS2BOOT"
                && u64_at(&bytes, 8) == 2
                && u64_at(&bytes, 24) == 192
                && bytes[192..].iter().all(|byte| *byte == 0),
            "sealed bootstrap layout"
        );
        let boot = Self {
            role: u64_at(&bytes, 16),
            root_pid: u32::try_from(u64_at(&bytes, 144))?,
            workload_pid: u32::try_from(u64_at(&bytes, 152))?,
            agent_pid: u32::try_from(u64_at(&bytes, 160))?,
            bytes,
        };
        let pid = match boot.role {
            1 => boot.root_pid,
            2 => boot.workload_pid,
            3 => boot.agent_pid,
            _ => 0,
        };
        anyhow::ensure!(
            pid == std::process::id()
                && boot.root_pid == 1
                && boot.agent_pid > 1
                && boot.workload_pid > 1
                && boot.agent_pid != boot.workload_pid,
            "sealed process lifetime differs"
        );
        println!(
            "HEPTA_NATIVE_BOOT role={} pid={pid} original_owner=true production_ready=false",
            boot.role
        );
        Ok(boot)
    }
}
pub fn u64_at(bytes: &[u8], offset: usize) -> u64 {
    let mut word = [0_u8; 8];
    word.copy_from_slice(&bytes[offset..offset + 8]);
    u64::from_le_bytes(word)
}
pub fn pidfd(pid: u32) -> Result<OwnedFd> {
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    anyhow::ensure!(raw >= 0, "pidfd_open: {}", std::io::Error::last_os_error());
    Ok(unsafe { OwnedFd::from_raw_fd(raw as i32) })
}
pub fn ticks(pid: u32) -> Result<u64> {
    let value = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(value
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .ok_or_else(|| anyhow::anyhow!("missing actual start ticks"))?
        .parse()?)
}
pub fn wait_file(path: &Path) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(120);
    while !path.exists() {
        anyhow::ensure!(
            Instant::now() < deadline,
            "timed out awaiting {}",
            path.display()
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    Ok(())
}
pub fn read_json<T: serde::de::DeserializeOwned>(path: &Path, uid: u32) -> Result<T> {
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let metadata = file.metadata()?;
    anyhow::ensure!(
        metadata.is_file()
            && metadata.uid() == uid
            && metadata.nlink() == 1
            && metadata.mode() & 0o022 == 0
            && metadata.len() <= 65536,
        "unsafe handoff file"
    );
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(65537)
        .read_to_end(&mut bytes)?;
    anyhow::ensure!(bytes.len() <= 65536, "handoff too large");
    Ok(serde_json::from_slice(&bytes)?)
}
pub fn write_json(path: &Path, value: &impl serde::Serialize, mode: u32) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(mode)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    file.write_all(&serde_json::to_vec(value)?)?;
    file.sync_all()?;
    File::open(
        path.parent()
            .ok_or_else(|| anyhow::anyhow!("parent absent"))?,
    )?
    .sync_all()?;
    Ok(())
}
pub fn chown(path: &Path, uid: u32, gid: u32) -> Result<()> {
    let path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
    anyhow::ensure!(
        unsafe { libc::chown(path.as_ptr(), uid, gid) } == 0,
        "chown: {}",
        std::io::Error::last_os_error()
    );
    Ok(())
}
pub fn handoff_fresh(path: &Path) -> Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    anyhow::ensure!(!metadata.file_type().is_symlink(), "fixture link refused");
    if metadata.is_dir() {
        for child in std::fs::read_dir(path)? {
            handoff_fresh(&child?.path())?;
        }
    }
    chown(path, 60002, 60002)
}
pub fn drop_agent_credentials() -> Result<()> {
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "trusted startup requires initial root"
    );
    anyhow::ensure!(
        unsafe { libc::setgroups(0, std::ptr::null()) } == 0,
        "setgroups"
    );
    // Original image retains its kernel HOS2 process binding; ordinary Linux
    // credentials are independently and irreversibly reduced before IPC.
    for cap in 0..=40 {
        anyhow::ensure!(
            unsafe { libc::prctl(libc::PR_CAPBSET_DROP, cap, 0, 0, 0) } == 0,
            "bounding set drop {cap}"
        );
    }
    anyhow::ensure!(
        unsafe {
            libc::prctl(
                libc::PR_CAP_AMBIENT,
                libc::PR_CAP_AMBIENT_CLEAR_ALL,
                0,
                0,
                0,
            )
        } == 0,
        "ambient clear"
    );
    // NOROOT + NO_SETUID_FIXUP, both locked. Explicit capset follows UID drop.
    anyhow::ensure!(
        unsafe { libc::prctl(libc::PR_SET_SECUREBITS, 15, 0, 0, 0) } == 0,
        "securebits"
    );
    anyhow::ensure!(
        unsafe { libc::setresgid(60002, 60002, 60002) } == 0
            && unsafe { libc::setresuid(60002, 60002, 60002) } == 0,
        "uid/gid drop"
    );
    let header = [0x2008_0522_u32, 0];
    let data = [0_u32; 6];
    anyhow::ensure!(
        unsafe { libc::syscall(libc::SYS_capset, header.as_ptr(), data.as_ptr()) } == 0,
        "capset clear"
    );
    anyhow::ensure!(
        unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } == 0,
        "NNP"
    );
    let status = std::fs::read_to_string("/proc/self/status")?;
    for name in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"] {
        anyhow::ensure!(
            status
                .lines()
                .any(|line| line == format!("{name}:\t0000000000000000")),
            "nonzero {name}"
        );
    }
    anyhow::ensure!(
        status.contains("Uid:\t60002\t60002\t60002\t60002") && status.contains("NoNewPrivs:\t1"),
        "credential readback"
    );
    Ok(())
}
