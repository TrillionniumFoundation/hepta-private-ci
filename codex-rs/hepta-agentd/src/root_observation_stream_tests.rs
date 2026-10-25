//! Same-UID private fixtures; these do not claim a deployed root service.
use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::fd::FromRawFd;

fn fixture(timeout: Duration) -> (RootObservationStream, UnixStream) {
    let (client, server) = UnixStream::pair().unwrap();
    let pid = std::process::id();
    let stat = bounded_text(&format!("/proc/{pid}/stat"), 8192).unwrap();
    let peer = AgentdRootAuthorityPeer {
        pid,
        boot_id: bounded_text("/proc/sys/kernel/random/boot_id", 128)
            .unwrap()
            .trim()
            .into(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .unwrap()
            .1
            .split_whitespace()
            .nth(19)
            .unwrap()
            .parse()
            .unwrap(),
    };
    // SAFETY: live test PID and zero flags create a new exclusively owned fd.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(fd >= 0);
    let pidfd = unsafe { OwnedFd::from_raw_fd(fd as i32) };
    let uid = unsafe { libc::geteuid() };
    (
        RootObservationStream::from_stream_for_uid(
            client,
            peer,
            pidfd,
            timeout,
            Duration::from_secs(10),
            uid,
        )
        .unwrap(),
        server,
    )
}
fn request() -> crate::HostAuthorityObservationRequestV2 {
    crate::HostAuthorityObservationRequestV2 {
        schema_version: 2,
        operation: crate::HOST_AUTHORITY_OBSERVATION_V2.into(),
    }
}
fn read_request(server: &mut UnixStream) {
    server
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    let mut prefix = [0; 4];
    server.read_exact(&mut prefix).unwrap();
    let mut bytes = vec![0; u32::from_be_bytes(prefix) as usize];
    server.read_exact(&mut bytes).unwrap();
    assert_eq!(bytes, serde_json::to_vec(&request()).unwrap());
}
fn reply(server: &mut UnixStream, bytes: &[u8]) {
    server
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    server.write_all(bytes).unwrap();
}
#[tokio::test]
async fn original_fixed_stream_accepts_bounded_reads_without_reconnect() {
    let (client, mut server) = fixture(Duration::from_millis(100));
    let peer = std::thread::spawn(move || {
        for _ in 0..2 {
            read_request(&mut server);
            reply(&mut server, b"42");
        }
    });
    assert_eq!(client.read::<u64>(&request()).await.unwrap(), 42);
    assert_eq!(client.read::<u64>(&request()).await.unwrap(), 42);
    peer.join().unwrap();
}
#[tokio::test]
async fn cancelled_original_exchange_discards_late_reply_and_stays_closed() {
    let (client, mut server) = fixture(Duration::from_millis(400));
    let peer = std::thread::spawn(move || {
        read_request(&mut server);
        std::thread::sleep(Duration::from_millis(100));
        let _ = server.write_all(&[0, 0, 0, 2, b'4', b'2']);
    });
    assert!(
        tokio::time::timeout(Duration::from_millis(20), client.read::<u64>(&request()))
            .await
            .is_err()
    );
    assert!(client.read::<u64>(&request()).await.is_err());
    peer.join().unwrap();
}
#[tokio::test]
async fn malformed_oversized_and_partial_frames_permanently_close_the_lane() {
    for scenario in 0..3 {
        let (client, mut server) = fixture(Duration::from_millis(40));
        let peer = std::thread::spawn(move || {
            read_request(&mut server);
            match scenario {
                0 => reply(&mut server, b"[]"),
                1 => server.write_all(&16_385u32.to_be_bytes()).unwrap(),
                2 => {
                    server.write_all(&[0, 0]).unwrap();
                    std::thread::sleep(Duration::from_millis(100));
                }
                _ => unreachable!(),
            }
        });
        assert!(client.read::<u64>(&request()).await.is_err());
        assert!(client.read::<u64>(&request()).await.is_err());
        peer.join().unwrap();
    }
}

fn identity_for(pid: u32) -> AgentdRootAuthorityPeer {
    let stat = bounded_text(&format!("/proc/{pid}/stat"), 8192).unwrap();
    AgentdRootAuthorityPeer {
        pid,
        boot_id: bounded_text("/proc/sys/kernel/random/boot_id", 128)
            .unwrap()
            .trim()
            .into(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .unwrap()
            .1
            .split_whitespace()
            .nth(19)
            .unwrap()
            .parse()
            .unwrap(),
    }
}
fn pidfd_for(pid: u32) -> OwnedFd {
    // SAFETY: live fixture PID creates a new descriptor, owned exactly once.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(fd >= 0);
    unsafe { OwnedFd::from_raw_fd(fd as i32) }
}
#[tokio::test]
async fn production_uid_and_boot_start_identity_are_pinned_before_any_frame() {
    for invalid in 0..2 {
        let (client, _server) = UnixStream::pair().unwrap();
        let mut peer = identity_for(std::process::id());
        if invalid == 0 {
            peer.boot_id = "wrong-boot".into();
        } else {
            peer.process_start_ticks += 1;
        }
        assert!(
            RootObservationStream::from_stream_for_uid(
                client,
                peer,
                pidfd_for(std::process::id()),
                Duration::from_millis(100),
                Duration::from_secs(5),
                unsafe { libc::geteuid() }
            )
            .is_err()
        );
    }
    if unsafe { libc::geteuid() } != 0 {
        let (client, _server) = UnixStream::pair().unwrap();
        assert!(
            RootObservationStream::from_stream(
                client,
                identity_for(std::process::id()),
                pidfd_for(std::process::id()),
                Duration::from_millis(100),
                Duration::from_secs(5)
            )
            .is_err()
        );
    }
}
#[tokio::test]
async fn original_peer_death_refuses_before_inherited_socket_reaches_eof() {
    use std::io::BufRead;
    use std::process::Command;
    use std::process::Stdio;
    let directory = tempfile::tempdir().unwrap();
    let socket = directory.path().join("root-observation.sock");
    let script = r#"
import socket,subprocess,sys
listener=socket.socket(socket.AF_UNIX)
listener.bind(sys.argv[1]);listener.listen(1)
print('READY',flush=True)
stream,_=listener.accept()
if sys.stdin.buffer.read(1)!=b'X':sys.exit(0)
subprocess.Popen(['/bin/sleep','0.6'],pass_fds=(stream.fileno(),),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
"#;
    let mut child = Command::new("python3")
        .args(["-I", "-B", "-c", script])
        .arg(&socket)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let pinned = pidfd_for(child.id());
    let mut ready = String::new();
    std::io::BufReader::new(child.stdout.take().unwrap())
        .read_line(&mut ready)
        .unwrap();
    assert_eq!(ready, "READY\n");
    let client = RootObservationStream::from_stream_for_uid(
        UnixStream::connect(&socket).unwrap(),
        identity_for(child.id()),
        pinned,
        Duration::from_millis(400),
        Duration::from_secs(5),
        unsafe { libc::geteuid() },
    )
    .unwrap();
    child.stdin.take().unwrap().write_all(b"X").unwrap();
    assert!(child.wait().unwrap().success());
    let started = Instant::now();
    assert!(client.read::<u64>(&request()).await.is_err());
    assert!(started.elapsed() < Duration::from_millis(300));
    assert!(client.read::<u64>(&request()).await.is_err());
}
