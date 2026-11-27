//! Actual Root-to-dedicated-UID custody and purpose negative controls. These
//! sealed framing vectors construct no CURRENT, grant, Model or ordinary task.

use super::*;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;
use std::os::unix::process::CommandExt;
use std::process::Command;

const CHILD: &str = "root_production_handoff::generation_publication::tests::publication_handoff_dedicated_uid_child";
const PAYLOAD: &[u8] = b"root-publication-framing-only-not-an-enrollment";

#[test]
#[ignore = "explicit actual Root to dedicated UID publication-purpose qualification"]
fn root_publication_handoff_reaches_dedicated_uid_and_refuses_confused_rights() -> anyhow::Result<()>
{
    // SAFETY: these calls only observe the actual parent credentials.
    assert_eq!(unsafe { libc::getuid() }, 0);
    assert_eq!(unsafe { libc::geteuid() }, 0);
    for mode in ["valid", "wrong-purpose", "wrong-order"] {
        let sealed = crate::authority_host_bootstrap_seal::seal_bytes(PAYLOAD)?;
        let (send, receive) = UnixDatagram::pair()?;
        // SAFETY: pidfd_open creates a new owned pin for this exact live Root.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
        anyhow::ensure!(raw >= 0, "{}", io::Error::last_os_error());
        // SAFETY: the successful syscall transfers one new owned descriptor.
        let root = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        let executable = File::open(std::env::current_exe()?)?;
        let inherited = [receive.as_raw_fd(), executable.as_raw_fd()];
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
                CHILD,
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env(
                "HEPTA_PUBLICATION_HANDOFF_FD",
                receive.as_raw_fd().to_string(),
            )
            .env("HEPTA_PUBLICATION_ROOT_PID", std::process::id().to_string())
            .env("HEPTA_PUBLICATION_MODE", mode)
            .current_dir("/")
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped());
        // SAFETY: after fork only async-signal-safe fcntl touches the two
        // retained rights. setpriv performs the actual UID/capability drop.
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
        let mut child = command.spawn()?;
        drop(receive);
        match mode {
            "valid" => send_root_generation_publication_handoff(
                send,
                crate::RootGenerationPublicationOfferV1 { bootstrap: sealed },
                &root,
                Duration::from_secs(5),
            )?,
            "wrong-purpose" => {
                crate::send_root_learning_handoff(send, &sealed, &root, Duration::from_secs(5))?
            }
            "wrong-order" => send_packet(
                &send,
                PUBLICATION_FRAME,
                &[root.as_raw_fd(), sealed.as_raw_fd()],
                Duration::from_secs(5),
            )?,
            _ => anyhow::bail!("unknown explicit test case"),
        }
        let end = std::time::Instant::now() + Duration::from_secs(10);
        while child.try_wait()?.is_none() {
            if std::time::Instant::now() >= end {
                child.kill()?;
                let _ = child.wait();
                anyhow::bail!("dedicated-UID original child deadline");
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        let output = child.wait_with_output()?;
        anyhow::ensure!(
            output.status.success(),
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        let stdout = String::from_utf8(output.stdout)?;
        anyhow::ensure!(stdout.contains("ROOT_PUBLICATION_HANDOFF actual_consumer_uid=60001"));
        println!("{stdout}");
    }
    Ok(())
}

#[test]
#[ignore = "only the explicit Root parent supplies the original inherited pair"]
fn publication_handoff_dedicated_uid_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60001, 60001)?;
    let raw: i32 = std::env::var("HEPTA_PUBLICATION_HANDOFF_FD")?.parse()?;
    let root_pid: u32 = std::env::var("HEPTA_PUBLICATION_ROOT_PID")?.parse()?;
    let mode = std::env::var("HEPTA_PUBLICATION_MODE")?;
    anyhow::ensure!(raw >= 3 && root_pid != std::process::id());
    // SAFETY: the original trusted parent transferred exclusive ownership of
    // this single inherited socket through exec; it is claimed exactly once.
    let socket = unsafe { UnixDatagram::from_raw_fd(raw) };
    let result = receive_root_generation_publication_handoff(socket, Duration::from_secs(5));
    if mode == "valid" {
        let mut handoff = result?;
        assert_eq!(handoff.root_pid, root_pid);
        require_root_pin(&handoff.root_pidfd, root_pid)?;
        for raw in [
            handoff.bootstrap.as_raw_fd(),
            handoff.root_pidfd.as_raw_fd(),
        ] {
            // SAFETY: F_GETFD only observes the live transferred descriptor.
            assert_ne!(
                unsafe { libc::fcntl(raw, libc::F_GETFD) } & libc::FD_CLOEXEC,
                0
            );
        }
        let mut bytes = Vec::new();
        handoff.bootstrap.read_to_end(&mut bytes)?;
        assert_eq!(bytes, PAYLOAD);
    } else {
        assert!(result.is_err());
    }
    println!(
        "ROOT_PUBLICATION_HANDOFF actual_consumer_uid=60001 mode={mode} original_root_pid={root_pid}"
    );
    Ok(())
}
