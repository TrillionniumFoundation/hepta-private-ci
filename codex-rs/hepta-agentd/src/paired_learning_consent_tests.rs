//! Real child-process refusal; these inherited handles establish no human authority.

use std::ffi::CString;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;

#[test]
fn inherited_handles_cannot_authorize_or_exchange_without_an_original_turn_verifier()
-> anyhow::Result<()> {
    let binary = codex_utils_cargo_bin::cargo_bin("hepta-paired-consent")?;
    let temp = tempfile::tempdir()?;
    let route = temp.path().join("unread-route");
    let route_name = CString::new(route.as_os_str().as_bytes())?;
    // SAFETY: the path is a live NUL-terminated string. A FIFO makes an
    // accidental route read block, rather than merely return a parsing error.
    assert_eq!(unsafe { libc::mkfifo(route_name.as_ptr(), 0o600) }, 0);
    let pid = std::process::id();
    // SAFETY: pidfd_open returns an owned descriptor for the live test process.
    let descriptor = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(descriptor >= 0);
    // SAFETY: the successful syscall transferred this descriptor's ownership.
    let identity = unsafe { OwnedFd::from_raw_fd(descriptor as i32) };
    let (mut observed, child_endpoint) = UnixStream::pair()?;
    let mut command = Command::new(binary);
    command
        .arg(pid.to_string())
        .arg(temp.path().join("absent-sqlite"))
        .arg(route)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    // SAFETY: duplicate both held descriptors before replacing fixed child
    // slots. Only async-signal-safe descriptor operations run after fork.
    unsafe {
        command.pre_exec(move || {
            let socket = libc::fcntl(child_endpoint.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 5);
            if socket < 0 {
                return Err(std::io::Error::last_os_error());
            }
            let birth = libc::fcntl(identity.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 5);
            if birth < 0 || libc::dup2(socket, 3) < 0 || libc::dup2(birth, 4) < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let mut child = command.spawn()?;
    drop(command);
    // Deliberately keep stdin open without bytes: the refusal must not read it.
    let _held_input = child.stdin.take().expect("piped child stdin");
    let deadline = Instant::now() + Duration::from_secs(5);
    while child.try_wait()?.is_none() {
        if Instant::now() >= deadline {
            child.kill()?;
            child.wait()?;
            anyhow::bail!("legacy consent waited for an untrusted route, stdin or issuer");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let output = child.wait_with_output()?;
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(output.stdout, Vec::<u8>::new());
    assert!(String::from_utf8(output.stderr)?.contains("ORIGINAL_TURN_VERIFIER_REQUIRED"));
    observed.set_nonblocking(true)?;
    assert_eq!(observed.read(&mut [0; 1])?, 0, "issuer lane received bytes");
    assert!(!temp.path().join("absent-sqlite").exists());
    Ok(())
}
