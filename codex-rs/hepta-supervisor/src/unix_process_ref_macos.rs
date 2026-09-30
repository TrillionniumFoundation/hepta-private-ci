//! Darwin uses a kernel-issued audit token for atomic signal target validation
//! and a registered EVFILT_PROC exit event for lifetime observation. See Apple's
//! proc_info.c psignal_by_audit_token and tests/signal_exit_reason.c. No raw-PID
//! fallback is permitted when an SDK/kernel or host policy refuses this path.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[repr(C)]
#[derive(Clone, Copy, Eq, PartialEq)]
struct AuditToken {
    values: [u32; 8],
}

// Darwin mach/task_info.h and mach/message.h ABI. A task name right is enough
// to query TASK_AUDIT_TOKEN; this does not obtain a task-control capability.
const TASK_AUDIT_TOKEN: i32 = 15;
const TASK_AUDIT_TOKEN_COUNT: u32 = 8;

unsafe extern "C" {
    static mach_task_self_: u32;
    fn task_name_for_pid(task: u32, pid: i32, name: *mut u32) -> i32;
    fn task_info(task: u32, flavor: i32, info: *mut i32, count: *mut u32) -> i32;
    fn mach_port_deallocate(task: u32, name: u32) -> i32;
}

struct TaskName(u32);

impl Drop for TaskName {
    fn drop(&mut self) {
        // SAFETY: this object owns the send right returned by task_name_for_pid.
        unsafe { mach_port_deallocate(mach_task_self_, self.0) };
    }
}

fn audit_token(pid: i32) -> io::Result<AuditToken> {
    let mut name = 0_u32;
    // SAFETY: the output is initialized writable storage and PID is positive.
    let result = unsafe { task_name_for_pid(mach_task_self_, pid, &mut name) };
    if result != 0 {
        return Err(io::Error::other(format!("task name acquisition failed: {result}")));
    }
    let name = TaskName(name);
    let mut token = AuditToken { values: [0; 8] };
    let mut count = TASK_AUDIT_TOKEN_COUNT;
    // SAFETY: AuditToken is exactly eight 32-bit words with C representation.
    let result = unsafe {
        task_info(name.0, TASK_AUDIT_TOKEN, token.values.as_mut_ptr().cast(), &mut count)
    };
    if result != 0 || count != TASK_AUDIT_TOKEN_COUNT || token.values[5] != pid as u32 {
        return Err(io::Error::other("kernel audit-token acquisition failed"));
    }
    Ok(token)
}

type SignalFn = unsafe extern "C" fn(*mut AuditToken, i32) -> i32;

struct Library(*mut libc::c_void);

impl Drop for Library {
    fn drop(&mut self) {
        // SAFETY: this object owns the successful dlopen reference.
        unsafe { libc::dlclose(self.0) };
    }
}

fn with_signal_api<T>(call: impl FnOnce(SignalFn) -> io::Result<T>) -> io::Result<T> {
    // Use the OS library, not a request-controlled search path or environment.
    // SAFETY: both C strings are static and NUL terminated.
    let library = unsafe {
        libc::dlopen(c"/usr/lib/libproc.dylib".as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL)
    };
    if library.is_null() {
        return Err(io::Error::new(io::ErrorKind::Unsupported, "libproc is unavailable"));
    }
    let library = Library(library);
    // SAFETY: library stays loaded through the entire synchronous call below.
    let symbol = unsafe {
        libc::dlsym(library.0, c"proc_signal_with_audittoken".as_ptr())
    };
    if symbol.is_null() {
        return Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "this macOS lacks audit-token-bound process signaling",
        ));
    }
    // SAFETY: the named Apple libproc function has the declared C signature.
    let signal = unsafe { std::mem::transmute::<*mut libc::c_void, SignalFn>(symbol) };
    call(signal)
}

pub(in crate::unix) struct ProcessRef {
    queue: File,
    pid: u32,
    token: AuditToken,
    observed_exit: AtomicBool,
}

impl ProcessRef {
    pub(in crate::unix) fn open(pid: u32) -> io::Result<Option<Self>> {
        let native_pid = super::checked_pid(pid)?;
        with_signal_api(|_| Ok(()))?;
        let token = audit_token(native_pid)?;
        // SAFETY: kqueue creates a new kernel descriptor without pointer inputs.
        let descriptor = unsafe { libc::kqueue() };
        if descriptor < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: kqueue returned one newly owned descriptor.
        let queue = unsafe { File::from_raw_fd(descriptor) };
        // SAFETY: the live descriptor is owned by queue; FD_CLOEXEC is a flag.
        if unsafe { libc::fcntl(queue.as_raw_fd(), libc::F_SETFD, libc::FD_CLOEXEC) } < 0 {
            return Err(io::Error::last_os_error());
        }
        let change = libc::kevent {
            ident: pid as libc::uintptr_t,
            filter: libc::EVFILT_PROC,
            flags: libc::EV_ADD | libc::EV_ENABLE | libc::EV_ONESHOT,
            fflags: libc::NOTE_EXIT,
            data: 0,
            udata: std::ptr::null_mut(),
        };
        // SAFETY: one initialized change; no result buffer; no blocking wait.
        let result = unsafe {
            libc::kevent(queue.as_raw_fd(), &change, 1, std::ptr::null_mut(), 0, std::ptr::null())
        };
        if result < 0 {
            let error = io::Error::last_os_error();
            return if error.raw_os_error() == Some(libc::ESRCH) { Ok(None) } else { Err(error) };
        }
        let reference = Self { queue, pid, token, observed_exit: AtomicBool::new(false) };
        if reference.exited()? {
            return Ok(None);
        }
        // Registering by PID must not bind a replacement between token capture
        // and EVFILT_PROC registration. The kernel-issued pidversion must agree.
        if audit_token(native_pid)? != token {
            return Err(io::Error::other("process changed during lifetime acquisition"));
        }
        Ok(Some(reference))
    }

    pub(in crate::unix) fn exited(&self) -> io::Result<bool> {
        if self.observed_exit.load(Ordering::Acquire) {
            return Ok(true);
        }
        let mut event = libc::kevent {
            ident: 0,
            filter: 0,
            flags: 0,
            fflags: 0,
            data: 0,
            udata: std::ptr::null_mut(),
        };
        let timeout = libc::timespec { tv_sec: 0, tv_nsec: 0 };
        // SAFETY: one initialized event slot; zero timeout is nonblocking.
        let result = unsafe {
            libc::kevent(self.queue.as_raw_fd(), std::ptr::null(), 0, &mut event, 1, &timeout)
        };
        if result < 0 {
            return Err(io::Error::last_os_error());
        }
        if result == 0 {
            return Ok(false);
        }
        if event.flags & libc::EV_ERROR != 0 {
            return Err(io::Error::other("process exit event reported an error"));
        }
        if event.ident != self.pid as libc::uintptr_t
            || event.filter != libc::EVFILT_PROC
            || event.fflags & libc::NOTE_EXIT == 0
        {
            return Err(io::Error::other("unexpected adopted-process exit event"));
        }
        self.observed_exit.store(true, Ordering::Release);
        Ok(true)
    }

    pub(in crate::unix) fn signal(&self, signal: i32) -> io::Result<()> {
        if !matches!(signal, libc::SIGTERM | libc::SIGKILL) {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "unsupported control signal"));
        }
        let mut token = self.token;
        with_signal_api(|send| {
            // SAFETY: the token came from the kernel; libproc/kernel revalidate
            // pidversion and retain the matching process before delivering signal.
            let error = unsafe { send(&mut token, signal) };
            if error != 0 {
                return Err(io::Error::from_raw_os_error(error));
            }
            Ok(())
        })
    }
}
