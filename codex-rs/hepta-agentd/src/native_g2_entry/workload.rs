//! Actual isolated CPU workload. Its observations never grant source authority.

use super::boot::Boot;
use super::paths;
use super::supervisor;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

pub(super) const HEARTBEAT: &str = "/run/hepta-g2/workload-heartbeat";
pub(super) const SOCKET: &str = "/run/hepta-g2/workload.sock";

pub(super) struct Heartbeat {
    file: File,
    mapping: *mut libc::c_void,
}

impl Heartbeat {
    pub(super) fn create() -> io::Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(HEARTBEAT)?;
        file.set_len(4096)?;
        // SAFETY: fchown acts only on this newly created retained file.
        if unsafe { libc::fchown(file.as_raw_fd(), 60002, 60002) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Self::map(file, /*write*/ false)
    }
    fn map(file: File, write: bool) -> io::Result<Self> {
        // SAFETY: the retained ordinary file has exactly one page. mmap returns
        // a fresh mapping; only the workload writes one naturally aligned u64.
        let mapping = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                4096,
                libc::PROT_READ | if write { libc::PROT_WRITE } else { 0 },
                libc::MAP_SHARED,
                file.as_raw_fd(),
                0,
            )
        };
        if mapping == libc::MAP_FAILED {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { file, mapping })
    }
    pub(super) fn read(&self) -> u64 {
        // SAFETY: this mapping stays live/aligned for self's lifetime. The
        // workload's only writer uses the exact same AtomicU64 protocol.
        unsafe { &*self.mapping.cast::<AtomicU64>() }.load(Ordering::Acquire)
    }
}
impl Drop for Heartbeat {
    fn drop(&mut self) {
        // SAFETY: self uniquely owns this live one-page mapping, not its file.
        unsafe {
            libc::munmap(self.mapping, 4096);
        }
        let _ = &self.file;
    }
}

pub(super) fn run(boot: Boot) -> Result<(), Box<dyn std::error::Error>> {
    // Kernel created workload credentials/session are checked by Boot and
    // independently read by Root. No attempt to acquire a native owner role.
    let stream = supervisor::connect_parent(std::path::Path::new(SOCKET))?;
    let mut channel = HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid: 0, pid: 1 },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(120),
            request_bound: 32768,
            response_bound: 32768,
        },
        supervisor::pin(1)?,
    )?;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(HEARTBEAT)?;
    if file.metadata()?.len() != 4096 {
        return Err("invalid actual heartbeat mapping".into());
    }
    let heartbeat = Heartbeat::map(file, /*write*/ true)?;
    channel.exchange(|request| {
        if request!=b"observe-isolation-v1" { return Err(codex_hepta_contracts::HostIssuerTransportError::InvalidRequest); }
        let mut signals=Vec::new();
        for pid in [1,boot.pids[0],boot.pids[2]] {
            for signal in [0,9] {
                // SAFETY: these are the actual privileged kernel-selected
                // processes. Their existing UID/session boundary must refuse.
                let rc=unsafe {libc::kill(pid as i32,signal)};
                signals.push(serde_json::json!({"pid":pid,"signal":signal,"rc":rc,
                    "errno":if rc<0 {io::Error::last_os_error().raw_os_error().unwrap_or(0)} else {0}}));
            }
        }
        let paths=[("host-store",format!("{}/agents/bf5c80be-3b26-4fd2-95e1-32f395538f6c/cognitive",paths::FLEET)),
            ("root-material",format!("{}/authority/cognitive-material-v1",paths::STATE))];
        let mut denials=Vec::new();
        for (kind,path) in paths {
            let result=File::open(path);
            let errno=result.as_ref().err().and_then(io::Error::raw_os_error).unwrap_or(0);
            denials.push(serde_json::json!({"kind":kind,"rc":if result.is_err(){-1}else{0},"errno":errno}));
        }
        let device=OpenOptions::new().read(true).write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC).open("/dev/hepta-control");
        serde_json::to_vec(&serde_json::json!({"workload_signal_checks":signals,
            "workload_host_path_checks":denials,"workload_device_open_errno":device.err()
                .and_then(|error|error.raw_os_error()).unwrap_or(0)}))
            .map_err(|_|codex_hepta_contracts::HostIssuerTransportError::Unavailable)
    })?;
    drop(channel);
    // No I/O or syscall substitutes for CPU work. The shared heartbeat advances
    // only while the actual workload process is scheduled by the controlled CPU.
    let counter = unsafe { &*heartbeat.mapping.cast::<AtomicU64>() };
    loop {
        counter.fetch_add(1, Ordering::Release);
        std::hint::spin_loop();
    }
}
