use super::*;
use crate::HostIssuerPeer;
use crate::HostIssuerSession;
use crate::HostIssuerSessionPolicy;
use crate::HostIssuerTransportError;
use pretty_assertions::assert_eq;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;

fn policy(fixture: &Fixture, pid: u32) -> HostIssuerSessionPolicy {
    HostIssuerSessionPolicy {
        peer: HostIssuerPeer {
            uid: rustix::process::geteuid().as_raw(),
            pid,
        },
        lease_id: "explicit-lease".into(),
        lease_revision: 1,
        revocations: fixture.authority.revocation_head().unwrap(),
        timeout: Duration::from_secs(5),
    }
}

fn binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "isolated-agent".into(),
        destination_id: "no-effect-test".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    }
}

fn accept_child(listener: &UnixListener, child: &mut std::process::Child) -> UnixStream {
    listener.set_nonblocking(true).unwrap();
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        match listener.accept() {
            Ok((stream, _)) => return stream,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                assert!(
                    child.try_wait().unwrap().is_none(),
                    "child exited before connecting"
                );
                assert!(Instant::now() < deadline, "child connection deadline");
                std::thread::sleep(Duration::from_millis(5));
            }
            Err(error) => panic!("accept failed: {error}"),
        }
    }
}

fn wire_exchange(stream: &mut UnixStream, binding: &FinalUseBinding) -> serde_json::Value {
    let bytes = serde_json::to_vec(&serde_json::json!({ "schema_version": 1,
        "operation": "runtime.agentd.production_operation", "binding": binding }))
    .unwrap();
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    stream.write_all(&bytes).unwrap();
    let mut length = [0; 4];
    stream.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!(length > 0 && length <= 64 * 1024);
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

#[test]
#[ignore = "subprocess entry called only by the bounded parent test"]
fn issuer_wire_process_child() {
    let socket = std::env::var_os("HEPTA_HOST_AUTHORITY_TEST_SOCKET").unwrap();
    let response = std::env::var_os("HEPTA_HOST_AUTHORITY_TEST_RESPONSE").unwrap();
    if let Some(protected) = std::env::var_os("HEPTA_HOST_AUTHORITY_TEST_PROTECTED") {
        assert_ne!(rustix::process::geteuid().as_raw(), 0);
        assert!(RootAuthorityDirectory::open(Path::new(&protected)).is_err());
        assert_eq!(
            std::fs::read_dir(protected).unwrap_err().kind(),
            std::io::ErrorKind::PermissionDenied
        );
        assert!(rustix::process::getgroups().unwrap().is_empty());
        let status = std::fs::read_to_string("/proc/self/status").unwrap();
        assert!(status.lines().any(|line| line == "NoNewPrivs:\t1"));
    }
    let mut stream = UnixStream::connect(socket).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .unwrap();
    stream
        .set_write_timeout(Some(Duration::from_secs(10)))
        .unwrap();
    let denied = wire_exchange(
        &mut stream,
        &FinalUseBinding {
            scope_sha256: [9; 32],
            ..binding()
        },
    );
    assert_eq!(denied["grant"], serde_json::Value::Null);
    assert_eq!(denied["denial_reason"], "authorization_denied");
    let accepted = wire_exchange(&mut stream, &binding());
    assert_eq!(accepted["schema_version"], 1);
    assert_eq!(accepted["denial_reason"], serde_json::Value::Null);
    std::fs::write(response, serde_json::to_vec(&accepted["grant"]).unwrap()).unwrap();
}

#[test]
fn actual_process_peer_and_original_wire_produce_a_verifiable_grant_after_denial() {
    let fixture = Fixture::new();
    fixture.authorize();
    let socket = fixture._directory.path().join("issuer.sock");
    let response = fixture._directory.path().join("response.json");
    let listener = UnixListener::bind(&socket).unwrap();
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "authority_host_store::tests::issuer_tests::transport_tests::issuer_wire_process_child",
            "--ignored",
        ])
        .env("HEPTA_HOST_AUTHORITY_TEST_SOCKET", &socket)
        .env("HEPTA_HOST_AUTHORITY_TEST_RESPONSE", &response)
        .spawn()
        .unwrap();
    let stream = accept_child(&listener, &mut child);
    let policy = policy(&fixture, child.id());
    let mut session = HostIssuerSession::from_stream(
        stream,
        policy,
        Arc::new(fixture.issuer),
        fixture.leases.verifier(),
    )
    .unwrap();
    assert_eq!(session.serve_next(), Ok(true));
    assert_eq!(session.serve_next(), Ok(true));
    assert_eq!(session.serve_next(), Ok(false));
    assert!(child.wait().unwrap().success());
    let grant: SignedFinalUseGrant =
        serde_json::from_slice(&std::fs::read(response).unwrap()).unwrap();
    fixture.authority.claim(&grant, &binding()).unwrap();
}

#[test]
fn mismatched_process_is_rejected_before_reading_or_issuing() {
    let fixture = Fixture::new();
    fixture.authorize();
    let (server, _client) = UnixStream::pair().unwrap();
    let policy = policy(&fixture, std::process::id() + 1);
    assert!(matches!(
        HostIssuerSession::from_stream(
            server,
            policy,
            Arc::new(fixture.issuer),
            fixture.leases.verifier()
        ),
        Err(HostIssuerTransportError::PeerDenied)
    ));
}

#[test]
fn bounded_frame_error_and_normal_idle_deadline_close_the_channel() {
    for oversized in [false, true] {
        let fixture = Fixture::new();
        fixture.authorize();
        let (server, mut client) = UnixStream::pair().unwrap();
        let mut policy = policy(&fixture, std::process::id());
        policy.timeout = Duration::from_millis(100);
        let mut session = HostIssuerSession::from_stream(
            server,
            policy,
            Arc::new(fixture.issuer),
            fixture.leases.verifier(),
        )
        .unwrap();
        if oversized {
            client
                .write_all(&(16_u32 * 1024 + 1).to_be_bytes())
                .unwrap();
        }
        let start = Instant::now();
        assert_eq!(
            session.serve_next(),
            Err(if oversized {
                HostIssuerTransportError::InvalidRequest
            } else {
                HostIssuerTransportError::DeadlineElapsed
            })
        );
        assert!(start.elapsed() < Duration::from_secs(2));
        assert_eq!(session.serve_next(), Err(HostIssuerTransportError::Closed));
    }
}

#[test]
#[ignore = "explicit root-only host qualification, spawns configured unprivileged UID"]
fn root_directory_and_actual_unprivileged_process_isolation() {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    let uid: u32 = std::env::var("HEPTA_HOST_AUTHORITY_QUALIFICATION_UID")
        .unwrap()
        .parse()
        .unwrap();
    assert_ne!(uid, 0);
    let state = tempfile::Builder::new()
        .prefix("hepta-authority-qualification-")
        .tempdir_in("/var/lib")
        .unwrap();
    std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = RootAuthorityDirectory::open(state.path()).unwrap();
    let fixture = Fixture::with_directory(state, root);
    fixture.authorize();
    let runtime = tempfile::Builder::new()
        .prefix("hepta-authority-qualification-")
        .tempdir_in("/run")
        .unwrap();
    std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o711)).unwrap();
    let socket = runtime.path().join("issuer.sock");
    let response_dir = tempfile::Builder::new()
        .prefix("hepta-authority-client-")
        .tempdir_in("/data")
        .unwrap();
    rustix::fs::chown(
        response_dir.path(),
        Some(rustix::process::Uid::from_raw(uid)),
        Some(rustix::process::Gid::from_raw(uid)),
    )
    .unwrap();
    let response = response_dir.path().join("response.json");
    let listener = UnixListener::bind(&socket).unwrap();
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o666)).unwrap();
    let mut child = Command::new("/usr/bin/setpriv")
        .args([
            "--reuid",
            &uid.to_string(),
            "--regid",
            &uid.to_string(),
            "--clear-groups",
            "--no-new-privs",
        ])
        .arg(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "authority_host_store::tests::issuer_tests::transport_tests::issuer_wire_process_child",
            "--ignored",
        ])
        .env("HEPTA_HOST_AUTHORITY_TEST_SOCKET", &socket)
        .env("HEPTA_HOST_AUTHORITY_TEST_RESPONSE", &response)
        .env(
            "HEPTA_HOST_AUTHORITY_TEST_PROTECTED",
            fixture._directory.path(),
        )
        .spawn()
        .unwrap();
    let stream = accept_child(&listener, &mut child);
    let actual = rustix::net::sockopt::socket_peercred(&stream).unwrap();
    assert_eq!(actual.uid.as_raw(), uid);
    assert_eq!(actual.pid.as_raw_nonzero().get() as u32, child.id());
    let mut policy = policy(&fixture, child.id());
    policy.peer.uid = uid;
    let mut session = HostIssuerSession::from_stream(
        stream,
        policy,
        Arc::new(fixture.issuer),
        fixture.leases.verifier(),
    )
    .unwrap();
    assert_eq!(session.serve_next(), Ok(true));
    assert_eq!(session.serve_next(), Ok(true));
    assert_eq!(session.serve_next(), Ok(false));
    assert!(child.wait().unwrap().success());
    let grant: SignedFinalUseGrant =
        serde_json::from_slice(&std::fs::read(response).unwrap()).unwrap();
    fixture.authority.claim(&grant, &binding()).unwrap();
    assert!(matches!(
        fixture.authority.claim(&grant, &binding()),
        Err(FinalUseError::AlreadyClaimed)
    ));
}
