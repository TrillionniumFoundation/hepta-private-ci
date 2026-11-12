use super::*;
use pretty_assertions::assert_eq;

// These remain same-UID framing components, not a Root deployment or grant.
fn client_until(end: Instant) -> (RootFinalUseFrontierClient, UnixStream) {
    let (stream, server) = UnixStream::pair().unwrap();
    let client = RootFinalUseFrontierClient::from_stream_for_uid_until(
        stream,
        "original".into(),
        identity(),
        pidfd(),
        Duration::from_secs(5),
        end,
        rustix::process::getuid().as_raw(),
    )
    .unwrap();
    assert_eq!(client.root.end(), end);
    (client, server)
}

fn after_original_end(end: Instant) {
    std::thread::sleep(end.saturating_duration_since(Instant::now()) + Duration::from_millis(1));
}

#[test]
fn absolute_frontier_end_keeps_original_framing_and_exact_end() {
    let end = Instant::now() + Duration::from_secs(60);
    let (client, mut server) = client_until(end);
    let worker = std::thread::spawn(move || {
        assert_eq!(
            receive(&mut server),
            json!({"schema_version":1,"operation":"runtime.final_use.frontier.load.v1","request_id":1})
        );
        send(&mut server, response(1, "ack", Some(frontier(1))));
    });
    assert_eq!(client.load("original"), Ok(frontier(1)));
    assert_eq!(client.root.end(), end);
    worker.join().unwrap();
}

#[test]
fn absolute_frontier_end_refuses_expired_request_without_rearm() {
    let end = Instant::now() + Duration::from_secs(2);
    let (client, mut server) = client_until(end);
    after_original_end(end);
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_closed(&mut server);
    assert_eq!(
        client.load("original"),
        Err(AuthorityTrustError::Unavailable)
    );
}

#[test]
fn absolute_frontier_lost_ack_does_not_resend_the_operation() {
    let end = Instant::now() + Duration::from_secs(60);
    let (client, mut server) = client_until(end);
    let worker = std::thread::spawn(move || {
        let request = receive(&mut server);
        assert_eq!(request["request_id"], 1);
        assert_eq!(request["expected"], json!(frontier(1)));
        assert_eq!(request["next"], json!(frontier(2)));
        server.shutdown(Shutdown::Write).unwrap();
        assert_closed(&mut server);
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
    worker.join().unwrap();
}

#[test]
fn absolute_frontier_constructor_keeps_root_incarnation_and_pidfd_guards() {
    if rustix::process::getuid().as_raw() != 0 {
        let (stream, mut server) = UnixStream::pair().unwrap();
        assert_eq!(
            RootFinalUseFrontierClient::from_stream_until(
                stream,
                "original".into(),
                identity(),
                pidfd(),
                Duration::from_secs(1),
                Instant::now() + Duration::from_secs(60),
            )
            .err(),
            Some(AuthorityTrustError::Invalid)
        );
        assert_closed(&mut server);
    }
    for (field, expected) in [
        ("boot", AuthorityTrustError::Invalid),
        ("start", AuthorityTrustError::Invalid),
        ("pid", AuthorityTrustError::Unavailable),
    ] {
        let (stream, mut server) = UnixStream::pair().unwrap();
        let mut peer = identity();
        match field {
            "boot" => peer.boot_id = "wrong".into(),
            "start" => peer.process_start_ticks += 1,
            "pid" => peer.pid += 1,
            _ => unreachable!(),
        }
        assert_eq!(
            RootFinalUseFrontierClient::from_stream_for_uid_until(
                stream,
                "original".into(),
                peer,
                pidfd(),
                Duration::from_secs(1),
                Instant::now() + Duration::from_secs(60),
                rustix::process::getuid().as_raw(),
            )
            .err(),
            Some(expected)
        );
        assert_closed(&mut server);
    }
    for end in [Instant::now(), Instant::now() + Duration::from_secs(3600)] {
        let (stream, mut server) = UnixStream::pair().unwrap();
        assert_eq!(
            RootFinalUseFrontierClient::from_stream_for_uid_until(
                stream,
                "original".into(),
                identity(),
                pidfd(),
                Duration::from_secs(1),
                end,
                rustix::process::getuid().as_raw(),
            )
            .err(),
            Some(AuthorityTrustError::Unavailable)
        );
        assert_closed(&mut server);
    }
}
