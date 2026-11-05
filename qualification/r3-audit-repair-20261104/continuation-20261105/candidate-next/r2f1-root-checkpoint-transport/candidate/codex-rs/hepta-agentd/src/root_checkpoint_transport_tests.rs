//! Real local UDS/pidfd controls; the test UID and synthetic ACK are not Root admission.

use super::*;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;

const REQUEST: &str = r#"{"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1","request_id":"00000000000000070000000000000003","command":"read_head","expected":null,"proposal":null}"#;
const ACK: &str = r#"{
  "schema_version": 1, "request_id": "00000000000000070000000000000003", "status": "ack", "reason": null,
  "token": {"publisher_epoch":7,"counter":1,"head_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  "head": {
    "schema_version": 1, "owner_agent_id": "56d6489e-c050-4de0-ab29-61c2ea00d860",
    "publisher_epoch": 7, "counter": 1, "last_mutation_sequence": 2,
    "writer_binding": {"lease_id":"checkpoint-wire-fixture","generation":1,"authority_epoch":2,"owner_epoch":3,"authority_grant_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","fencing_token_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","expires_at_unix_seconds":1000},
    "peer_lifetime": {"uid":0,"pid":17,"boot_id":"fixture-boot","process_start_ticks":4},
    "phase": "current",
    "last_current": {"profile":"hepta:cognitive:exact-current-cut:v1","owner_agent_id":"56d6489e-c050-4de0-ab29-61c2ea00d860","schema_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","state_digest":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},
    "proposal": null, "last_request": null
  }
}"#;

fn fixture_identity() -> (AgentdRootCheckpointPeer, OwnedFd) {
    let pid = std::process::id();
    // SAFETY: pidfd_open takes a PID and zero flags, and returns a new owned FD.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(fd >= 0, "pidfd_open: {}", std::io::Error::last_os_error());
    let stat = std::fs::read_to_string("/proc/self/stat").unwrap();
    let peer = AgentdRootCheckpointPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id").unwrap().trim().to_owned(),
        process_start_ticks: stat.rsplit_once(") ").unwrap().1.split_whitespace().nth(19).unwrap().parse().unwrap(),
    };
    // SAFETY: the successful syscall returned a fresh FD, transferred exactly once.
    (peer, unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

fn fixture_bootstrap() -> (AgentdRootCheckpointBootstrap, UnixStream) {
    let (peer, root) = fixture_identity();
    let (stream, server) = UnixStream::pair().unwrap();
    // SAFETY: geteuid has no pointer arguments or ownership effects. Only this
    // private test fixture accepts the current UID; the public constructor uses 0.
    let uid = unsafe { libc::geteuid() };
    let bootstrap = AgentdRootCheckpointBootstrap::from_peer(
        stream, root, peer, Duration::from_secs(1), Duration::from_secs(30), uid,
    ).unwrap();
    (bootstrap, server)
}

async fn receive_request(server: &mut tokio::net::UnixStream) {
    let mut prefix = [0; 4];
    server.read_exact(&mut prefix).await.unwrap();
    assert_eq!(u32::from_be_bytes(prefix) as usize, REQUEST.len());
    let mut bytes = vec![0; REQUEST.len()];
    server.read_exact(&mut bytes).await.unwrap();
    assert_eq!(bytes, REQUEST.as_bytes());
}

#[test]
fn synchronous_custody_rejects_wrong_peer_and_closes_owned_socket() {
    // This synchronous control does not enter a Tokio runtime. Libtest itself
    // may have threads; this is not the ordinary single-thread launcher proof.
    #[derive(Debug)]
    enum Mismatch { Uid, Pid, Boot, Birth, NotPidfd }
    for mismatch in [Mismatch::Uid, Mismatch::Pid, Mismatch::Boot, Mismatch::Birth, Mismatch::NotPidfd] {
        let (mut peer, mut root) = fixture_identity();
        let (stream, mut server) = UnixStream::pair().unwrap();
        // SAFETY: geteuid has no pointer arguments or ownership effects.
        let mut uid = unsafe { libc::geteuid() };
        match mismatch {
            Mismatch::Uid => uid = uid.wrapping_add(1),
            Mismatch::Pid => peer.pid = if peer.pid == 1 { 2 } else { 1 },
            Mismatch::Boot => peer.boot_id.push('x'),
            Mismatch::Birth => peer.process_start_ticks += 1,
            Mismatch::NotPidfd => root = File::open("/dev/null").unwrap().into(),
        }
        assert!(matches!(AgentdRootCheckpointBootstrap::from_peer(
            stream, root, peer, Duration::from_secs(1), Duration::from_secs(30), uid,
        ), Err(Error::Refused)), "{mismatch:?}");
        server.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        assert_eq!(server.read(&mut [0]).unwrap(), 0, "{mismatch:?}");
    }
    let (peer, root) = fixture_identity();
    let (stream, mut server) = UnixStream::pair().unwrap();
    let public = AgentdRootCheckpointBootstrap::from_inherited(
        stream, root, peer, Duration::from_secs(1), Duration::from_secs(30),
    );
    // SAFETY: observe the real fixture credential, without changing it. A root
    // test process still does not establish independent Root/issuer authority.
    match unsafe { libc::geteuid() } {
        0 => assert!(public.is_ok()),
        _ => assert!(matches!(&public, Err(Error::Refused))),
    }
    drop(public);
    server.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    assert_eq!(server.read(&mut [0]).unwrap(), 0);
    let (bootstrap, mut server) = fixture_bootstrap();
    for fd in [bootstrap.stream.as_raw_fd(), bootstrap.root.as_raw_fd()] {
        // SAFETY: bootstrap owns each live descriptor during this observation.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        assert!(flags >= 0 && flags & libc::FD_CLOEXEC != 0);
    }
    drop(bootstrap);
    server.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    assert_eq!(server.read(&mut [0]).unwrap(), 0);
}

#[tokio::test]
async fn complete_ack_preserves_wire_bytes_and_wrong_request_closes_lane() {
    let (bootstrap, server) = fixture_bootstrap();
    let mut channel = bootstrap.into_runtime().unwrap();
    server.set_nonblocking(true).unwrap();
    let mut server = tokio::net::UnixStream::from_std(server).unwrap();
    let request: CognitiveCheckpointRequest = serde_json::from_str(REQUEST).unwrap();
    let client = async {
        assert_eq!(channel.exchange(&request).await.unwrap(), ACK.as_bytes());
        assert_eq!(channel.exchange(&request).await, Err(Error::Unavailable));
        assert_eq!(channel.exchange(&request).await, Err(Error::Unavailable));
    };
    let peer = async {
        for reply in [ACK.to_owned(), ACK.replacen("00000000000000070000000000000003", "00000000000000070000000000000004", /*count*/ 1)] {
            receive_request(&mut server).await;
            server.write_all(&(reply.len() as u32).to_be_bytes()).await.unwrap();
            server.write_all(reply.as_bytes()).await.unwrap();
        }
        assert_eq!(server.read(&mut [0]).await.unwrap(), 0);
    };
    tokio::time::timeout(Duration::from_secs(5), async { tokio::join!(client, peer); }).await.unwrap();
}

#[tokio::test]
async fn cancellation_after_real_request_closes_lane_without_reconnecting() {
    let (bootstrap, server) = fixture_bootstrap();
    let mut channel = bootstrap.into_runtime().unwrap();
    server.set_nonblocking(true).unwrap();
    let mut server = tokio::net::UnixStream::from_std(server).unwrap();
    let request: CognitiveCheckpointRequest = serde_json::from_str(REQUEST).unwrap();
    let mut exchange = Box::pin(channel.exchange(&request));
    tokio::time::timeout(Duration::from_secs(5), async {
        tokio::select! {
            result = &mut exchange => panic!("exchange ended before peer withheld response: {result:?}"),
            _ = receive_request(&mut server) => {}
        }
    }).await.unwrap();
    drop(exchange);
    assert_eq!(tokio::time::timeout(Duration::from_secs(1), server.read(&mut [0])).await.unwrap().unwrap(), 0);
    assert_eq!(channel.exchange(&request).await, Err(Error::Unavailable));
}

#[tokio::test]
async fn withheld_response_times_out_and_closes_lane() {
    let (bootstrap, server) = fixture_bootstrap();
    let mut channel = bootstrap.into_runtime().unwrap();
    server.set_nonblocking(true).unwrap();
    let mut server = tokio::net::UnixStream::from_std(server).unwrap();
    let request: CognitiveCheckpointRequest = serde_json::from_str(REQUEST).unwrap();
    let mut exchange = Box::pin(channel.exchange(&request));
    tokio::select! {
        result = &mut exchange => panic!("exchange ended before peer received request: {result:?}"),
        _ = receive_request(&mut server) => {}
    }
    assert_eq!(exchange.await, Err(Error::Unavailable));
    assert_eq!(tokio::time::timeout(Duration::from_secs(1), server.read(&mut [0])).await.unwrap().unwrap(), 0);
    assert_eq!(channel.exchange(&request).await, Err(Error::Unavailable));
}
