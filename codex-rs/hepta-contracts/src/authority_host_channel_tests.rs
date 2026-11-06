use super::*;
use pretty_assertions::assert_eq;
use std::process::Stdio;

#[test]
fn idle_may_exceed_frame_timeout_but_partial_frame_cannot() {
    let fixture = Fixture::new();
    fixture.authorize();
    let (server, mut client) = UnixStream::pair().unwrap();
    let mut policy = policy(&fixture, std::process::id());
    policy.timeout = Duration::from_millis(100);
    policy.lifetime = Duration::from_secs(3);
    let mut session = HostIssuerSession::from_stream(
        server,
        policy,
        owner_pidfd(std::process::id()),
        Arc::new(fixture.issuer),
        fixture.leases.verifier(),
    )
    .unwrap();
    let peer = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(200));
        let denied = wire_exchange(
            &mut client,
            &FinalUseBinding {
                scope_sha256: [9; 32],
                ..binding()
            },
        );
        assert_eq!(denied["denial_reason"], "authorization_denied");
        client.write_all(&[0]).unwrap();
        std::thread::sleep(Duration::from_millis(300));
    });
    assert_eq!(session.serve_next(), Ok(true));
    let start = Instant::now();
    assert_eq!(
        session.serve_next(),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    assert!(start.elapsed() < Duration::from_secs(1));
    peer.join().unwrap();
}

#[test]
fn a_complete_exchange_does_not_reset_the_hard_lifetime() {
    let fixture = Fixture::new();
    fixture.authorize();
    let (server, mut client) = UnixStream::pair().unwrap();
    let mut policy = policy(&fixture, std::process::id());
    policy.lifetime = Duration::from_millis(300);
    let mut session = HostIssuerSession::from_stream(
        server,
        policy,
        owner_pidfd(std::process::id()),
        Arc::new(fixture.issuer),
        fixture.leases.verifier(),
    )
    .unwrap();
    let peer = std::thread::spawn(move || {
        wire_exchange(
            &mut client,
            &FinalUseBinding {
                scope_sha256: [9; 32],
                ..binding()
            },
        );
        std::thread::sleep(Duration::from_millis(500));
    });
    assert_eq!(session.serve_next(), Ok(true));
    let start = Instant::now();
    assert_eq!(
        session.serve_next(),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    assert!(start.elapsed() < Duration::from_secs(1));
    peer.join().unwrap();
}

#[test]
fn arbitrary_descriptor_is_not_an_owner_lifecycle_handle() {
    let fixture = Fixture::new();
    let (server, _client) = UnixStream::pair().unwrap();
    let file = std::fs::File::open("/dev/null").unwrap();
    assert!(matches!(
        HostIssuerSession::from_stream(
            server,
            policy(&fixture, std::process::id()),
            file.into(),
            Arc::new(fixture.issuer),
            fixture.leases.verifier()
        ),
        Err(HostIssuerTransportError::InvalidConfiguration)
    ));
}

#[test]
#[ignore = "controlled process-lifecycle fixture, launched by its parent test"]
#[expect(
    clippy::zombie_processes,
    reason = "the parent test is a subreaper and explicitly waits for this inherited descendant after the original owner exits"
)]
fn inherited_channel_process_child() {
    let socket = std::env::var_os("HEPTA_OWNER_TEST_SOCKET").unwrap();
    let ready = std::env::var_os("HEPTA_OWNER_TEST_READY").unwrap();
    let stop = std::env::var_os("HEPTA_OWNER_TEST_STOP").unwrap();
    let stream = UnixStream::connect(socket).unwrap();
    // A bounded ordinary descendant keeps the descriptor open after this owner
    // exits. The fixture exercises lifecycle revocation without issuing a grant.
    let descendant = Command::new("/usr/bin/sleep")
        .arg("3")
        .stdin(Stdio::from(std::os::fd::OwnedFd::from(stream)))
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    std::fs::write(ready, descendant.id().to_string()).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while !Path::new(&stop).exists() {
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[test]
fn owner_exit_ends_idle_session_even_while_descendant_keeps_the_stream_open() {
    struct Subreaper(Option<rustix::process::Pid>);
    impl Drop for Subreaper {
        fn drop(&mut self) {
            rustix::process::set_child_subreaper(self.0).unwrap();
        }
    }
    let _subreaper = Subreaper(rustix::process::child_subreaper().unwrap());
    rustix::process::set_child_subreaper(rustix::process::Pid::from_raw(1)).unwrap();
    let fixture = Fixture::new();
    let socket = fixture._directory.path().join("lifecycle.sock");
    let ready = fixture._directory.path().join("ready");
    let stop = fixture._directory.path().join("stop");
    let listener = UnixListener::bind(&socket).unwrap();
    let mut child = Command::new(std::env::current_exe().unwrap()).args([
        "--exact", "authority_host_store::tests::issuer_tests::transport_tests::channel_tests::inherited_channel_process_child", "--ignored"])
        .env("HEPTA_OWNER_TEST_SOCKET", &socket).env("HEPTA_OWNER_TEST_READY", &ready)
        .env("HEPTA_OWNER_TEST_STOP", &stop).spawn().unwrap();
    let owner = owner_pidfd(child.id());
    let stream = accept_child(&listener, &mut child);
    let mut session = HostIssuerSession::from_stream(
        stream,
        policy(&fixture, child.id()),
        owner,
        Arc::new(fixture.issuer),
        fixture.leases.verifier(),
    )
    .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while !ready.exists() {
        assert!(Instant::now() < deadline);
        std::thread::sleep(Duration::from_millis(5));
    }
    let descendant: u32 = std::fs::read_to_string(&ready).unwrap().parse().unwrap();
    let descendant_pid = rustix::process::Pid::from_raw(descendant as i32).unwrap();
    let descendant = owner_pidfd(descendant);
    let trigger = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(100));
        std::fs::write(stop, "exit").unwrap();
    });
    let start = Instant::now();
    assert_eq!(
        session.serve_next(),
        Err(HostIssuerTransportError::PeerDenied)
    );
    assert!(start.elapsed() < Duration::from_secs(1));
    assert!(child.wait().unwrap().success());
    trigger.join().unwrap();
    let mut descriptors = [rustix::event::PollFd::new(
        &descendant,
        rustix::event::PollFlags::IN,
    )];
    assert_eq!(
        rustix::event::poll(&mut descriptors, Some(&rustix::event::Timespec::default())).unwrap(),
        0,
        "descendant must still hold the connected descriptor when owner exit is rejected"
    );
    let timeout = rustix::event::Timespec::try_from(Duration::from_secs(5)).unwrap();
    assert_eq!(
        rustix::event::poll(&mut descriptors, Some(&timeout)).unwrap(),
        1
    );
    let (_, status) =
        rustix::process::waitpid(Some(descendant_pid), rustix::process::WaitOptions::empty())
            .unwrap()
            .unwrap();
    assert_eq!(status.exit_status(), Some(0));
}
