use super::*;
use pretty_assertions::assert_eq;

// Real socket/pidfd transport components. The peer only returns a denial;
// these fixtures provide no Root deployment, signature or granted authority.
fn provider_until(end: Instant) -> (AgentdUnixFinalUseGrantProvider, UnixStream) {
    let (stream, server) = UnixStream::pair().unwrap();
    let provider = AgentdUnixFinalUseGrantProvider::protected_stream_until(
        stream,
        std::process::id(),
        pidfd(std::process::id()),
        Duration::from_secs(5),
        end,
        unsafe { libc::geteuid() },
    )
    .unwrap();
    assert_eq!(provider.protected_root.as_ref().unwrap().end, end);
    (provider, server)
}

fn binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "original-agent".into(),
        destination_id: "original-notes".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    }
}

fn assert_closed(stream: &mut UnixStream) {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    assert_eq!(stream.read(&mut [0; 1]).unwrap(), 0);
}

#[test]
fn absolute_root_issuer_end_keeps_original_request_and_denial() {
    let end = Instant::now() + Duration::from_secs(60);
    let (provider, mut server) = provider_until(end);
    let worker = thread::spawn(move || {
        for _ in 0..2 {
            assert_eq!(
                read(&mut server),
                json!({"schema_version":1,"operation":OPERATION,"binding":binding()})
            );
            send(
                &mut server,
                json!({"schema_version":1,"revocations":{"authority_epoch":1,"revision":1,"revoked_grant_ids":[]},"grant":null,"denial_reason":"explicit denial"}),
            );
        }
    });
    for _ in 0..2 {
        assert_eq!(
            provider.request_grant(&binding()),
            Err(AgentdFinalUseIssuerError::Denied)
        );
        assert_eq!(provider.protected_root.as_ref().unwrap().end, end);
    }
    worker.join().unwrap();
}

#[test]
fn absolute_root_issuer_end_refuses_late_request_without_rearm() {
    let end = Instant::now() + Duration::from_secs(2);
    let (provider, mut server) = provider_until(end);
    thread::sleep(end.saturating_duration_since(Instant::now()) + Duration::from_millis(1));
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::PeerDenied)
    );
    assert_closed(&mut server);
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::ChannelClosed)
    );
}

#[test]
fn absolute_root_issuer_lost_ack_closes_original_lane_without_resend() {
    let (provider, mut server) = provider_until(Instant::now() + Duration::from_secs(60));
    let worker = thread::spawn(move || {
        assert_eq!(
            read(&mut server),
            json!({"schema_version":1,"operation":OPERATION,"binding":binding()})
        );
        server.shutdown(Shutdown::Write).unwrap();
        assert_closed(&mut server);
    });
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::Unavailable)
    );
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::ChannelClosed)
    );
    worker.join().unwrap();
}

#[test]
fn absolute_root_issuer_constructor_keeps_uid_pidfd_and_end_guards() {
    if unsafe { libc::geteuid() } != 0 {
        let (stream, mut server) = UnixStream::pair().unwrap();
        assert_eq!(
            AgentdUnixFinalUseGrantProvider::from_root_stream_until(
                stream,
                std::process::id(),
                pidfd(std::process::id()),
                Duration::from_secs(1),
                Instant::now() + Duration::from_secs(60),
            )
            .err(),
            Some(AgentdFinalUseIssuerError::PeerDenied)
        );
        assert_closed(&mut server);
    }
    for (case, expected) in [
        ("pid", AgentdFinalUseIssuerError::PeerDenied),
        ("pidfd", AgentdFinalUseIssuerError::PeerDenied),
        ("timeout", AgentdFinalUseIssuerError::PeerDenied),
        ("expired", AgentdFinalUseIssuerError::DeadlineElapsed),
        ("too_far", AgentdFinalUseIssuerError::PeerDenied),
    ] {
        let (stream, mut server) = UnixStream::pair().unwrap();
        let root_pid = if case == "pid" {
            std::process::id() + 1
        } else {
            std::process::id()
        };
        let root_pidfd: OwnedFd = if case == "pidfd" {
            std::fs::File::open("/dev/null").unwrap().into()
        } else {
            pidfd(std::process::id())
        };
        let timeout = if case == "timeout" {
            Duration::ZERO
        } else {
            Duration::from_secs(1)
        };
        let end = match case {
            "expired" => Instant::now(),
            "too_far" => Instant::now() + Duration::from_secs(3600),
            _ => Instant::now() + Duration::from_secs(60),
        };
        assert_eq!(
            AgentdUnixFinalUseGrantProvider::protected_stream_until(
                stream,
                root_pid,
                root_pidfd,
                timeout,
                end,
                unsafe { libc::geteuid() },
            )
            .err(),
            Some(expected)
        );
        assert_closed(&mut server);
    }
}
