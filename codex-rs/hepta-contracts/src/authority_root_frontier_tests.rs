use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::io::Read;
use std::io::Write;
use std::sync::Arc;
use std::sync::mpsc;

fn identity() -> RootPeerIdentity {
    let pid = std::process::id();
    RootPeerIdentity {
        pid,
        boot_id: bounded_text("/proc/sys/kernel/random/boot_id", 128)
            .unwrap()
            .trim()
            .into(),
        process_start_ticks: bounded_text(&format!("/proc/{pid}/stat"), 8192)
            .unwrap()
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
    rustix::process::pidfd_open(
        rustix::process::getpid(),
        rustix::process::PidfdFlags::empty(),
    )
    .unwrap()
}

// Same-UID socketpair fixtures test framing only, never root deployment.
fn client(timeout: Duration) -> (RootFinalUseFrontierClient, UnixStream) {
    let (stream, server) = UnixStream::pair().unwrap();
    let client = RootFinalUseFrontierClient::from_stream_for_uid(
        stream,
        "original".into(),
        identity(),
        pidfd(),
        timeout,
        Duration::from_secs(5),
        rustix::process::getuid().as_raw(),
    )
    .unwrap();
    (client, server)
}

fn frontier(value: u8) -> FinalUseFrontier {
    FinalUseFrontier {
        authority_epoch: 2,
        revocation_revision: 7,
        state_sha256: [value; 32],
    }
}

fn receive(stream: &mut UnixStream) -> Value {
    let mut prefix = [0; 4];
    stream.read_exact(&mut prefix).unwrap();
    let mut bytes = vec![0; u32::from_be_bytes(prefix) as usize];
    stream.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

fn send(stream: &mut UnixStream, response: Value) {
    let bytes = serde_json::to_vec(&response).unwrap();
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    stream.write_all(&bytes).unwrap();
}

fn response(id: u64, status: &str, frontier: Option<FinalUseFrontier>) -> Value {
    json!({"schema_version":1,"request_id":id,"status":status,"frontier":frontier})
}

fn assert_closed(stream: &mut UnixStream) {
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    assert_eq!(stream.read(&mut [0]).unwrap(), 0);
}

#[test]
fn exact_original_load_cas_and_conflict_keep_order_without_automatic_retry() {
    let (client, mut server) = client(Duration::from_secs(2));
    let worker = std::thread::spawn(move || {
        assert_eq!(
            receive(&mut server),
            json!({"schema_version":1,"operation":"runtime.final_use.frontier.load.v1","request_id":1})
        );
        send(&mut server, response(1, "ack", Some(frontier(1))));
        for (id, status, current) in [(2, "ack", frontier(2)), (3, "conflict", frontier(2))] {
            assert_eq!(
                receive(&mut server),
                json!({"schema_version":1,"operation":"runtime.final_use.frontier.cas.v1","request_id":id,"expected":frontier(1),"next":frontier(2)})
            );
            send(&mut server, response(id, status, Some(current)));
        }
        assert_eq!(receive(&mut server)["request_id"], 4);
        send(&mut server, response(4, "ack", Some(frontier(2))));
    });
    assert_eq!(client.load("original"), Ok(frontier(1)));
    assert_eq!(
        client.compare_and_set("original", &frontier(1), &frontier(2)),
        Ok(())
    );
    assert_eq!(
        client.compare_and_set("original", &frontier(1), &frontier(2)),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(client.load("original"), Ok(frontier(2)));
    worker.join().unwrap();
}

#[test]
fn lost_ack_after_remote_commit_is_permanently_unavailable() {
    let (client, mut server) = client(Duration::from_secs(2));
    let worker = std::thread::spawn(move || {
        let request = receive(&mut server);
        assert_eq!(request["expected"], json!(frontier(1)));
        let committed: FinalUseFrontier = serde_json::from_value(request["next"].clone()).unwrap();
        server.shutdown(Shutdown::Write).unwrap(); // commit happened; ACK was lost
        assert_closed(&mut server);
        committed
    });
    assert_eq!(
        client.compare_and_set("original", &frontier(1), &frontier(2)),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(
        client.compare_and_set("original", &frontier(1), &frontier(2)),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(worker.join().unwrap(), frontier(2));
}

#[test]
fn invalid_or_unknown_ack_never_reopens_the_lane() {
    let mut extra = response(1, "ack", Some(frontier(2)));
    extra["reset"] = json!(true);
    for reply in [
        response(2, "ack", Some(frontier(2))),
        response(1, "unknown", None),
        response(1, "ack", None),
        response(1, "ack", Some(frontier(3))),
        extra,
    ] {
        let (client, mut server) = client(Duration::from_secs(2));
        let worker = std::thread::spawn(move || {
            receive(&mut server);
            send(&mut server, reply);
            assert_closed(&mut server);
        });
        assert_eq!(
            client.compare_and_set("original", &frontier(1), &frontier(2)),
            Err(AuthorityTrustError::Unavailable)
        );
        assert_eq!(
            client.load("original"),
            Err(AuthorityTrustError::Unavailable)
        );
        worker.join().unwrap();
    }
}

#[test]
fn partial_or_oversize_response_closes_without_another_request() {
    for bytes in [
        vec![0, 0],
        16_385u32.to_be_bytes().to_vec(),
        0u32.to_be_bytes().to_vec(),
        vec![0, 0, 0, 9, b'{'],
    ] {
        let (client, mut server) = client(Duration::from_secs(2));
        let worker = std::thread::spawn(move || {
            receive(&mut server);
            server.write_all(&bytes).unwrap();
            server.shutdown(Shutdown::Write).unwrap();
            assert_closed(&mut server);
        });
        assert_eq!(
            client.load("original"),
            Err(AuthorityTrustError::Unavailable)
        );
        assert_eq!(
            client.load("original"),
            Err(AuthorityTrustError::Unavailable)
        );
        worker.join().unwrap();
    }
}

#[test]
fn total_timeout_closes_without_replaying_a_waiting_operation() {
    let (client, mut server) = client(Duration::from_millis(100));
    let worker = std::thread::spawn(move || {
        receive(&mut server);
        assert_closed(&mut server); // no ACK, no new request ID
    });
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
    worker.join().unwrap();
}

#[test]
fn owner_mismatch_emits_nothing_and_concurrent_calls_never_interleave() {
    let (client, mut server) = client(Duration::from_secs(2));
    assert_eq!(client.load("other"), Err(AuthorityTrustError::Invalid));
    let client = Arc::new(client);
    let original = Arc::clone(&client);
    let (received, ready) = mpsc::sync_channel(1);
    let (release, wait) = mpsc::sync_channel(1);
    let peer = std::thread::spawn(move || {
        assert_eq!(receive(&mut server)["request_id"], 1);
        received.send(()).unwrap();
        wait.recv_timeout(Duration::from_secs(2)).unwrap();
        send(&mut server, response(1, "ack", Some(frontier(1))));
    });
    let worker = std::thread::spawn(move || original.load("original"));
    ready.recv_timeout(Duration::from_secs(2)).unwrap();
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
    release.send(()).unwrap();
    assert_eq!(worker.join().unwrap(), Ok(frontier(1)));
    peer.join().unwrap();
}

#[test]
fn exhausted_request_counter_closes_before_writing() {
    let (client, mut server) = client(Duration::from_secs(2));
    client
        .channel
        .lock()
        .unwrap()
        .as_mut()
        .unwrap()
        .next_request_id = u64::MAX;
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_closed(&mut server);
}

#[test]
fn public_constructor_requires_root_and_exact_preheld_process_identity() {
    let (stream, mut server) = UnixStream::pair().unwrap();
    if rustix::process::getuid().as_raw() != 0 {
        assert!(
            RootFinalUseFrontierClient::from_stream(
                stream,
                "original".into(),
                identity(),
                pidfd(),
                Duration::from_secs(1),
                Duration::from_secs(3)
            )
            .is_err()
        );
        assert_closed(&mut server);
    }
    for field in ["boot", "start", "pid"] {
        let (stream, mut server) = UnixStream::pair().unwrap();
        let mut peer = identity();
        match field {
            "boot" => peer.boot_id = "wrong".into(),
            "start" => peer.process_start_ticks += 1,
            "pid" => peer.pid += 1,
            _ => unreachable!(),
        }
        assert!(
            RootFinalUseFrontierClient::from_stream_for_uid(
                stream,
                "original".into(),
                peer,
                pidfd(),
                Duration::from_secs(1),
                Duration::from_secs(3),
                rustix::process::getuid().as_raw()
            )
            .is_err()
        );
        assert_closed(&mut server);
    }
}
