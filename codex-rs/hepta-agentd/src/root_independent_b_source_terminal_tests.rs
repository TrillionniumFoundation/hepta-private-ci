//! Real Root/source processes and original channel postchecks. This verifies
//! terminal lifetime coordination, not signed source admission or B execution.

use std::os::fd::FromRawFd;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use pretty_assertions::assert_eq;

use super::*;
use crate::root_generation_current_client::OriginalPublicationStream;
use crate::root_independent_b_source_protocol::receive_original_end;
use crate::root_independent_b_source_protocol::seal_original_end;

const RECEIPT: &str = "ORIGINAL_B_SOURCE_TERMINAL_COMPONENT_FINISHED";

struct ChildGuard(Option<Child>);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        if let Some(child) = &mut self.0 {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn pin(pid: u32) -> io::Result<OwnedFd> {
    // SAFETY: pidfd_open observes this concrete test process and returns one FD.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful pidfd_open transferred exactly this owned descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(raw as i32) })
}

fn run_parent(phase: &str) -> anyhow::Result<()> {
    crate::authority_host_service::generation_initial::original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("b-terminal-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o711))?;
    let path = directory.path().join("actual-source.sock");
    let listener = UnixListener::bind(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))?;
    listener.set_nonblocking(true)?;
    let (writer, reader) = OriginalBNoticeWriter::pair()?;
    let root = pin(std::process::id())?;
    let root_fd = root.as_raw_fd();
    let notice_fd = reader.as_raw_fd();
    let end = Instant::now() + Duration::from_secs(10);
    let stat = std::fs::read_to_string("/proc/self/stat")?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, s)| s.split_whitespace().nth(19))
        .ok_or_else(|| io::Error::other("actual Root start missing"))?;
    let name = concat!(module_path!(), "::original_b_source_terminal_child");
    let name = name
        .split_once("::")
        .ok_or_else(|| io::Error::other("test path missing"))?
        .1;
    let mut command = Command::new(std::env::current_exe()?);
    command
        .args(["--ignored", "--exact", name, "--nocapture"])
        .uid(60_002)
        .gid(60_002)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("HEPTA_B_TERMINAL_PHASE", phase)
        .env("HEPTA_B_TERMINAL_SOCKET", &path)
        .env("HEPTA_B_TERMINAL_ROOT_FD", root_fd.to_string())
        .env("HEPTA_B_TERMINAL_NOTICE_FD", notice_fd.to_string())
        .env("HEPTA_B_TERMINAL_ROOT_PID", std::process::id().to_string())
        .env("HEPTA_B_TERMINAL_ROOT_START", start)
        .env("HEPTA_B_TERMINAL_END", seal_original_end(end)?.to_string());
    // SAFETY: only the two original inherited descriptors are changed in the
    // child before exec. The parent retains both owned descriptors until spawn.
    unsafe {
        command.pre_exec(move || {
            for fd in [root_fd, notice_fd] {
                if libc::fcntl(fd, libc::F_SETFD, 0) < 0 {
                    return Err(io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    let mut child = ChildGuard(Some(command.spawn()?));
    let process = child
        .0
        .as_mut()
        .ok_or_else(|| io::Error::other("source child absent"))?;
    let source = pin(process.id())?;
    let stream = loop {
        if Instant::now() >= end || process.try_wait()?.is_some() {
            anyhow::bail!("source child ended before actual connection");
        }
        match listener.accept() {
            Ok((stream, _)) => break stream,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(5))
            }
            Err(error) => return Err(error.into()),
        }
    };
    let mut channel = HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: 60_002,
                pid: process.id(),
            },
            timeout: Duration::from_millis(500),
            lifetime: end
                .checked_duration_since(Instant::now())
                .ok_or_else(|| io::Error::other("component end elapsed"))?,
            request_bound: 128,
            response_bound: 128,
        },
        source,
    )?;
    channel.limit_original_end(end)?;
    assert!(channel.exchange_with_original_deadline(|request, _| {
        assert_eq!(request, b"component source input");
        Ok(b"component input acknowledgement".to_vec())
    })?);
    // The real exchange has checked the source pidfd after writing its ACK.
    // The child still waits on the separate original notification descriptor.
    assert!(process.try_wait()?.is_none());
    match phase {
        "finalized" => writer.send(b"component finalized cut", end, || {
            crate::root_observation_stream::check_lifetime(&root).map_err(io::Error::other)
        })?,
        "missing" => drop(writer),
        _ => anyhow::bail!("unknown component phase"),
    }
    let output = child
        .0
        .take()
        .ok_or_else(|| io::Error::other("source child absent"))?
        .wait_with_output()?;
    assert!(
        output.status.success(),
        "child stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stdout).contains(&format!("{RECEIPT}:{phase}")));
    Ok(())
}

#[test]
#[ignore = "actual UID0 Root and independent UID60002 source process"]
fn original_b_source_terminal_notice_allows_exit_after_real_frame_postcheck() -> anyhow::Result<()>
{
    run_parent("finalized")
}

#[test]
#[ignore = "actual UID0 Root and independent UID60002 source process"]
fn original_b_source_terminal_missing_notice_never_completes() -> anyhow::Result<()> {
    run_parent("missing")
}

#[test]
#[ignore = "only the original Root parent invokes this UID60002 component child"]
fn original_b_source_terminal_child() -> anyhow::Result<()> {
    let phase = std::env::var("HEPTA_B_TERMINAL_PHASE")?;
    // SAFETY: getuid/geteuid only observe this actual child process.
    assert_eq!(unsafe { libc::getuid() }, 60_002);
    assert_eq!(unsafe { libc::geteuid() }, 60_002);
    let parse = |key| -> anyhow::Result<u64> { Ok(std::env::var(key)?.parse()?) };
    let root_fd = i32::try_from(parse("HEPTA_B_TERMINAL_ROOT_FD")?)?;
    let notice_fd = i32::try_from(parse("HEPTA_B_TERMINAL_NOTICE_FD")?)?;
    if root_fd <= 2 || notice_fd <= 2 || root_fd == notice_fd {
        anyhow::bail!("original rights missing");
    }
    // SAFETY: this private test child consumes the parent's inherited rights
    // exactly once. The product constructors below verify their actual peers.
    let root = unsafe { OwnedFd::from_raw_fd(root_fd) };
    let notice = unsafe { File::from_raw_fd(notice_fd) };
    let original_root = root.try_clone()?;
    let root_pid = u32::try_from(parse("HEPTA_B_TERMINAL_ROOT_PID")?)?;
    let end = receive_original_end(parse("HEPTA_B_TERMINAL_END")?)?;
    let stream = UnixStream::connect(std::env::var("HEPTA_B_TERMINAL_SOCKET")?)?;
    let mut stream = OriginalPublicationStream::from_stream_until(
        stream,
        root,
        crate::AgentdRootAuthorityPeer {
            pid: root_pid,
            boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
                .trim()
                .into(),
            process_start_ticks: parse("HEPTA_B_TERMINAL_ROOT_START")?,
        },
        Duration::from_millis(500),
        end,
    )?;
    assert_eq!(
        stream.exchange(b"component source input")?,
        b"component input acknowledgement"
    );
    let observed = receive_original_notice(notice, root_pid, end, || {
        crate::root_observation_stream::check_lifetime(&original_root).map_err(io::Error::other)
    });
    match phase.as_str() {
        "finalized" => assert_eq!(observed?, b"component finalized cut"),
        "missing" => assert!(observed.is_err()),
        _ => anyhow::bail!("unknown component phase"),
    }
    println!("{RECEIPT}:{phase}");
    std::io::stdout().flush()?;
    Ok(())
}
