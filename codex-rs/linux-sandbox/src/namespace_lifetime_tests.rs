use super::*;
use pretty_assertions::assert_eq;
use std::ffi::CStr;
use std::ffi::CString;
use std::io::Write;
use std::os::fd::IntoRawFd;

#[test]
fn inherited_reader_restores_close_on_exec_and_detects_an_already_closed_owner() -> io::Result<()> {
    let (reader, owner) = channel()?;
    let fd = reader.into_raw_fd();
    // SAFETY: the descriptor was just transferred out of reader.
    assert_eq!(unsafe { libc::fcntl(fd, libc::F_SETFD, 0) }, 0);
    // SAFETY: no Rust object owns fd after into_raw_fd.
    let mut reader = unsafe { take_reader(fd) }?;
    // SAFETY: reader keeps this descriptor open.
    assert_ne!(
        unsafe { libc::fcntl(reader.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC,
        0
    );
    require_live_owner(&reader)?;
    drop(owner);
    assert!(require_live_owner(&reader).is_err());
    // EOF is persistent even if the owner vanished before watcher startup.
    wait_for_owner_loss(&mut reader);
    Ok(())
}

#[test]
fn non_stream_and_unconnected_descriptors_cannot_impersonate_owner_liveness() -> io::Result<()> {
    let regular = tempfile::NamedTempFile::new()?;
    let file = File::open(regular.path())?;
    // SAFETY: ownership of file is transferred, including on rejection.
    assert!(unsafe { take_reader(file.into_raw_fd()) }.is_err());

    let (datagram, _peer) = std::os::unix::net::UnixDatagram::pair()?;
    // SAFETY: ownership of the datagram is transferred, including on rejection.
    assert!(unsafe { take_reader(datagram.into_raw_fd()) }.is_err());

    let directory = tempfile::tempdir()?;
    let listener = std::os::unix::net::UnixListener::bind(directory.path().join("listener"))?;
    // SAFETY: a listener has no connected peer and must be rejected.
    assert!(unsafe { take_reader(listener.into_raw_fd()) }.is_err());
    Ok(())
}

#[test]
fn duplicated_observer_cannot_retain_owner_and_cannot_send() -> io::Result<()> {
    let (reader, owner) = channel()?;
    let duplicate = reader.try_clone()?;
    // SAFETY: ownership of the observing endpoint is transferred exactly once.
    let mut reader = unsafe { take_reader(reader.into_raw_fd()) }?;
    let byte = [1_u8];
    // SAFETY: MSG_NOSIGNAL avoids signaling this test for the closed write half.
    assert_eq!(
        unsafe { libc::send(duplicate.as_raw_fd(), byte.as_ptr().cast(), 1, libc::MSG_NOSIGNAL) },
        -1
    );
    assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EPIPE));
    require_live_owner(&reader)?;
    drop(owner);
    observe_eof(&mut reader)?;
    // Keeping this duplicate alive must not delay EOF after the other peer dies.
    drop(duplicate);
    Ok(())
}

#[test]
fn owner_peer_close_is_observed_after_fork_and_a_new_session() -> io::Result<()> {
    let (mut reader, owner) = channel()?;
    let (mut ready_reader, mut ready_writer) = channel()?;
    // SAFETY: each branch retains distinct ownership of its inherited file
    // table. The child uses a finite poll and exits without Rust unwinding.
    let pid = unsafe { libc::fork() };
    if pid < 0 {
        return Err(io::Error::last_os_error());
    }
    if pid == 0 {
        drop(owner);
        drop(ready_reader);
        // SAFETY: setsid affects only this child, matching bubblewrap's
        // separate-session boundary.
        unsafe {
            if libc::setsid() < 0 {
                libc::_exit(2);
            }
        }
        if ready_writer.write_all(&[1]).is_err() {
            // SAFETY: exit only this owned test child on setup failure.
            unsafe { libc::_exit(3) }
        }
        drop(ready_writer);
        let mut descriptor = libc::pollfd {
            fd: reader.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: the initialized descriptor remains owned by reader. On
        // timeout the child exits itself; the test sends no process signal.
        if unsafe { libc::poll(&mut descriptor, 1, 2_000) } <= 0 {
            // SAFETY: terminate only this owned test child on timeout/error.
            unsafe { libc::_exit(4) }
        }
        wait_for_owner_loss(&mut reader);
        // SAFETY: EOF must arrive without a signal to the child or its group.
        unsafe { libc::_exit(0) }
    }

    drop(reader);
    drop(ready_writer);
    let mut ready = [0_u8; 1];
    let ready_result = ready_reader.read_exact(&mut ready);
    // Only this owner peer remains. The new-session child closed its copy.
    drop(owner);
    let mut status = 0;
    loop {
        // SAFETY: pid is the unreaped child just created by this test.
        let result = unsafe { libc::waitpid(pid, &mut status, 0) };
        if result == pid {
            break;
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted {
            return Err(error);
        }
    }
    ready_result?;
    assert_eq!(ready, [1]);
    assert!(libc::WIFEXITED(status), "child status: {status}");
    assert_eq!(libc::WEXITSTATUS(status), 0);
    Ok(())
}

#[test]
fn private_owner_peer_cannot_be_reopened_through_proc() -> io::Result<()> {
    // Hardening and capability changes apply only to this isolated child, never
    // to the multithreaded test process or another test's credentials.
    // SAFETY: the owned child exits without Rust unwinding across the fork.
    let owner_pid = unsafe { libc::fork() };
    if owner_pid < 0 {
        return Err(io::Error::last_os_error());
    }
    if owner_pid == 0 {
        let code = if check_private_owner_peer().is_ok() { 0 } else { 1 };
        // SAFETY: terminate only this owned test subprocess.
        unsafe { libc::_exit(code) }
    }
    wait_child_success(owner_pid)
}

fn check_private_owner_peer() -> io::Result<()> {
    let mut header = [0x2008_0522_u32, 0];
    let mut capabilities = [[0_u32; 3]; 2];
    // SAFETY: Linux capability ABI v3 uses this header and two data entries.
    // Clearing all three sets prevents a CAP_SYS_PTRACE bypass in the probe.
    if unsafe {
        libc::syscall(
            libc::SYS_capset,
            header.as_mut_ptr(),
            capabilities.as_mut_ptr(),
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: this isolated owner enables the positive control before hardening.
    if unsafe { libc::prctl(libc::PR_SET_DUMPABLE, 1, 0, 0, 0) } < 0 {
        return Err(io::Error::last_os_error());
    }
    let (reader, owner) = channel()?;
    let (mut control, mut probe_control) = channel()?;
    // SAFETY: getpid/getuid inspect only the current process identity.
    let owner_pid = unsafe { libc::getpid() };
    let owner_uid = unsafe { libc::getuid() };
    let paths = [reader.as_raw_fd(), owner.as_raw_fd()]
        .map(|fd| CString::new(format!("/proc/{owner_pid}/fd/{fd}")))
        .into_iter()
        .collect::<Result<Vec<_>, _>>()
        .map_err(io::Error::other)?;
    // SAFETY: the child uses inherited descriptors and a bounded handshake.
    let probe_pid = unsafe { libc::fork() };
    if probe_pid < 0 {
        return Err(io::Error::last_os_error());
    }
    if probe_pid == 0 {
        drop(owner);
        drop(control);
        let result = (|| {
            // SAFETY: the probe has not changed UID since the owner fork.
            if unsafe { libc::getuid() } != owner_uid {
                return Err(io::Error::other("probe UID changed"));
            }
            for path in &paths {
                // O_PATH proves /proc access before hardening. A socket itself
                // cannot be reopened as a writer, even while access is allowed.
                check_proc_open(path, libc::O_PATH, None)?;
                check_proc_open(path, libc::O_WRONLY | libc::O_NONBLOCK, Some(libc::ENXIO))?;
            }
            probe_control.write_all(&[1])?;
            receive_byte(&mut probe_control)?;
            for path in &paths {
                check_proc_open(path, libc::O_PATH, Some(libc::EACCES))?;
                check_proc_open(path, libc::O_WRONLY | libc::O_NONBLOCK, Some(libc::EACCES))?;
            }
            probe_control.write_all(&[1])?;
            let mut reader = reader;
            observe_eof(&mut reader)
        })();
        // SAFETY: terminate only this probe; no process is killed by signal.
        unsafe { libc::_exit(if result.is_ok() { 0 } else { 2 }) }
    }
    drop(probe_control);
    let handshake = (|| {
        receive_byte(&mut control)?;
        codex_process_hardening::disable_process_dumping()?;
        control.write_all(&[1])?;
        receive_byte(&mut control)
    })();
    drop(owner);
    drop(control);
    // Retain another observer while the probe proves that owner loss is EOF.
    let reaped = wait_child_success(probe_pid);
    drop(reader);
    handshake?;
    reaped
}

fn check_proc_open(path: &CStr, flags: libc::c_int, expected_errno: Option<i32>) -> io::Result<()> {
    // SAFETY: path is NUL-terminated; O_CLOEXEC contains any successful probe FD.
    let fd = unsafe { libc::open(path.as_ptr(), flags | libc::O_CLOEXEC) };
    let error = io::Error::last_os_error();
    if fd >= 0 {
        // SAFETY: the successful open returned a descriptor owned only here.
        unsafe { libc::close(fd) };
        return if expected_errno.is_none() {
            Ok(())
        } else {
            Err(io::Error::other("private descriptor unexpectedly opened"))
        };
    }
    if error.raw_os_error() == expected_errno {
        Ok(())
    } else {
        Err(error)
    }
}

fn receive_byte(reader: &mut File) -> io::Result<()> {
    wait_readable(reader)?;
    let mut byte = [0_u8];
    reader.read_exact(&mut byte)?;
    if byte != [1] {
        return Err(io::Error::other("unexpected subprocess handshake"));
    }
    Ok(())
}

fn observe_eof(reader: &mut File) -> io::Result<()> {
    wait_readable(reader)?;
    if reader.read(&mut [0_u8])? != 0 {
        return Err(io::Error::other("owner loss did not produce EOF"));
    }
    Ok(())
}

fn wait_readable(reader: &File) -> io::Result<()> {
    let mut descriptor = libc::pollfd {
        fd: reader.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    // SAFETY: the initialized descriptor is owned throughout the bounded poll.
    if unsafe { libc::poll(&mut descriptor, 1, 2_000) } <= 0 {
        return Err(io::Error::other("subprocess readiness timed out or failed"));
    }
    Ok(())
}

fn wait_child_success(pid: libc::pid_t) -> io::Result<()> {
    let mut status = 0;
    loop {
        // SAFETY: pid is the unreaped child created by the calling test branch.
        let result = unsafe { libc::waitpid(pid, &mut status, 0) };
        if result == pid {
            break;
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted {
            return Err(error);
        }
    }
    if !libc::WIFEXITED(status) || libc::WEXITSTATUS(status) != 0 {
        return Err(io::Error::other(format!("subprocess status: {status}")));
    }
    Ok(())
}
