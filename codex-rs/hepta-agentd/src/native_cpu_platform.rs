//! Actual guest mounts, final-image credential drop and CPU workload.
use super::*;
use std::ffi::CString;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

fn syscall(result: i32) -> io::Result<()> {
    if result < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}
fn mount(source: &str, target: &str, filesystem: &str, flags: libc::c_ulong) -> io::Result<()> {
    let source = CString::new(source).map_err(error)?;
    let target = CString::new(target).map_err(error)?;
    let filesystem = CString::new(filesystem).map_err(error)?;
    // SAFETY: all three owned C strings outlive this synchronous syscall.
    syscall(unsafe {
        libc::mount(
            source.as_ptr(),
            target.as_ptr(),
            filesystem.as_ptr(),
            flags,
            std::ptr::null(),
        )
    })
}
pub(super) fn private_dir(path: &Path, uid: u32, gid: u32, mode: u32) -> io::Result<()> {
    std::fs::DirBuilder::new().mode(mode).create(path)?;
    std::os::unix::fs::chown(path, Some(uid), Some(gid))?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))?;
    File::open(path.parent().ok_or_else(|| invalid("directory parent"))?)?.sync_all()
}
pub(super) enum StateMount {
    Fresh,
    Retained,
}

pub(super) fn existing_directory(path: &Path, uid: u32, gid: u32, mode: u32) -> io::Result<()> {
    use std::os::unix::fs::MetadataExt;
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)?;
    let actual = file.metadata()?;
    if !actual.is_dir()
        || actual.uid() != uid
        || actual.gid() != gid
        || actual.mode() & 0o7777 != mode
    {
        return Err(invalid(
            "retained native directory identity or mode differs",
        ));
    }
    file.sync_all()
}

pub(super) fn mount_platform() -> io::Result<StateMount> {
    if unsafe { libc::geteuid() } != 0 || std::process::id() != 1 {
        return Err(invalid("actual Root required"));
    }
    for path in ["/dev", "/proc", "/sys", "/run", "/state"] {
        std::fs::create_dir_all(path)?;
    }
    mount("none", "/dev", "devtmpfs", 0)?;
    mount("none", "/proc", "proc", 0)?;
    mount("none", "/sys", "sysfs", 0)?;
    std::fs::create_dir_all("/sys/fs/cgroup")?;
    mount("none", "/sys/fs/cgroup", "cgroup2", 0)?;
    mount("/dev/vda", "/state", "ext2", 0)?;
    // Presence never means a fresh installation. Existing/partial state must
    // pass the original open-only owners below; it is never reset or repaired.
    let retained = match std::fs::symlink_metadata(STATE) {
        Ok(_) => {
            existing_directory(Path::new(STATE), 0, 0, 0o711)?;
            StateMount::Retained
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            private_dir(Path::new(STATE), 0, 0, 0o711)?;
            StateMount::Fresh
        }
        Err(error) => return Err(error),
    };
    private_dir(Path::new(RUNTIME), 0, 0, 0o755)?;
    for child in ["protected-source", "protected"] {
        let path = Path::new(STATE).join(child);
        match &retained {
            StateMount::Fresh => private_dir(&path, 0, 0, 0o700)?,
            StateMount::Retained => existing_directory(&path, 0, 0, 0o700)?,
        }
    }
    mount(
        &format!("{STATE}/protected-source"),
        &format!("{STATE}/protected"),
        "none",
        libc::MS_BIND,
    )?;
    let heartbeat = Path::new(RUNTIME).join("workload-heartbeat");
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o644)
        .open(&heartbeat)?;
    file.set_len(8)?;
    file.sync_all()?;
    std::os::unix::fs::chown(&heartbeat, Some(60002), Some(60002))?;
    let report = Path::new(RUNTIME).join("workload-report.json");
    let file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o644)
        .open(&report)?;
    file.sync_all()?;
    std::os::unix::fs::chown(report, Some(60002), Some(60002))?;
    let mut ready = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o644)
        .open(Path::new(RUNTIME).join("platform-ready"))?;
    ready.write_all(b"g2-root-mounted-v1\n")?;
    ready.sync_all()?;
    File::open(RUNTIME)?.sync_all()?;
    Ok(retained)
}
/// Keep the original sealed runtime path/ancestor policy while retaining the
/// same FinalUse local stores on the state disk. Root owns both parent entries;
/// the Host cannot replace the mount source or target directory itself.
pub(super) fn mount_consumer_state() -> io::Result<()> {
    use std::os::unix::fs::MetadataExt;
    let source = Path::new(STATE).join("consumer-local");
    existing_directory(&source, 60001, 60001, 0o700)?;
    let held = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(&source)?;
    let target = Path::new(RUNTIME).join("owner/consumer-local");
    private_dir(&target, 60001, 60001, 0o700)?;
    mount(
        &source.to_string_lossy(),
        &target.to_string_lossy(),
        "none",
        libc::MS_BIND,
    )?;
    let current = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(&target)?;
    let retained = held.metadata()?;
    let observed = current.metadata()?;
    if (retained.dev(), retained.ino()) != (observed.dev(), observed.ino()) {
        return Err(invalid(
            "original consumer bind differs from its retained state inode",
        ));
    }
    existing_directory(&target, 60001, 60001, 0o700)
}

pub(super) fn wait_platform() -> io::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        if let Ok(bytes) = std::fs::read(Path::new(RUNTIME).join("platform-ready"))
            && bytes == b"g2-root-mounted-v1\n"
        {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(invalid("Root platform mount did not become ready"));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}
pub(super) fn drop_host_privileges() -> io::Result<()> {
    let mut width = 0;
    loop {
        let result = unsafe { libc::prctl(libc::PR_CAPBSET_READ, width, 0, 0, 0) };
        if result < 0 {
            if io::Error::last_os_error().raw_os_error() == Some(libc::EINVAL) {
                break;
            }
            return Err(io::Error::last_os_error());
        }
        width += 1;
        if width > 64 {
            return Err(invalid("unsupported capability width"));
        }
    }
    if width == 0 {
        return Err(invalid("missing capability bounding set"));
    }
    syscall(unsafe { libc::setgroups(0, std::ptr::null()) })?;
    syscall(unsafe { libc::prctl(libc::PR_SET_KEEPCAPS, 0, 0, 0, 0) })?;
    syscall(unsafe {
        libc::prctl(
            libc::PR_CAP_AMBIENT,
            libc::PR_CAP_AMBIENT_CLEAR_ALL,
            0,
            0,
            0,
        )
    })?;
    for cap in 0..width {
        syscall(unsafe { libc::prctl(libc::PR_CAPBSET_DROP, cap, 0, 0, 0) })?;
    }
    syscall(unsafe { libc::setresgid(60001, 60001, 60001) })?;
    syscall(unsafe { libc::setresuid(60001, 60001, 60001) })?;
    #[repr(C)]
    struct Header {
        version: u32,
        pid: i32,
    }
    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Data {
        effective: u32,
        permitted: u32,
        inheritable: u32,
    }
    let header = Header {
        version: 0x20080522,
        pid: 0,
    };
    let data = [Data {
        effective: 0,
        permitted: 0,
        inheritable: 0,
    }; 2];
    syscall(unsafe { libc::syscall(libc::SYS_capset, &header, data.as_ptr()) } as i32)?;
    syscall(unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) })?;
    syscall(unsafe { libc::prctl(libc::PR_SET_DUMPABLE, 0, 0, 0, 0) })?;
    if unsafe { libc::setfsuid(u32::MAX) } as u32 != 60001
        || unsafe { libc::setfsgid(u32::MAX) } as u32 != 60001
    {
        return Err(invalid("actual Host filesystem IDs differ"));
    }
    Ok(())
}
pub(super) fn chown_tree(path: &Path, uid: u32, gid: u32) -> io::Result<()> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() {
        return Err(invalid("owner namespace contains a symlink"));
    }
    std::os::unix::fs::chown(path, Some(uid), Some(gid))?;
    if metadata.is_dir() {
        for child in std::fs::read_dir(path)? {
            chown_tree(&child?.path(), uid, gid)?;
        }
    }
    Ok(())
}

struct Heartbeat {
    address: *mut AtomicU64,
}
impl Heartbeat {
    fn open(write: bool) -> io::Result<Self> {
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(write)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(Path::new(RUNTIME).join("workload-heartbeat"))?;
        if file.metadata()?.len() != 8 {
            return Err(invalid("heartbeat length differs"));
        }
        let protection = libc::PROT_READ | if write { libc::PROT_WRITE } else { 0 };
        // SAFETY: the retained mapping has exactly one aligned AtomicU64. The
        // trusted workload is its sole writer; consumers only observe it.
        let address = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                8,
                protection,
                libc::MAP_SHARED,
                file.as_raw_fd(),
                0,
            )
        };
        if address == libc::MAP_FAILED {
            return Err(io::Error::last_os_error());
        }
        Ok(Self {
            address: address.cast(),
        })
    }
    fn read(&self) -> u64 {
        unsafe { (*self.address).load(Ordering::Acquire) }
    }
}
impl Drop for Heartbeat {
    fn drop(&mut self) {
        unsafe {
            libc::munmap(self.address.cast(), 8);
        }
    }
}
pub(super) fn heartbeat() -> io::Result<u64> {
    Ok(Heartbeat::open(false)?.read())
}

pub(super) fn run_workload() -> io::Result<()> {
    if unsafe { libc::getuid() } != 60002
        || unsafe { libc::geteuid() } != 60002
        || std::process::id() != 3
    {
        return Err(invalid("actual distinct workload UID required"));
    }
    syscall(unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) })?;
    if unsafe { libc::getsid(0) } != 3 {
        syscall(unsafe { libc::setsid() })?;
    }
    let end = Instant::now() + Duration::from_secs(30);
    while !Path::new(RUNTIME).join("owner-installed").exists() {
        if Instant::now() >= end {
            return Err(invalid("original owner installation did not appear"));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    let mut signals = Vec::new();
    for pid in [1, 2, 4] {
        for signal in [0, libc::SIGKILL] {
            let rc = unsafe { libc::kill(pid, signal) };
            let errno = if rc < 0 {
                io::Error::last_os_error().raw_os_error().unwrap_or(0)
            } else {
                0
            };
            signals.push(serde_json::json!({"pid":pid,"signal":signal,"rc":rc,"errno":errno}));
            if rc != -1 || errno != libc::EPERM {
                return Err(invalid("workload signal isolation failed"));
            }
        }
    }
    let mut path_checks = Vec::new();
    let agent = codex_hepta_contracts::AgentId::parse(AGENT).map_err(error)?;
    let layout = codex_hepta_paths::HeptaFleetRoot::parse(Path::new(STATE).join("fleet"))
        .map_err(error)?
        .layout()
        .agent(&agent);
    for (kind, path) in [
        ("host-store", layout.home_root().to_path_buf()),
        (
            "root-material",
            Path::new(STATE).join("protected/authority/material"),
        ),
    ] {
        let path = CString::new(path.as_os_str().as_encoded_bytes()).map_err(error)?;
        let fd = unsafe {
            libc::open(
                path.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC,
            )
        };
        let errno = if fd < 0 {
            io::Error::last_os_error().raw_os_error().unwrap_or(0)
        } else {
            unsafe { libc::close(fd) };
            0
        };
        path_checks.push(serde_json::json!({"kind":kind,"rc":if fd<0 {-1} else {0},"errno":errno}));
    }
    let device = CString::new("/dev/hepta-control").unwrap();
    let fd = unsafe { libc::open(device.as_ptr(), libc::O_RDWR | libc::O_CLOEXEC) };
    let device_errno = if fd < 0 {
        io::Error::last_os_error().raw_os_error().unwrap_or(0)
    } else {
        unsafe { libc::close(fd) };
        0
    };
    let report = serde_json::json!({"workload_signal_checks":signals,"workload_host_path_checks":path_checks,"workload_device_open_errno":device_errno});
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .truncate(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(Path::new(RUNTIME).join("workload-report.json"))?;
    file.write_all(&serde_json::to_vec(&report).map_err(error)?)?;
    file.sync_all()?;
    let heartbeat = Heartbeat::open(true)?;
    let mut work = 1_u64;
    loop {
        for _ in 0..10000 {
            work = std::hint::black_box(work.wrapping_mul(6364136223846793005).wrapping_add(1));
        }
        unsafe {
            (*heartbeat.address).fetch_add(1, Ordering::Release);
        }
    }
}
