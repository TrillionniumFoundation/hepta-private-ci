use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use crate::UnixListener;
use crate::UnixStream;

#[tokio::test]
async fn adopted_listener_uses_original_socket_and_leaves_owner_paths_intact() {
    let directory = tempfile::tempdir().expect("fixture directory");
    let directory_path = directory.path().canonicalize().expect("canonical fixture");
    let path = directory_path.join("original.sock");
    let socket = std::os::unix::net::UnixListener::bind(&path).expect("fixture listener");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
        .expect("private socket");
    let before = std::fs::metadata(&path).expect("socket metadata");
    let parent_mode = std::fs::metadata(&directory_path)
        .expect("directory metadata")
        .mode();
    let mut listener = UnixListener::from_inherited(OwnedFd::from(socket), &path).expect("adopt");
    let mut client = UnixStream::connect(&path).await.expect("connect");
    let mut accepted = listener.accept().await.expect("accept");
    accepted
        .ensure_current_user_peer()
        .expect("actual owner peer");
    client.write_all(b"original").await.expect("write");
    let mut bytes = [0; 8];
    accepted.read_exact(&mut bytes).await.expect("read");
    assert_eq!(&bytes, b"original");
    drop(listener);
    let after = std::fs::metadata(&path).expect("owner still has socket path");
    assert_eq!(
        (before.dev(), before.ino(), before.mode()),
        (after.dev(), after.ino(), after.mode())
    );
    assert_eq!(
        std::fs::metadata(&directory_path)
            .expect("directory intact")
            .mode(),
        parent_mode
    );
}

#[tokio::test]
async fn adoption_rejects_other_path_and_nonprivate_node_without_changing_either() {
    let directory = tempfile::tempdir().expect("fixture directory");
    let directory_path = directory.path().canonicalize().expect("canonical fixture");
    let path = directory_path.join("original.sock");
    let other = directory_path.join("other.sock");
    let socket = std::os::unix::net::UnixListener::bind(&path).expect("fixture listener");
    let other_socket = std::os::unix::net::UnixListener::bind(&other).expect("other listener");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
        .expect("private socket");
    std::fs::set_permissions(&other, std::fs::Permissions::from_mode(0o600))
        .expect("private other");
    assert!(UnixListener::from_inherited(OwnedFd::from(socket), &other).is_err());
    assert_eq!(
        std::os::unix::net::UnixStream::connect(&path)
            .expect_err("refused adoption closes the held descriptor")
            .kind(),
        std::io::ErrorKind::ConnectionRefused
    );
    std::fs::set_permissions(&other, std::fs::Permissions::from_mode(0o660))
        .expect("shared fixture");
    assert!(UnixListener::from_inherited(OwnedFd::from(other_socket), &other).is_err());
    assert_eq!(
        std::os::unix::net::UnixStream::connect(&other)
            .expect_err("nonprivate adoption closes the held descriptor")
            .kind(),
        std::io::ErrorKind::ConnectionRefused
    );
    assert!(path.exists());
    assert_eq!(
        std::fs::metadata(&other).expect("node retained").mode() & 0o7777,
        0o660
    );
}

#[tokio::test]
async fn adoption_rejects_connected_socket_before_using_a_path() {
    let (socket, mut peer) = std::os::unix::net::UnixStream::pair().expect("socket pair");
    let error =
        UnixListener::from_inherited(OwnedFd::from(socket), std::path::Path::new("/unused"))
            .err()
            .expect("a connected stream is not a listener");
    assert_eq!(error.kind(), std::io::ErrorKind::InvalidInput);
    peer.set_read_timeout(Some(Duration::from_secs(1)))
        .expect("bounded closure observation");
    let mut byte = [0];
    assert_eq!(
        peer.read(&mut byte).expect("rejected descriptor is closed"),
        0
    );
}

#[tokio::test]
async fn adoption_rejects_other_socket_families_and_kinds_before_using_a_path() {
    let directory = tempfile::tempdir().expect("fixture directory");
    let path = directory.path().join("unchanged-file");
    std::fs::write(&path, b"unchanged").expect("owned path marker");
    let tcp = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))
        .expect("owned TCP listener");
    let datagram = std::os::unix::net::UnixDatagram::unbound().expect("owned Unix datagram");
    for socket in [OwnedFd::from(tcp), OwnedFd::from(datagram)] {
        let error = UnixListener::from_inherited(socket, &path)
            .err()
            .expect("only a listening Unix stream socket can be adopted");
        assert_eq!(error.kind(), std::io::ErrorKind::InvalidInput);
    }
    assert_eq!(std::fs::read(path).expect("marker retained"), b"unchanged");
}

const CLOEXEC_TEST: &str = "inherited::tests::adoption_restores_cloexec_before_child_exec";
const CLOEXEC_MODE: &str = "CODEX_UDS_CLOEXEC_TEST_MODE";
const CLOEXEC_ROOT: &str = "CODEX_UDS_CLOEXEC_TEST_ROOT";
const CLOEXEC_FD: &str = "CODEX_UDS_CLOEXEC_TEST_FD";
const CLOEXEC_IDENTITY: &str = "CODEX_UDS_CLOEXEC_TEST_IDENTITY";

struct OwnedExec(Option<Child>);

impl Drop for OwnedExec {
    fn drop(&mut self) {
        if let Some(child) = self.0.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn exec_command(root: &Path, fd: i32, identity: &Path, mode: &str) -> Command {
    let mut command = Command::new(std::env::current_exe().expect("actual test executable"));
    command
        .args(["--exact", CLOEXEC_TEST, "--nocapture", "--test-threads=1"])
        .env(CLOEXEC_MODE, mode)
        .env(CLOEXEC_ROOT, root)
        .env(CLOEXEC_FD, fd.to_string())
        .env(CLOEXEC_IDENTITY, identity);
    let parent_pid = std::process::id() as libc::pid_t;
    // The creating thread synchronously owns and waits for this exact child.
    // Each fork clears PDEATHSIG, so also protect the inner exec probes if the
    // adopting child is killed at its deadline. This test performs no credential
    // transition and re-execs the same ordinary test binary.
    // SAFETY: the post-fork closure performs only fixed Linux system calls and
    // constructs raw OS errors, without allocation, locks or environment access.
    unsafe {
        command.pre_exec(move || {
            if libc::prctl(
                libc::PR_SET_PDEATHSIG,
                libc::SIGKILL as libc::c_ulong,
                0 as libc::c_ulong,
                0 as libc::c_ulong,
                0 as libc::c_ulong,
            ) != 0
            {
                return Err(std::io::Error::last_os_error());
            }
            // Cover parent-process death before the signal was installed.
            if libc::getppid() != parent_pid {
                return Err(std::io::Error::from_raw_os_error(libc::ESRCH));
            }
            Ok(())
        });
    }
    command
}

fn run_owned_exec(mut command: Command, root: &Path, stage: &str) -> std::io::Result<()> {
    let stdout = root.join(format!("{stage}.stdout"));
    let stderr = root.join(format!("{stage}.stderr"));
    command
        .stdout(Stdio::from(std::fs::File::create(&stdout)?))
        .stderr(Stdio::from(std::fs::File::create(&stderr)?));
    let mut owned = OwnedExec(Some(command.spawn()?));
    let budget = if stage == "adopt" { 30 } else { 10 };
    let deadline = Instant::now() + Duration::from_secs(budget);
    loop {
        let child = owned
            .0
            .as_mut()
            .expect("owned process remains until reaped");
        if let Some(status) = child.try_wait()? {
            owned.0.take();
            if status.success() {
                eprintln!(
                    "owned exec {stage} completed with {status}; stdout: {}; stderr: {}",
                    std::fs::read_to_string(&stdout)?,
                    std::fs::read_to_string(&stderr)?,
                );
                return Ok(());
            }
            return Err(std::io::Error::other(format!(
                "{stage} failed with {status}; stdout: {}; stderr: {}",
                std::fs::read_to_string(&stdout)?,
                std::fs::read_to_string(&stderr)?,
            )));
        }
        if Instant::now() >= deadline {
            return Err(std::io::Error::new(
                std::io::ErrorKind::TimedOut,
                format!("owned {stage} process did not finish"),
            ));
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn cloexec_child(mode: &str) -> std::io::Result<()> {
    let root = PathBuf::from(std::env::var_os(CLOEXEC_ROOT).expect("owned root"));
    let identity = PathBuf::from(std::env::var_os(CLOEXEC_IDENTITY).expect("socket identity"));
    let fd: i32 = std::env::var(CLOEXEC_FD)
        .expect("owned fd")
        .parse()
        .expect("fd number");
    assert!(fd >= 3);
    if mode == "before-exec" || mode == "after-exec" {
        let observed = match std::fs::read_link(format!("/proc/self/fd/{fd}")) {
            Ok(target) => target == identity,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
            Err(error) => return Err(error),
        };
        eprintln!("actual exec probe {mode}: original_listener_present={observed}");
        let observed_bytes: &[u8] = if observed { b"present\n" } else { b"absent\n" };
        std::fs::write(root.join(mode), observed_bytes)?;
        assert_eq!(observed, mode == "before-exec");
        return Ok(());
    }
    assert_eq!(mode, "adopt");
    assert_eq!(std::fs::read_link(format!("/proc/self/fd/{fd}"))?, identity);
    // SAFETY: this child exclusively takes the descriptor transferred by the
    // parent's post-fork pre_exec hook; no Rust owner exists in this process.
    let socket = unsafe { OwnedFd::from_raw_fd(fd) };
    // SAFETY: socket owns the live descriptor.
    let flags_before = unsafe { libc::fcntl(socket.as_raw_fd(), libc::F_GETFD) };
    assert!(flags_before >= 0);
    assert_eq!(flags_before & libc::FD_CLOEXEC, 0);
    run_owned_exec(
        exec_command(&root, fd, &identity, "before-exec"),
        &root,
        "before",
    )?;
    assert_eq!(std::fs::read(root.join("before-exec"))?, b"present\n");

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let _entered = runtime.enter();
    let adopted = UnixListener::from_inherited(socket, &root.join("original.sock"))?;
    // SAFETY: adopted retains the same descriptor through both observations
    // and the subsequent real exec. Tokio/Mio's from_std does not duplicate it.
    let flags_after = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    assert!(flags_after >= 0);
    eprintln!("after adoption: fd_flags_before={flags_before}, fd_flags_after={flags_after}");
    // Run the actual exec even if the flag is wrong, so the negative control
    // observes a real leaked listener rather than only a numeric flag mismatch.
    run_owned_exec(
        exec_command(&root, fd, &identity, "after-exec"),
        &root,
        "after",
    )?;
    assert_eq!(std::fs::read(root.join("after-exec"))?, b"absent\n");
    assert_eq!(flags_after, flags_before | libc::FD_CLOEXEC);
    drop(adopted);
    std::fs::write(root.join("adoption-complete"), b"checked\n")?;
    Ok(())
}

#[test]
fn adoption_restores_cloexec_before_child_exec() -> std::io::Result<()> {
    match std::env::var(CLOEXEC_MODE) {
        Ok(mode) => return cloexec_child(&mode),
        Err(std::env::VarError::NotPresent) => {}
        Err(error) => panic!("invalid owned exec mode: {error}"),
    }
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let path = root.join("original.sock");
    let socket = std::os::unix::net::UnixListener::bind(&path)?;
    socket.set_nonblocking(false)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let fd = socket.as_raw_fd();
    let identity = std::fs::read_link(format!("/proc/self/fd/{fd}"))?;
    // SAFETY: socket owns this descriptor for the entire parent observation.
    let parent_flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    assert!(parent_flags >= 0);
    assert!(parent_flags & libc::FD_CLOEXEC != 0);
    let mut command = exec_command(&root, fd, &identity, "adopt");
    // SAFETY: only async-signal-safe fcntl calls execute after fork. Clearing
    // the child's descriptor flag cannot leak this listener from other tests
    // concurrently executing in the parent libtest process.
    unsafe {
        command.pre_exec(move || {
            let flags = libc::fcntl(fd, libc::F_GETFD);
            if flags < 0 || libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) != 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    run_owned_exec(command, &root, "adopt")?;
    assert_eq!(std::fs::read(root.join("adoption-complete"))?, b"checked\n");
    assert_eq!(std::fs::read(root.join("before-exec"))?, b"present\n");
    assert_eq!(std::fs::read(root.join("after-exec"))?, b"absent\n");
    // FD_CLOEXEC is per descriptor; O_NONBLOCK belongs to the shared open-file
    // description and the adopted child changes that flag in this parent too.
    // SAFETY: the parent still owns socket, so both flag queries use a live descriptor.
    let (descriptor_flags, status_flags) = unsafe {
        (
            libc::fcntl(fd, libc::F_GETFD),
            libc::fcntl(fd, libc::F_GETFL),
        )
    };
    assert_eq!(descriptor_flags, parent_flags);
    assert!(status_flags >= 0);
    assert!(status_flags & libc::O_NONBLOCK != 0);
    Ok(())
}
