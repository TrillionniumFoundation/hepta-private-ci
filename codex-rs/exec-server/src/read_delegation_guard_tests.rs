//! A test-only Linux v7.0 delegation precursor; no authorized-read capability.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::marker::PhantomData;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::IntoRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::rc::Rc;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

// Fixed upstream 028ef9c96e96197026887c0f092424679298aae8, uapi/linux/fcntl.h.
const F_GETDELEG: libc::c_int = 1039;
const F_SETDELEG: libc::c_int = 1040;
const F_OWNER_TID: libc::c_int = 0;
const F_SETOWN_EX: libc::c_int = 15;
const F_GETOWN_EX: libc::c_int = 16;
const F_SETSIG: libc::c_int = 10;
const F_GETSIG: libc::c_int = 11;

#[repr(C)]
struct Delegation {
    flags: u32,
    kind: u16,
    padding: u16,
}

#[repr(C)]
struct Owner {
    kind: libc::c_int,
    tid: libc::pid_t,
}

const _: () = assert!(size_of::<Delegation>() == 8 && size_of::<Owner>() == 8);

#[derive(Clone, Copy, Debug)]
enum Stage {
    Abi,
    Temporary,
    Prepare,
    Identity,
    Thread,
    Mask,
    Pending,
    SignalFd,
    Owner,
    Signal,
    SetDelegation,
    SetLease,
    GetDelegation,
    Notification,
    Link,
    Close,
    Cleanup,
    Invariant,
    Invalidated,
}

#[derive(Clone, Copy, Debug)]
enum Status {
    Unsupported,
    Refused,
    Error,
}

#[derive(Clone, Copy, Debug)]
struct Failure {
    stage: Stage,
    status: Status,
    os: Option<i32>,
}

type Check<T> = Result<T, Failure>;

fn failure(stage: Stage, os: Option<i32>) -> Failure {
    let status = match os {
        Some(libc::EINVAL | libc::ENOSYS | libc::EOPNOTSUPP)
            if matches!(stage, Stage::SetDelegation | Stage::GetDelegation) =>
        {
            Status::Unsupported
        }
        Some(libc::EPERM | libc::EACCES) => Status::Refused,
        _ => Status::Error,
    };
    Failure { stage, status, os }
}

fn checked(ret: libc::c_int, stage: Stage) -> Check<()> {
    if ret == 0 {
        Ok(())
    } else {
        Err(failure(
            stage,
            (ret < 0)
                .then(|| io::Error::last_os_error().raw_os_error())
                .flatten(),
        ))
    }
}

fn io_failure(stage: Stage, error: io::Error) -> Failure {
    failure(stage, error.raw_os_error())
}

fn ensure(condition: bool, stage: Stage) -> Check<()> {
    condition
        .then_some(())
        .ok_or_else(|| failure(stage, /*os*/ None))
}

// This object never leaves its fresh thread. It never reads a signal record.
// SIGIO remains blocked until thread exit; the caller's mask is untouched.
struct Notification {
    fd: OwnedFd,
    tid: libc::pid_t,
    _thread: PhantomData<Rc<()>>,
}

impl Notification {
    fn new() -> Check<Self> {
        // SAFETY: sigset_t is an initialized plain C object; only SIGIO is added.
        let mut set: libc::sigset_t = unsafe { std::mem::zeroed() };
        // SAFETY: both calls receive a valid writable sigset_t.
        checked(unsafe { libc::sigemptyset(&mut set) }, Stage::Mask)?;
        checked(
            unsafe { libc::sigaddset(&mut set, libc::SIGIO) },
            Stage::Mask,
        )?;
        // SAFETY: modifies only this dedicated thread's mask, not dispositions.
        let ret = unsafe { libc::pthread_sigmask(libc::SIG_BLOCK, &set, std::ptr::null_mut()) };
        if ret != 0 {
            return Err(failure(Stage::Mask, Some(ret)));
        }
        // SAFETY: pending is initialized storage. Inspection consumes no signal.
        let mut pending: libc::sigset_t = unsafe { std::mem::zeroed() };
        checked(unsafe { libc::sigpending(&mut pending) }, Stage::Pending)?;
        ensure(
            unsafe { libc::sigismember(&pending, libc::SIGIO) } == 0,
            Stage::Pending,
        )?;
        // SAFETY: creates a new owned descriptor for the one blocked signal.
        let fd = unsafe {
            libc::signalfd(/*fd*/ -1, &set, libc::SFD_CLOEXEC | libc::SFD_NONBLOCK)
        };
        if fd < 0 {
            return Err(io_failure(Stage::SignalFd, io::Error::last_os_error()));
        }
        // SAFETY: signalfd returned a new valid descriptor owned only here.
        let fd = unsafe { OwnedFd::from_raw_fd(fd) };
        // SAFETY: gettid has no pointer arguments and returns this Linux TID.
        let tid = unsafe { libc::syscall(libc::SYS_gettid) };
        let tid =
            libc::pid_t::try_from(tid).map_err(|_| failure(Stage::Owner, /*os*/ None))?;
        ensure(tid > 0, Stage::Owner)?;
        Ok(Self {
            fd,
            tid,
            _thread: PhantomData,
        })
    }

    fn configure(&self, file: &File) -> Check<()> {
        let owner = Owner {
            kind: F_OWNER_TID,
            tid: self.tid,
        };
        // SAFETY: file is live; both fcntl argument forms match the pinned UAPI.
        checked(
            unsafe { libc::fcntl(file.as_raw_fd(), F_SETOWN_EX, &owner as *const Owner) },
            Stage::Owner,
        )?;
        checked(
            unsafe { libc::fcntl(file.as_raw_fd(), F_SETSIG, libc::SIGIO) },
            Stage::Signal,
        )?;
        self.verify(file)
    }

    fn verify(&self, file: &File) -> Check<()> {
        let mut owner = Owner { kind: -1, tid: 0 };
        // SAFETY: owner is writable storage for the exact 8-byte UAPI structure.
        checked(
            unsafe { libc::fcntl(file.as_raw_fd(), F_GETOWN_EX, &mut owner as *mut Owner) },
            Stage::Owner,
        )?;
        ensure(
            owner.kind == F_OWNER_TID && owner.tid == self.tid,
            Stage::Owner,
        )?;
        // SAFETY: F_GETSIG takes no third argument and does not mutate ownership.
        let signal = unsafe { libc::fcntl(file.as_raw_fd(), F_GETSIG) };
        if signal < 0 {
            return Err(io_failure(Stage::Signal, io::Error::last_os_error()));
        }
        ensure(signal == libc::SIGIO, Stage::Signal)
    }

    fn hint(&self) -> Check<bool> {
        let mut poll = libc::pollfd {
            fd: self.fd.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: one valid pollfd; this does not read or consume a queued signal.
        let ret = unsafe {
            libc::poll(&mut poll, /*nfds*/ 1, /*timeout*/ 2_000)
        };
        if ret < 0 {
            return Err(io_failure(Stage::Notification, io::Error::last_os_error()));
        }
        ensure(poll.revents & !libc::POLLIN == 0, Stage::Notification)?;
        Ok(ret == 1 && poll.revents & libc::POLLIN != 0)
    }
}

// There is no Clone, descriptor accessor, renewal, or second final query.
struct ReadDelegation {
    file: File,
    _thread: PhantomData<Rc<()>>,
}

impl ReadDelegation {
    fn acquire(file: File, notification: &Notification) -> Check<Self> {
        notification.configure(&file)?;
        let delegation = Delegation {
            flags: 0,
            kind: libc::F_RDLCK as u16,
            padding: 0,
        };
        // SAFETY: file is a private live read-only descriptor; UAPI is exactly 8 bytes.
        checked(
            unsafe {
                libc::fcntl(
                    file.as_raw_fd(),
                    F_SETDELEG,
                    &delegation as *const Delegation,
                )
            },
            Stage::SetDelegation,
        )?;
        notification.verify(&file)?;
        let metadata = file
            .metadata()
            .map_err(|e| io_failure(Stage::Identity, e))?;
        ensure(metadata.is_file() && metadata.nlink() == 1, Stage::Identity)?;
        Ok(Self {
            file,
            _thread: PhantomData,
        })
    }

    fn finish(self, notification: &Notification, case: u8) -> Check<u16> {
        let kind = finish_file(self.file, notification, case)?;
        if kind == libc::F_RDLCK as u16 {
            Ok(kind)
        } else if kind == libc::F_UNLCK as u16 {
            Err(failure(Stage::Invalidated, /*os*/ None))
        } else {
            Err(failure(Stage::Invariant, /*os*/ None))
        }
    }
}

fn finish_file(file: File, notification: &Notification, case: u8) -> Check<u16> {
    let owner = notification.verify(&file);
    let mut state = Delegation {
        flags: 0,
        kind: libc::F_UNLCK as u16,
        padding: 0,
    };
    // SAFETY: one final query on this exact live description; output storage is valid.
    let query = checked(
        unsafe { libc::fcntl(file.as_raw_fd(), F_GETDELEG, &mut state as *mut Delegation) },
        Stage::GetDelegation,
    );
    let shape = ensure(
        state.flags == 0 && state.padding == 0 && state.kind <= 2,
        Stage::GetDelegation,
    );
    // SAFETY: ownership is consumed; no Rust owner can close or use this number again.
    // Linux close is not retried, including on EINTR, to avoid closing a reused number.
    let closed = checked(unsafe { libc::close(file.into_raw_fd()) }, Stage::Close);
    println!(
        "DELEGATION_CLOSE case={case} success={} os={:?}",
        closed.is_ok(),
        closed.as_ref().err().and_then(|e| e.os)
    );
    owner?;
    closed?;
    query?;
    shape?;
    Ok(state.kind)
}

fn run_owned(root: &Path, case: u8) -> Check<()> {
    let path = root.join("owned");
    let alias = root.join("alias");
    let created = OpenOptions::new()
        .write(/*write*/ true)
        .create_new(/*create_new*/ true)
        .mode(/*mode*/ 0o600)
        .open(&path)
        .map_err(|e| io_failure(Stage::Prepare, e))?;
    drop(created);
    let original = std::fs::metadata(&path).map_err(|e| io_failure(Stage::Identity, e))?;
    // SAFETY: geteuid has no pointer arguments and does not mutate credentials.
    ensure(
        original.is_file() && original.nlink() == 1 && original.uid() == unsafe { libc::geteuid() },
        Stage::Identity,
    )?;
    let (start, receive) = mpsc::channel();
    let (done, completed) = mpsc::channel();
    let actor_path = path.clone();
    let actor_alias = alias.clone();
    // The actor starts before this thread blocks SIGIO; it does not inherit that change.
    let actor = thread::Builder::new()
        .spawn(move || -> Check<bool> {
            if receive.recv().is_err() {
                return Ok(false);
            }
            let result =
                std::fs::hard_link(actor_path, actor_alias).map_err(|e| io_failure(Stage::Link, e));
            let _ = done.send(());
            result.map(|()| true)
        })
        .map_err(|e| io_failure(Stage::Thread, e))?;
    let observation = (|| -> Check<()> {
        let notification = Notification::new()?;
        let file = File::open(&path).map_err(|e| io_failure(Stage::Prepare, e))?;
        let (state, hint) = if case == 2 {
            notification.configure(&file)?;
            // SAFETY: this is deliberately an ordinary lease control, never a ReadDelegation.
            checked(
                unsafe { libc::fcntl(file.as_raw_fd(), libc::F_SETLEASE, libc::F_RDLCK) },
                Stage::SetLease,
            )?;
            let hint = start
                .send(())
                .map_err(|_| failure(Stage::Thread, /*os*/ None))
                .and_then(|()| {
                    completed
                        .recv_timeout(Duration::from_secs(/*secs*/ 2))
                        .map(|()| true)
                        .map_err(|_| failure(Stage::Notification, /*os*/ None))
                });
            (finish_file(file, &notification, case), hint)
        } else {
            let guard = ReadDelegation::acquire(file, &notification)?;
            let hint = if case == 1 {
                start
                    .send(())
                    .map_err(|_| failure(Stage::Thread, /*os*/ None))
                    .and_then(|()| notification.hint())
            } else {
                Ok(false)
            };
            // The final query and close occur even if waiting for the hint failed.
            (guard.finish(&notification, case), hint)
        };
        let invalidated = matches!(
            state,
            Err(Failure {
                stage: Stage::Invalidated,
                status: Status::Error,
                os: None,
            })
        );
        println!(
            "DELEGATION_STATE case={case} kind={:?} hint={:?} invalidated={invalidated}",
            state.as_ref().ok(),
            hint.as_ref().ok()
        );
        match state {
            Err(_) if case == 1 && invalidated => (),
            Err(error) => return Err(error),
            Ok(_) if case == 1 => return Err(failure(Stage::Invariant, /*os*/ None)),
            Ok(kind) => {
                let expected = if case == 0 {
                    libc::F_RDLCK
                } else {
                    libc::F_UNLCK
                };
                ensure(kind == expected as u16, Stage::Invariant)?;
            }
        }
        ensure(case == 0 || hint?, Stage::Invariant)
    })();
    // On every ordinary result the private A is already closed before joining the actor.
    drop(start);
    let linked = actor
        .join()
        .map_err(|_| failure(Stage::Thread, /*os*/ None))?;
    println!(
        "DELEGATION_LINK case={case} completed={:?}",
        linked.as_ref().ok()
    );
    let linked = linked?;
    let identity = if linked {
        let after = std::fs::metadata(&path).map_err(|e| io_failure(Stage::Identity, e))?;
        let alias = std::fs::metadata(&alias).map_err(|e| io_failure(Stage::Identity, e))?;
        ensure(
            after.dev() == original.dev()
                && after.ino() == original.ino()
                && after.dev() == alias.dev()
                && after.ino() == alias.ino()
                && after.nlink() == 2
                && alias.nlink() == 2,
            Stage::Identity,
        )
    } else {
        ensure(case == 0 || observation.is_err(), Stage::Invariant)
    };
    observation?;
    identity
}

fn fixture(case: u8) -> Check<()> {
    if !cfg!(any(target_arch = "x86_64", target_arch = "aarch64")) {
        return Err(Failure {
            stage: Stage::Abi,
            status: Status::Unsupported,
            os: None,
        });
    }
    let directory = tempfile::tempdir().map_err(|e| io_failure(Stage::Temporary, e))?;
    let result = run_owned(directory.path(), case);
    let cleaned = directory.close().map_err(|e| io_failure(Stage::Cleanup, e));
    println!(
        "DELEGATION_CLEANUP case={case} success={} os={:?}",
        cleaned.is_ok(),
        cleaned.as_ref().err().and_then(|e| e.os)
    );
    cleaned?;
    result
}

#[test]
fn private_read_delegation_detects_owned_link_break() -> Check<()> {
    let mut success = true;
    for case in 0..3 {
        let result = thread::Builder::new()
            .spawn(move || fixture(case))
            .map_err(|e| io_failure(Stage::Thread, e))
            .and_then(|thread| {
                thread
                    .join()
                    .map_err(|_| failure(Stage::Thread, /*os*/ None))
            })
            .and_then(|result| result);
        match result {
            Ok(()) => println!("DELEGATION_CASE case={case} status=PASS"),
            Err(error) => {
                println!(
                    "DELEGATION_CASE case={case} status={:?} stage={:?} os={:?}",
                    error.status, error.stage, error.os
                );
                success = false;
            }
        }
    }
    ensure(success, Stage::Invariant)
}
