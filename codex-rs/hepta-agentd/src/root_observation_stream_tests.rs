//! Same-UID private fixtures; these do not claim a deployed root service.
use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::fd::FromRawFd;

fn fixture(timeout: Duration) -> (RootObservationStream, UnixStream) {
    let (client, server) = UnixStream::pair().unwrap();
    let pid = std::process::id();
    let uid = unsafe { libc::geteuid() };
    (
        RootObservationStream::from_stream_for_uid(
            client,
            identity_for(pid),
            pidfd_for(pid),
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
    assert_eq!(client.diagnostics().first(), None);
    peer.join().unwrap();
}
#[tokio::test]
async fn cancelled_original_exchange_discards_late_reply_and_stays_closed() {
    let (client, mut server) = fixture(Duration::from_millis(400));
    let (received, request_received) = tokio::sync::oneshot::channel();
    let (release, released) = std::sync::mpsc::channel();
    let peer = std::thread::spawn(move || {
        read_request(&mut server);
        received.send(()).unwrap();
        let _ = released.recv();
        let _ = server.write_all(&[0, 0, 0, 2, b'4', b'2']);
    });
    {
        let request = request();
        let read = client.read::<u64>(&request);
        tokio::pin!(read);
        tokio::select! {
            result = &mut read => panic!("exchange finished before cancellation: {result:?}"),
            received = request_received => received.unwrap(),
        }
    }
    let first = client.diagnostics().first().unwrap();
    assert_eq!(first.stage, "stream_read_cancelled");
    assert!(first.duration_ns.is_some());
    assert!(client.read::<u64>(&request()).await.is_err());
    assert_eq!(client.diagnostics().first(), Some(first));
    release.send(()).unwrap();
    peer.join().unwrap();
}
#[tokio::test]
async fn malformed_oversized_and_partial_frames_permanently_close_the_lane() {
    for (scenario, stage) in [
        (0, "stream_response_malformed"),
        (1, "stream_response_length"),
        (2, "stream_read_timeout"),
        (3, "stream_response_prefix_read"),
        (4, "stream_response_body_read"),
    ] {
        let timeout = Duration::from_millis(if scenario == 2 { 40 } else { 500 });
        let (client, mut server) = fixture(timeout);
        let (release, released) = std::sync::mpsc::channel::<()>();
        let peer = std::thread::spawn(move || {
            read_request(&mut server);
            match scenario {
                0 => reply(&mut server, b"[]"),
                1 => server.write_all(&16_385u32.to_be_bytes()).unwrap(),
                2 => {
                    server.write_all(&[0, 0]).unwrap();
                    let _ = released.recv();
                }
                3 => {}
                4 => server.write_all(&[0, 0, 0, 2, b'4']).unwrap(),
                _ => unreachable!(),
            }
        });
        assert!(client.read::<u64>(&request()).await.is_err());
        let first = client.diagnostics().first().unwrap();
        assert_eq!(first.stage, stage);
        assert_eq!(first.os_error, None);
        assert_eq!(
            first.io_error_kind,
            if scenario >= 3 {
                Some(std::io::ErrorKind::UnexpectedEof)
            } else {
                None
            }
        );
        assert!(first.duration_ns.is_some());
        if scenario == 2 {
            assert!(u128::from(first.duration_ns.unwrap()) >= timeout.as_nanos());
        }
        assert!(client.read::<u64>(&request()).await.is_err());
        assert_eq!(client.diagnostics().first(), Some(first));
        drop(release);
        peer.join().unwrap();
    }
}

fn identity_for(pid: u32) -> AgentdRootAuthorityPeer {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
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
    let first = client.diagnostics().first().unwrap();
    assert_eq!(first.stage, "stream_read_lifetime_before");
    assert_eq!(first.poll_result, Some(1));
    assert_ne!(first.poll_revents.unwrap() & libc::POLLIN, 0);
    assert_eq!(first.os_error, None);
    assert_eq!(first.io_error_kind, None);
    assert!(client.read::<u64>(&request()).await.is_err());
    assert_eq!(client.diagnostics().first(), Some(first));
}
