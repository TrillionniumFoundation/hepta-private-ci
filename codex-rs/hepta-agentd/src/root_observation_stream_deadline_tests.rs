use super::*;
use pretty_assertions::assert_eq;
use std::net::Shutdown;

// Same-UID framing components only. Numeric replies are not verified Root
// observations, signatures, grants or evidence of a deployed phase.
fn stream_until(end: Instant) -> (RootObservationStream, UnixStream) {
    let (stream, server) = UnixStream::pair().unwrap();
    let client = RootObservationStream::from_stream_for_uid_until(
        stream,
        identity_for(std::process::id()),
        pidfd_for(std::process::id()),
        Duration::from_millis(500),
        end,
        unsafe { libc::geteuid() },
    )
    .unwrap();
    assert_eq!(client.end, end);
    (client, server)
}

fn assert_closed(server: &mut UnixStream) {
    server
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    assert_eq!(server.read(&mut [0; 1]).unwrap(), 0);
}

#[tokio::test]
async fn absolute_root_observation_end_keeps_original_framing_and_end() {
    let end = Instant::now() + Duration::from_secs(60);
    let (client, mut server) = stream_until(end);
    let worker = std::thread::spawn(move || {
        for _ in 0..2 {
            read_request(&mut server);
            reply(&mut server, b"42");
        }
    });
    for _ in 0..2 {
        assert_eq!(client.read::<u64>(&request()).await, Ok(42));
        assert_eq!(client.end, end);
    }
    worker.join().unwrap();
}

#[tokio::test]
async fn absolute_root_observation_end_refuses_late_read_without_rearm() {
    let end = Instant::now() + Duration::from_secs(2);
    let (client, mut server) = stream_until(end);
    tokio::time::sleep_until(tokio::time::Instant::from_std(end + Duration::from_millis(1))).await;
    assert_eq!(
        client.read::<u64>(&request()).await,
        Err(AgentdRootAuthorityError::Unavailable)
    );
    assert_closed(&mut server);
    assert_eq!(
        client.read::<u64>(&request()).await,
        Err(AgentdRootAuthorityError::Unavailable)
    );
}

#[tokio::test]
async fn absolute_root_observation_lost_reply_closes_without_resend() {
    let (client, mut server) = stream_until(Instant::now() + Duration::from_secs(60));
    let worker = std::thread::spawn(move || {
        read_request(&mut server);
        server.shutdown(Shutdown::Write).unwrap();
        assert_closed(&mut server);
    });
    assert_eq!(
        client.read::<u64>(&request()).await,
        Err(AgentdRootAuthorityError::Unavailable)
    );
    assert_eq!(
        client.read::<u64>(&request()).await,
        Err(AgentdRootAuthorityError::Unavailable)
    );
    worker.join().unwrap();
}

#[tokio::test]
async fn absolute_root_observation_constructor_keeps_identity_and_bounds() {
    if unsafe { libc::geteuid() } != 0 {
        let (stream, mut server) = UnixStream::pair().unwrap();
        assert_eq!(
            RootObservationStream::from_stream_until(
                stream,
                identity_for(std::process::id()),
                pidfd_for(std::process::id()),
                Duration::from_millis(500),
                Instant::now() + Duration::from_secs(60),
            )
            .err(),
            Some(AgentdRootAuthorityError::Refused)
        );
        assert_closed(&mut server);
    }
    for case in [
        "pid",
        "boot",
        "start",
        "pidfd",
        "zero_timeout",
        "large_timeout",
        "expired",
        "too_far",
    ] {
        let (stream, mut server) = UnixStream::pair().unwrap();
        let mut peer = identity_for(std::process::id());
        match case {
            "pid" => peer.pid += 1,
            "boot" => peer.boot_id = "wrong".into(),
            "start" => peer.process_start_ticks += 1,
            _ => {}
        }
        let root_pidfd: OwnedFd = if case == "pidfd" {
            std::fs::File::open("/dev/null").unwrap().into()
        } else {
            pidfd_for(std::process::id())
        };
        let timeout = match case {
            "zero_timeout" => Duration::ZERO,
            "large_timeout" => Duration::from_millis(501),
            _ => Duration::from_millis(500),
        };
        let end = match case {
            "expired" => Instant::now(),
            "too_far" => Instant::now() + Duration::from_secs(3600),
            _ => Instant::now() + Duration::from_secs(60),
        };
        assert_eq!(
            RootObservationStream::from_stream_for_uid_until(
                stream,
                peer,
                root_pidfd,
                timeout,
                end,
                unsafe { libc::geteuid() },
            )
            .err(),
            Some(AgentdRootAuthorityError::Refused)
        );
        assert_closed(&mut server);
    }
}
