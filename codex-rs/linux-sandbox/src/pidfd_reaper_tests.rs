use super::*;
use std::os::fd::IntoRawFd;

// Use a real isolated process so blocking SIGCHLD cannot interfere with the
// test harness's threads. The alarm is a failed-test bound, not a PASS path.
fn isolated(body: fn() -> libc::c_int) {
    let pid = unsafe { libc::fork() };
    assert!(pid >= 0, "fork isolated pidfd control");
    if pid == 0 {
        unsafe {
            libc::alarm(5);
            libc::_exit(body());
        }
    }
    let mut status = 0;
    assert_eq!(unsafe { libc::waitpid(pid, &mut status, 0) }, pid);
    assert!(libc::WIFEXITED(status), "isolated control status {status}");
    assert_eq!(libc::WEXITSTATUS(status), 0);
}

fn open_pidfd(pid: libc::pid_t) -> File {
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(fd >= 0, "open actual process pidfd");
    unsafe { File::from_raw_fd(fd as RawFd) }
}

#[test]
fn normal_child_exit_is_reaped_with_original_status() {
    isolated(|| {
        let owner = OwnerPidfd::from_inherited(
            open_current_owner_pidfd()
                .unwrap_or_else(|error| panic!("self pidfd: {error}"))
                .into_raw_fd(),
        )
        .unwrap_or_else(|error| panic!("inherited self pidfd: {error}"));
        let events = ChildExitEvents::new().unwrap_or_else(|error| panic!("child events: {error}"));
        let child = unsafe { libc::fork() };
        assert!(child >= 0);
        if child == 0 {
            events
                .restore_mask()
                .unwrap_or_else(|error| panic!("original child mask: {error}"));
            unsafe { libc::_exit(17) }
        }
        let status = events
            .wait_for_command(child, &owner)
            .unwrap_or_else(|error| panic!("real wait: {error}"));
        events
            .restore_mask()
            .unwrap_or_else(|error| panic!("original init mask: {error}"));
        if libc::WIFEXITED(status) && libc::WEXITSTATUS(status) == 17 {
            0
        } else {
            1
        }
    });
}

#[test]
fn owner_already_dead_before_inner_entry_exits_before_command() {
    isolated(|| {
        let owner_pid = unsafe { libc::fork() };
        assert!(owner_pid >= 0);
        if owner_pid == 0 {
            unsafe { libc::_exit(0) }
        }
        let fd = open_pidfd(owner_pid);
        let mut status = 0;
        assert_eq!(
            unsafe { libc::waitpid(owner_pid, &mut status, 0) },
            owner_pid
        );
        let inner = unsafe { libc::fork() };
        assert!(inner >= 0);
        if inner == 0 {
            unsafe { libc::alarm(3) };
            let _owner = OwnerPidfd::from_inherited(fd.into_raw_fd());
            unsafe { libc::_exit(1) }
        }
        assert_eq!(unsafe { libc::waitpid(inner, &mut status, 0) }, inner);
        if libc::WIFEXITED(status) && libc::WEXITSTATUS(status) == 128 + libc::SIGKILL {
            0
        } else {
            1
        }
    });
}

#[test]
fn actual_owner_exit_wakes_blocking_reaper_without_sigchld() {
    isolated(|| {
        let owner_pid = unsafe { libc::fork() };
        assert!(owner_pid >= 0);
        if owner_pid == 0 {
            unsafe { libc::alarm(3) };
            loop {
                unsafe { libc::pause() };
            }
        }
        let owner_fd = open_pidfd(owner_pid);
        let mut ready = [0; 2];
        assert_eq!(
            unsafe { libc::pipe2(ready.as_mut_ptr(), libc::O_CLOEXEC) },
            0
        );
        let inner = unsafe { libc::fork() };
        assert!(inner >= 0);
        if inner == 0 {
            unsafe { libc::alarm(4) };
            unsafe { libc::close(ready[0]) };
            let owner = OwnerPidfd::from_inherited(owner_fd.into_raw_fd())
                .unwrap_or_else(|error| panic!("owner: {error}"));
            let events = ChildExitEvents::new().unwrap_or_else(|error| panic!("events: {error}"));
            assert_eq!(unsafe { libc::write(ready[1], b"R".as_ptr().cast(), 1) }, 1);
            events
                .wait_for_event(&owner)
                .unwrap_or_else(|error| panic!("owner-only kernel event: {error}"));
            unsafe { libc::_exit(1) }
        }
        unsafe { libc::close(ready[1]) };
        let mut byte = 0_u8;
        assert_eq!(
            unsafe { libc::read(ready[0], (&mut byte as *mut u8).cast(), 1) },
            1
        );
        assert_eq!(byte, b'R');
        assert_eq!(unsafe { libc::kill(owner_pid, libc::SIGKILL) }, 0);
        let mut status = 0;
        assert_eq!(
            unsafe { libc::waitpid(owner_pid, &mut status, 0) },
            owner_pid
        );
        assert_eq!(unsafe { libc::waitpid(inner, &mut status, 0) }, inner);
        unsafe { libc::close(ready[0]) };
        if libc::WIFEXITED(status) && libc::WEXITSTATUS(status) == 128 + libc::SIGKILL {
            0
        } else {
            1
        }
    });
}

#[test]
fn ordinary_descriptor_cannot_replace_owner_pidfd() {
    for path in ["/dev/null", "/proc"] {
        let file =
            File::open(path).unwrap_or_else(|error| panic!("ordinary descriptor {path}: {error}"));
        let result = OwnerPidfd::from_inherited(file.as_raw_fd());
        assert!(matches!(result, Err(error) if error.kind() == io::ErrorKind::InvalidInput));
    }
    let mut pipe = [0; 2];
    assert_eq!(
        unsafe { libc::pipe2(pipe.as_mut_ptr(), libc::O_CLOEXEC) },
        0
    );
    for fd in pipe {
        let file = unsafe { File::from_raw_fd(fd) };
        let result = OwnerPidfd::from_inherited(file.as_raw_fd());
        assert!(matches!(result, Err(error) if error.kind() == io::ErrorKind::InvalidInput));
    }
}

#[test]
fn pidfd_type_check_does_not_consume_real_child_exit_status() {
    isolated(|| {
        let child = unsafe { libc::fork() };
        assert!(child >= 0);
        if child == 0 {
            unsafe { libc::_exit(23) }
        }
        let child_fd = open_pidfd(child);
        let mut info = unsafe { std::mem::zeroed::<libc::siginfo_t>() };
        assert_eq!(
            unsafe {
                libc::waitid(
                    libc::P_PIDFD,
                    child_fd.as_raw_fd() as libc::id_t,
                    &mut info,
                    libc::WEXITED | libc::WNOWAIT,
                )
            },
            0
        );
        validate_pidfd(child_fd.as_raw_fd())
            .unwrap_or_else(|error| panic!("actual child pidfd type: {error}"));
        let mut status = 0;
        assert_eq!(unsafe { libc::waitpid(child, &mut status, 0) }, child);
        if libc::WIFEXITED(status) && libc::WEXITSTATUS(status) == 23 {
            0
        } else {
            1
        }
    });
}

#[test]
fn restoring_sigchld_does_not_reblock_forwarded_signals() {
    isolated(|| {
        let mut mask = unsafe { std::mem::zeroed::<libc::sigset_t>() };
        unsafe {
            libc::sigemptyset(&mut mask);
            libc::sigaddset(&mut mask, libc::SIGTERM);
        }
        assert_eq!(
            unsafe { libc::sigprocmask(libc::SIG_BLOCK, &mask, std::ptr::null_mut()) },
            0
        );
        let events = ChildExitEvents::new().unwrap_or_else(|error| panic!("child events: {error}"));
        assert_eq!(
            unsafe { libc::sigprocmask(libc::SIG_UNBLOCK, &mask, std::ptr::null_mut()) },
            0
        );
        events
            .restore_mask()
            .unwrap_or_else(|error| panic!("restore child mask: {error}"));
        assert_eq!(
            unsafe { libc::sigprocmask(libc::SIG_SETMASK, std::ptr::null(), &mut mask) },
            0
        );
        if unsafe { libc::sigismember(&mask, libc::SIGTERM) } == 0 {
            0
        } else {
            1
        }
    });
}
