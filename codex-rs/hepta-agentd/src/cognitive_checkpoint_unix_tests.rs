//! Explicit same-UID channel fixtures exercise the real client, not a deployed
//! root service, authority issuance, checkpoint CAS or durable publication.
use super::*;
use std::io::Write;
use std::os::fd::FromRawFd;

fn identity() -> AgentdCognitiveCheckpointPeer {
    let pid = std::process::id();
    let stat = bounded_text(&format!("/proc/{pid}/stat"), 8192).unwrap();
    AgentdCognitiveCheckpointPeer {
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

fn pidfd() -> OwnedFd {
    // SAFETY: pidfd_open with a live test PID and zero flags returns a fresh fd.
    let descriptor = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(descriptor >= 0);
    // SAFETY: the successful syscall returned sole descriptor ownership.
    unsafe { OwnedFd::from_raw_fd(descriptor as i32) }
}

fn fixture(timeout: Duration) -> (AgentdUnixCognitiveCheckpointTransport, UnixStream) {
    let (client, server) = UnixStream::pair().unwrap();
    // Explicit fixture-only UID. The public production constructor pins UID0.
    let uid = unsafe { libc::geteuid() };
    let transport = AgentdUnixCognitiveCheckpointTransport::from_stream_for_uid(
        client,
        identity(),
        pidfd(),
        timeout,
        Duration::from_secs(10),
        uid,
    )
    .unwrap();
    (transport, server)
}

fn request() -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "schema_version":1,"operation":"runtime.cognitive.checkpoint.v1",
        "request_id":"00000000000000010000000000000001","command":"read_head",
        "expected":null,"proposal":null,
    }))
    .unwrap()
}

fn read_request(server: &mut UnixStream) {
    server
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    let mut prefix = [0; 4];
    server.read_exact(&mut prefix).unwrap();
    let mut bytes = vec![0; u32::from_be_bytes(prefix) as usize];
    server.read_exact(&mut bytes).unwrap();
    assert_eq!(bytes, request());
}

fn response() -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "schema_version":1,"request_id":"00000000000000010000000000000001",
        "status":"refused","reason":"unavailable","token":null,"head":null,
    }))
    .unwrap()
}

#[tokio::test]
async fn exact_framing_keeps_a_complete_refusal_lane_usable_without_retrying() {
    let (transport, mut server) = fixture(Duration::from_secs(1));
    let peer = std::thread::spawn(move || {
        for _ in 0..2 {
            read_request(&mut server);
            let response = response();
            server
                .write_all(&(response.len() as u32).to_be_bytes())
                .unwrap();
            server.write_all(&response).unwrap();
        }
    });
    assert_eq!(transport.exchange(&request()).await.unwrap(), response());
    // Two explicit read calls, never an automatic retry of a failed mutation.
    assert_eq!(transport.exchange(&request()).await.unwrap(), response());
    peer.join().unwrap();
}

#[tokio::test]
async fn partial_frame_deadline_permanently_closes_the_original_stream() {
    let (transport, mut server) = fixture(Duration::from_millis(40));
    let peer = std::thread::spawn(move || {
        read_request(&mut server);
        server.write_all(&[0, 0]).unwrap();
        std::thread::sleep(Duration::from_millis(100));
        let _ = server.write_all(&[0, 1, b'{']);
    });
    let start = Instant::now();
    assert!(transport.exchange(&request()).await.is_err());
    assert!(start.elapsed() < Duration::from_secs(1));
    assert!(transport.exchange(&request()).await.is_err());
    peer.join().unwrap();
}

#[tokio::test]
async fn cancelling_an_exchange_discards_its_late_reply_and_cannot_rearm_the_lane() {
    let (transport, mut server) = fixture(Duration::from_secs(2));
    let peer = std::thread::spawn(move || {
        read_request(&mut server);
        std::thread::sleep(Duration::from_millis(120));
        let response = response();
        let _ = server.write_all(&(response.len() as u32).to_be_bytes());
        let _ = server.write_all(&response);
    });
    assert!(
        tokio::time::timeout(Duration::from_millis(40), transport.exchange(&request()))
            .await
            .is_err()
    );
    assert!(transport.exchange(&request()).await.is_err());
    peer.join().unwrap();
}

#[tokio::test]
async fn malformed_or_mismatched_reply_never_leaves_a_reusable_stream() {
    for raw in [
        Vec::new(),
        vec![b'x'; COGNITIVE_CHECKPOINT_FRAME_LIMIT + 1],
        b"{\"schema_version\":1}".to_vec(),
        String::from_utf8(response())
            .unwrap()
            .replace("00000001\"", "00000002\"")
            .into_bytes(),
    ] {
        let (transport, mut server) = fixture(Duration::from_secs(1));
        let peer = std::thread::spawn(move || {
            read_request(&mut server);
            server.write_all(&(raw.len() as u32).to_be_bytes()).unwrap();
            let _ = server.write_all(&raw);
        });
        assert!(transport.exchange(&request()).await.is_err());
        assert!(transport.exchange(&request()).await.is_err());
        peer.join().unwrap();
    }
}

#[tokio::test]
async fn invalid_request_is_refused_before_io_without_consuming_the_channel() {
    let (transport, mut server) = fixture(Duration::from_secs(1));
    assert!(transport.exchange(b"{}").await.is_err());
    assert!(
        transport
            .exchange(&vec![0; COGNITIVE_CHECKPOINT_FRAME_LIMIT + 1])
            .await
            .is_err()
    );
    let peer = std::thread::spawn(move || {
        read_request(&mut server);
        let response = response();
        server
            .write_all(&(response.len() as u32).to_be_bytes())
            .unwrap();
        server.write_all(&response).unwrap();
    });
    assert_eq!(transport.exchange(&request()).await.unwrap(), response());
    peer.join().unwrap();
}

#[tokio::test]
async fn bootstrap_rejects_wrong_lifetime_peer_and_non_pidfd_capabilities() {
    let uid = unsafe { libc::geteuid() };
    for mismatch in 0..4 {
        let (client, _server) = UnixStream::pair().unwrap();
        let mut peer = identity();
        if mismatch == 0 {
            peer.process_start_ticks += 1;
        }
        if mismatch == 1 {
            peer.boot_id = "0".repeat(36);
        }
        let descriptor = if mismatch == 2 {
            File::open("/dev/null").unwrap().into()
        } else {
            pidfd()
        };
        assert!(
            AgentdUnixCognitiveCheckpointTransport::from_stream_for_uid(
                client,
                peer,
                descriptor,
                Duration::from_secs(1),
                Duration::from_secs(2),
                if mismatch == 3 { uid + 1 } else { uid },
            )
            .is_err()
        );
    }
}
