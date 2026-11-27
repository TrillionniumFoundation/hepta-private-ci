//! Real anonymous FD transport and separate-purpose framing. These unprivileged
//! mechanism checks do not qualify Root custody or a registered learning owner.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::process::Command;

const ROOT_CHILD: &str =
    "root_production_handoff::learning::tests::root_learning_handoff_dedicated_uid_child";
const ROOT_PAYLOAD: &[u8] = b"actual-root-learning-handoff-qualification";

#[test]
fn learning_handoff_preserves_ordered_open_objects_and_cloexec() -> anyhow::Result<()> {
    let (sender, receiver) = UnixDatagram::pair()?;
    let mut first = tempfile::tempfile()?;
    let mut second = tempfile::tempfile()?;
    first.write_all(b"learning-scope")?;
    second.write_all(b"separate-root-pin-slot")?;
    send_packet(
        &sender,
        LEARNING_FRAME,
        &[first.as_raw_fd(), second.as_raw_fd()],
        Duration::from_secs(1),
    )?;
    let (received_first, received_second) =
        receive_learning_packet(&receiver, Duration::from_secs(1))?;
    let received_second = File::from(received_second);
    assert_eq!(received_first.metadata()?.ino(), first.metadata()?.ino());
    assert_eq!(received_second.metadata()?.ino(), second.metadata()?.ino());
    for descriptor in [&received_first, &received_second] {
        // SAFETY: F_GETFD only observes the live received file descriptor.
        assert_ne!(
            unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC,
            0
        );
    }
    assert!(validate_bootstrap(&received_first).is_err());
    Ok(())
}

#[test]
fn learning_and_original_v1_handoffs_refuse_each_others_purpose() -> anyhow::Result<()> {
    for learning_receiver in [false, true] {
        let (sender, receiver) = UnixDatagram::pair()?;
        let (first, mut first_peer) = UnixStream::pair()?;
        let (second, mut second_peer) = UnixStream::pair()?;
        send_packet(
            &sender,
            if learning_receiver {
                FRAME
            } else {
                LEARNING_FRAME
            },
            &[first.as_raw_fd(), second.as_raw_fd()],
            Duration::from_secs(1),
        )?;
        drop((first, second));
        let result = if learning_receiver {
            receive_learning_packet(&receiver, Duration::from_secs(1))
        } else {
            receive_packet(&receiver, Duration::from_secs(1))
        };
        assert!(result.is_err());
        for peer in [&mut first_peer, &mut second_peer] {
            peer.set_read_timeout(Some(Duration::from_secs(1)))?;
            assert_eq!(peer.read(&mut [0])?, 0);
        }
    }
    Ok(())
}

#[test]
#[ignore = "explicit actual Root to dedicated-UID sealed learning handoff qualification"]
fn root_learning_handoff_reaches_dedicated_uid_with_original_root_pin() -> anyhow::Result<()> {
    // SAFETY: these calls only sample the actual parent credentials.
    assert_eq!(unsafe { libc::getuid() }, 0);
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let sealed = crate::authority_host_bootstrap_seal::seal_bytes(ROOT_PAYLOAD)?;
    let (parent, child_socket) = UnixDatagram::pair()?;
    // SAFETY: pidfd_open creates a new pin for this live original Root process.
    let number = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(number >= 0, "{}", io::Error::last_os_error());
    // SAFETY: the successful syscall transfers one fresh descriptor here.
    let root_pin = unsafe { OwnedFd::from_raw_fd(number as i32) };
    let executable = File::open(std::env::current_exe()?)?;
    let inherited = [child_socket.as_raw_fd(), executable.as_raw_fd()];
    let mut command = Command::new("/usr/bin/setpriv");
    command
        .args([
            "--reuid=60001",
            "--regid=60001",
            "--clear-groups",
            "--no-new-privs",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
        ])
        .arg(format!("/proc/self/fd/{}", executable.as_raw_fd()))
        .args([
            "--exact",
            ROOT_CHILD,
            "--ignored",
            "--nocapture",
            "--test-threads=1",
        ])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env(
            "HEPTA_LEARNING_CHILD_FD",
            child_socket.as_raw_fd().to_string(),
        )
        .env("HEPTA_LEARNING_ROOT_PID", std::process::id().to_string())
        .current_dir("/")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    // SAFETY: after fork this closure only applies fcntl to the two retained
    // descriptors. The original setpriv executable drops actual credentials.
    unsafe {
        command.pre_exec(move || {
            for fd in inherited {
                let flags = libc::fcntl(fd, libc::F_GETFD);
                if flags < 0 || libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0 {
                    return Err(io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    let child = command.spawn()?;
    drop(child_socket);
    send_root_learning_handoff(parent, &sealed, &root_pin, Duration::from_secs(5))?;
    let output = child.wait_with_output()?;
    anyhow::ensure!(
        output.status.success(),
        "dedicated-UID child failed: {}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let stdout = String::from_utf8(output.stdout)?;
    assert!(
        stdout.contains("ROOT_LEARNING_HANDOFF actual_consumer_uid=60001"),
        "{stdout}"
    );
    println!("{stdout}");
    Ok(())
}

#[test]
#[ignore = "only the explicit Root learning parent supplies these inherited descriptors"]
fn root_learning_handoff_dedicated_uid_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60001, 60001)?;
    let number: i32 = std::env::var("HEPTA_LEARNING_CHILD_FD")?.parse()?;
    let original_root: u32 = std::env::var("HEPTA_LEARNING_ROOT_PID")?.parse()?;
    anyhow::ensure!(number >= 3 && original_root != std::process::id());
    // SAFETY: the trusted parent passes exclusive ownership of this one FD
    // through exec; it remains live and is claimed exactly once here.
    let socket = unsafe { UnixDatagram::from_raw_fd(number) };
    let mut handoff = receive_root_learning_handoff(socket, Duration::from_secs(5))?;
    assert_eq!(handoff.root_pid, original_root);
    require_root_pin(&handoff.root_pidfd, original_root)?;
    for fd in [
        handoff.bootstrap.as_raw_fd(),
        handoff.root_pidfd.as_raw_fd(),
    ] {
        // SAFETY: F_GETFD only reads flags of the retained received FD.
        assert_ne!(
            unsafe { libc::fcntl(fd, libc::F_GETFD) } & libc::FD_CLOEXEC,
            0
        );
    }
    let mut observed = Vec::new();
    handoff.bootstrap.read_to_end(&mut observed)?;
    assert_eq!(observed, ROOT_PAYLOAD);
    validate_bootstrap(&handoff.bootstrap)?;
    println!(
        "ROOT_LEARNING_HANDOFF actual_consumer_uid=60001 actual_consumer_pid={} original_root_pid={} sealed=true cloexec=true",
        std::process::id(),
        original_root
    );
    Ok(())
}
