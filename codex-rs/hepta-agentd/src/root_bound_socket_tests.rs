use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::unix::process::CommandExt;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

const CHILD: &str = "root_bound_socket::tests::original_root_bound_listener_child";
const OWNER: u32 = 60001;

#[test]
fn refuses_shared_or_aliased_parent_without_creating_a_rendezvous() {
    let directory = tempfile::tempdir().expect("fixture directory");
    let path = directory.path().join("unused.sock");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o777)).expect("shared fixture parent");
    // A private descendant cannot repair shared writes in its parent chain.
    assert!(require_root_parent(&path).is_err());
    assert!(!path.exists());
}

#[test]
#[ignore = "explicit actual Root fixture, held descriptors and dedicated-UID child"]
fn original_root_bound_listener_preserves_peer_identity_and_path_custody() {
    // SAFETY: geteuid only reads this fixture process's identity.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_SOCKET_TEST_ROOT")
        .expect("explicit isolated Root-owned, non-shared parent required");
    let directory = tempfile::tempdir_in(parent).expect("Root fixture directory");
    let name = std::ffi::CString::new(directory.path().as_os_str().as_bytes()).expect("fixture path");
    // SAFETY: the fixture owns this fresh directory, not any production root.
    assert_eq!(unsafe { libc::chown(name.as_ptr(), 0, OWNER) }, 0);
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o2750)).expect("fixture peer traversal");
    let path = directory.path().join("original.sock");
    let premature = directory.path().join("premature.sock");
    let wrong = directory.path().join("wrong.sock");
    let socket = bind_root_agentd_socket(&path, OWNER, OWNER).expect("Root binds only");
    let early = bind_root_agentd_socket(&premature, OWNER, OWNER).expect("negative Root binding");
    let other = bind_root_agentd_socket(&wrong, OWNER, OWNER).expect("wrong-path negative binding");
    assert!(std::os::unix::net::UnixStream::connect(&path).is_err());
    assert!(bind_root_agentd_socket(&path, OWNER, OWNER).is_err());
    // SAFETY: this intentional negative descriptor must fail in the child.
    assert_eq!(unsafe { libc::listen(early.as_raw_fd(), 8) }, 0);
    let before = std::fs::metadata(&path).expect("original node");
    let parent_before = std::fs::metadata(directory.path()).expect("Root parent");
    let descriptors = [socket.as_raw_fd(), early.as_raw_fd(), other.as_raw_fd()];
    // Pin the exact already-built executable so the child need not traverse a
    // developer-owned source/target parent after dropping to its fixture UID.
    let executable = File::open(std::env::current_exe().expect("same test executable")).expect("retain actual test executable");
    let inherited = [descriptors[0], descriptors[1], descriptors[2], executable.as_raw_fd()];
    let mut command = Command::new("/usr/bin/setpriv");
    command.args(["--reuid=60001", "--regid=60001", "--clear-groups", "--no-new-privs",
        "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all"])
        .arg(format!("/proc/self/fd/{}", executable.as_raw_fd()))
        .args(["--exact", CHILD, "--ignored", "--nocapture", "--test-threads=1"])
        .env_clear().env("PATH", "/usr/bin:/bin")
        .env("HEPTA_SOCKET_CHILD_PATH", &path)
        .env("HEPTA_SOCKET_CHILD_PREMATURE", &premature)
        .env("HEPTA_SOCKET_CHILD_FDS", descriptors.map(|fd| fd.to_string()).join(","))
        .current_dir("/").stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::piped());
    // SAFETY: the post-fork/pre-exec closure uses only fcntl on held descriptor
    // numbers. Actual credential dropping occurs in the original setpriv tool.
    unsafe { command.pre_exec(move || {
        for fd in inherited {
            let flags = libc::fcntl(fd, libc::F_GETFD);
            if flags < 0 || libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0 {
                return Err(io::Error::last_os_error());
            }
        }
        Ok(())
    }); }
    let mut child = command.spawn().expect("dedicated-owner fixture child");
    let end = Instant::now() + Duration::from_secs(10);
    let mut client = loop {
        match std::os::unix::net::UnixStream::connect(&path) {
            Ok(client) => break client,
            Err(error) if error.kind() == io::ErrorKind::ConnectionRefused && Instant::now() < end => {
                if let Some(status) = child.try_wait().expect("poll child") { panic!("child exited before listen: {status}"); }
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(error) => panic!("actual child never listened: {error}"),
        }
    };
    let mut peer: libc::ucred = unsafe { std::mem::zeroed() };
    let mut length = std::mem::size_of_val(&peer) as libc::socklen_t;
    // SAFETY: the connected stream and correctly sized credential buffer live.
    assert_eq!(unsafe { libc::getsockopt(client.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PEERCRED,
        std::ptr::from_mut(&mut peer).cast(), &mut length) }, 0);
    assert_eq!((peer.pid as u32, peer.uid, peer.gid), (child.id(), OWNER, OWNER));
    client.set_read_timeout(Some(Duration::from_secs(5))).expect("read bound");
    client.set_write_timeout(Some(Duration::from_secs(5))).expect("write bound");
    client.write_all(b"fixture").expect("fixture request");
    let mut response = [0; 7];
    client.read_exact(&mut response).expect("fixture reply");
    assert_eq!(&response, b"fixture");
    let output = child.wait_with_output().expect("collect child");
    assert!(output.status.success(), "stdout={} stderr={}", String::from_utf8_lossy(&output.stdout), String::from_utf8_lossy(&output.stderr));
    let after = std::fs::metadata(&path).expect("Root keeps socket node");
    assert_eq!((after.dev(), after.ino(), after.uid(), after.gid(), after.mode()), (before.dev(), before.ino(), before.uid(), before.gid(), before.mode()));
    let parent_after = std::fs::metadata(directory.path()).expect("Root keeps directory");
    assert_eq!((parent_after.uid(), parent_after.gid(), parent_after.mode()), (parent_before.uid(), parent_before.gid(), parent_before.mode()));
    println!("ROOT_BOUND_LISTENER actual_server_uid=60001 actual_server_gid=60001 actual_server_pid={} root_path_unchanged=true root_listening_rejected=true wrong_path_rejected=true", peer.pid);
}

#[test]
#[ignore = "only the explicit Root socket test supplies these inherited descriptors"]
fn original_root_bound_listener_child() {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), OWNER, OWNER).expect("actual zero-capability peer");
    let path = std::path::PathBuf::from(std::env::var_os("HEPTA_SOCKET_CHILD_PATH").expect("fixture path"));
    let premature = std::path::PathBuf::from(std::env::var_os("HEPTA_SOCKET_CHILD_PREMATURE").expect("negative path"));
    let numbers: Vec<i32> = std::env::var("HEPTA_SOCKET_CHILD_FDS").expect("held fixture fds").split(',').map(|value| value.parse().expect("fd number")).collect();
    assert_eq!(numbers.len(), 3);
    assert!(numbers.iter().all(|fd| *fd >= 3));
    assert!(numbers[0] != numbers[1] && numbers[1] != numbers[2] && numbers[0] != numbers[2]);
    // SAFETY: the trusted fixture passed these distinct held descriptors once.
    let [socket, early, other] = unsafe { [OwnedFd::from_raw_fd(numbers[0]), OwnedFd::from_raw_fd(numbers[1]), OwnedFd::from_raw_fd(numbers[2])] };
    assert!(listen_root_bound_socket(early, &premature).is_err());
    assert!(listen_root_bound_socket(other, &path).is_err());
    let socket = listen_root_bound_socket(socket, &path).expect("listen as final actual owner");
    assert!(listen_root_bound_socket(socket.try_clone().expect("retained negative duplicate"), &path).is_err());
    assert_eq!(std::fs::remove_file(&path).expect_err("peer cannot remove Root rendezvous").kind(), io::ErrorKind::PermissionDenied);
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().expect("fixture runtime after credential drop");
    runtime.block_on(async {
        use tokio::io::AsyncReadExt;
        use tokio::io::AsyncWriteExt;
        let mut listener = codex_uds::UnixListener::from_inherited(socket, &path).expect("adopt original listener");
        tokio::time::timeout(Duration::from_secs(10), async {
            let mut stream = listener.accept().await.expect("fixture connection");
            assert!(stream.ensure_current_user_peer().is_err());
            stream.ensure_current_user_or_root_peer().expect("original actual Root supervisor remains admitted");
            let mut bytes = [0; 7];
            stream.read_exact(&mut bytes).await.expect("fixture request");
            stream.write_all(&bytes).await.expect("fixture reply");
        }).await.expect("bounded fixture exchange");
    });
}
