//! Collision-safe, syscall-only child setup. All allocation happens before fork.
//! Command::pre_exec cannot expose its internal exec-error pipe: dup2 onto role
//! FD3/4/5/6 could replace that pipe. This launcher owns a separate high pipe.

use super::root_role_child as process;
use super::root_role_child::RootRoleChild;
use std::ffi::CString;
use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;

pub(super) struct Mapping {
    descriptor: OwnedFd,
    target: i32,
}
pub(super) struct Deadlines {
    pub(super) total: u64,
    pub(super) exec: u64,
}
impl Deadlines {
    pub(super) fn new(total:u64) -> io::Result<Self> {
        let before = process::now()?;
        let remaining = total.checked_sub(before).filter(|n| *n > 0 && *n <= 300_000_000_000)
            .ok_or_else(||io::Error::other("original Root preparation deadline required"))?;
        Ok(Self { total,exec:before+remaining.min(5_000_000_000) })
    }
}
impl Mapping {
    pub(super) fn new(descriptor: &impl AsRawFd, target: i32) -> io::Result<Self> {
        if ![0,1,2,3,4,5,6].contains(&target) { return Err(io::Error::other("fixed role FD required")); }
        Ok(Self { descriptor:duplicate(descriptor.as_raw_fd())?, target })
    }
}

pub(super) fn spawn(executable: File, arguments: Vec<CString>, environment: Vec<CString>,
    directory: CString, mappings: Vec<Mapping>, uid: u32, deadlines:Deadlines) -> io::Result<RootRoleChild>
{
    super::root_role_executable::require_root()?;
    process::remaining(deadlines.exec)?;
    // The trusted Root launcher is the sole reaper of these children. Refuse an
    // inherited auto-reap policy, which would invalidate the unreaped-PID proof.
    let mut action: libc::sigaction = unsafe { std::mem::zeroed() };
    if unsafe { libc::sigaction(libc::SIGCHLD, std::ptr::null(), &mut action) } < 0 {
        return Err(io::Error::last_os_error());
    }
    if action.sa_sigaction == libc::SIG_IGN || action.sa_flags & libc::SA_NOCLDWAIT != 0 {
        return Err(io::Error::other("Root launcher requires exclusive child reaping"));
    }
    // Discover the complete supported bounding set BEFORE fork; never silently
    // skip a kernel-supported capability. Both kernels reject the first unknown
    // index with EINVAL. No /proc read or Rust allocation occurs in the child.
    let mut capabilities = 0;
    loop {
        let value = unsafe { libc::prctl(libc::PR_CAPBSET_READ, capabilities, 0, 0, 0) };
        if value < 0 {
            if io::Error::last_os_error().raw_os_error() == Some(libc::EINVAL) { break; }
            return Err(io::Error::last_os_error());
        }
        capabilities += 1;
        if capabilities > 64 { return Err(io::Error::other("unsupported capability width")); }
    }
    if capabilities == 0 { return Err(io::Error::other("missing capability bounding API")); }
    let (read, write) = error_pipe()?;
    let argv = arguments.iter().map(|s| s.as_ptr()).chain([std::ptr::null()]).collect::<Vec<_>>();
    let envp = environment.iter().map(|s| s.as_ptr()).chain([std::ptr::null()]).collect::<Vec<_>>();
    process::remaining(deadlines.exec)?;
    // SAFETY: the child below uses only preallocated memory and raw syscalls,
    // never Rust locks, allocation, environment mutation or filesystem reads.
    let pid = unsafe { libc::fork() };
    if pid < 0 { return Err(io::Error::last_os_error()); }
    if pid == 0 {
        let error = unsafe { child_setup(executable.as_raw_fd(), &mappings,
            uid, capabilities, directory.as_ptr(), argv.as_ptr(), envp.as_ptr()) };
        // SAFETY: four bytes fit atomically in our empty nonblocking pipe. No
        // destructor/panic/formatting/allocator may run in the forked child.
        unsafe {
            libc::write(write.as_raw_fd(), (&error as *const i32).cast(), 4);
            libc::_exit(127);
        }
    }
    drop(write);
    let mut pending = PendingChild::new(pid)?;
    wait_exec(&read, pending.pidfd.as_ref().unwrap(), deadlines.exec)?;
    // Transfer exclusive reap responsibility. from_executed cleans up on ALL
    // errors; PendingChild must never subsequently kill a recycled numeric PID.
    pending.armed = false;
    RootRoleChild::from_executed(pid, pending.pidfd.take().unwrap(), uid, deadlines.total)
}

unsafe fn child_setup(executable: i32, mappings: &[Mapping], uid:u32,
    capabilities:i32, directory:*const libc::c_char, argv:*const *const libc::c_char,
    envp:*const *const libc::c_char) -> i32
{
    // The high error pipe and executable remain CLOEXEC. Mark every inherited
    // descriptor, including any concurrently opened parent FD, atomically before
    // clearing CLOEXEC only through dup2 of the complete fixed mapping.
    if unsafe { libc::syscall(libc::SYS_close_range, 0u32, u32::MAX, 4u32) } < 0 {
        return errno();
    }
    for mapping in mappings {
        if unsafe { libc::dup2(mapping.descriptor.as_raw_fd(), mapping.target) } < 0 { return errno(); }
    }
    if unsafe { libc::setgroups(0, std::ptr::null()) } < 0
        || unsafe { libc::prctl(libc::PR_SET_KEEPCAPS, 0, 0, 0, 0) } < 0
        || unsafe { libc::prctl(libc::PR_CAP_AMBIENT, libc::PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) } < 0
    { return errno(); }
    for capability in 0..capabilities {
        if unsafe { libc::prctl(libc::PR_CAPBSET_DROP, capability, 0, 0, 0) } < 0 { return errno(); }
    }
    if unsafe { libc::setresgid(uid,uid,uid) } < 0 || unsafe { libc::setresuid(uid,uid,uid) } < 0 {
        return errno();
    }
    #[repr(C)] struct Header { version:u32, pid:i32 }
    #[repr(C)] #[derive(Clone,Copy)] struct Data { effective:u32, permitted:u32, inheritable:u32 }
    let header = Header { version:0x20080522, pid:0 };
    let data = [Data { effective:0,permitted:0,inheritable:0 };2];
    if unsafe { libc::syscall(libc::SYS_capset, &header, data.as_ptr()) } < 0
        || unsafe { libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) } < 0
        || unsafe { libc::chdir(directory) } < 0
    { return errno(); }
    // Actual filesystem IDs must match too, even if inherited securebits have
    // altered the usual automatic credential transitions.
    if unsafe { libc::setfsuid(u32::MAX) } as u32 != uid
        || unsafe { libc::setfsgid(u32::MAX) } as u32 != uid
    { return libc::EPERM; }
    // AT_EMPTY_PATH executes exactly the retained inode, even if its pathname
    // is replaced concurrently. No /proc path lookup after dropping privileges.
    unsafe { libc::syscall(libc::SYS_execveat, executable, c"".as_ptr(), argv, envp, libc::AT_EMPTY_PATH) };
    errno()
}
fn errno() -> i32 {
    // SAFETY: errno is this thread's initialized libc TLS errno slot.
    unsafe { *libc::__errno_location() }
}
fn duplicate(raw:i32) -> io::Result<OwnedFd> {
    // SAFETY: F_DUPFD_CLOEXEC returns a new independently owned high descriptor.
    let high = unsafe { libc::fcntl(raw, libc::F_DUPFD_CLOEXEC, 10) };
    if high < 0 { return Err(io::Error::last_os_error()); }
    Ok(unsafe { OwnedFd::from_raw_fd(high) })
}
fn error_pipe() -> io::Result<(OwnedFd,OwnedFd)> {
    let mut pipe = [-1;2];
    // SAFETY: pipe points to two initialized writable descriptor slots.
    if unsafe { libc::pipe2(pipe.as_mut_ptr(), libc::O_CLOEXEC | libc::O_NONBLOCK) } < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful pipe2 returned exactly these two fresh owned descriptors.
    let read = unsafe { OwnedFd::from_raw_fd(pipe[0]) };
    let write = unsafe { OwnedFd::from_raw_fd(pipe[1]) };
    Ok((duplicate(read.as_raw_fd())?,duplicate(write.as_raw_fd())?))
}
fn wait_exec(read:&OwnedFd, pidfd:&OwnedFd, end:u64) -> io::Result<()> {
    loop {
        let nanos = process::remaining(end)?;
        let mut fds = [libc::pollfd { fd:read.as_raw_fd(),events:libc::POLLIN,revents:0 },
            libc::pollfd { fd:pidfd.as_raw_fd(),events:libc::POLLIN,revents:0 }];
        if unsafe { libc::poll(fds.as_mut_ptr(),2,nanos.div_ceil(1_000_000).min(10) as i32) } < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted { continue; }
            return Err(error);
        }
        if fds[0].revents != 0 {
            let mut error = 0i32;
            let count = unsafe { libc::read(read.as_raw_fd(),(&mut error as *mut i32).cast(),4) };
            process::remaining(end)?;
            if count == 0 && fds[1].revents == 0 { return Ok(()); }
            if count == 4 && error > 0 { return Err(io::Error::from_raw_os_error(error)); }
            if count < 0 && matches!(io::Error::last_os_error().raw_os_error(),Some(libc::EAGAIN | libc::EINTR)) { continue; }
            return Err(io::Error::other("role exec failed or child exited before admission"));
        }
        if fds[1].revents != 0 { return Err(io::Error::other("role exited during exec")); }
    }
}
struct PendingChild { pid:libc::pid_t, pidfd:Option<OwnedFd>, armed:bool }
impl PendingChild {
    fn new(pid:libc::pid_t) -> io::Result<Self> {
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open,pid,0) };
        if raw < 0 {
            let error = io::Error::last_os_error();
            process::reap_failed_fork(pid);
            return Err(error);
        }
        Ok(Self { pid,pidfd:Some(unsafe { OwnedFd::from_raw_fd(raw as i32) }),armed:true })
    }
}
impl Drop for PendingChild {
    fn drop(&mut self) { if self.armed { process::reap_failed_fork(self.pid); } }
}
