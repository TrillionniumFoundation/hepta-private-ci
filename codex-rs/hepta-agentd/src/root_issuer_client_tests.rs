//! Socket/pidfd protocol fixtures; no deployed Root or signature qualification.
use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::thread;

fn body() -> AuthBusObjectiveBody {
    AuthBusObjectiveBody {
        spawn_generation: 1,
        run_id: "notes-original-run".into(),
        objective_revision: 1,
        source_envelope_json: "{\"text\":\"你好\"}".into(),
        runtime_body_digest: "11".repeat(32),
        preference_state_digest: "22".repeat(32),
        model_tuple_digest: "33".repeat(32),
        prompt_registry_digest: "44".repeat(32),
        artifact_set_digest: "55".repeat(32),
        authority_epoch: 1,
    }
}

fn signed(body: AuthBusObjectiveBody) -> AuthBusObjectiveIngress {
    AuthBusObjectiveIngress {
        issuer_id: "protocol-fixture-only".into(),
        key_epoch: 1,
        message_id: "fixture:objective:1:2".into(),
        sequence: 2,
        expires_at_ms: 60_000,
        signature_hex: "11".repeat(64),
        body,
    }
}

fn pidfd(pid: u32) -> OwnedFd {
    rustix::process::pidfd_open(
        rustix::process::Pid::from_raw(pid as i32).unwrap(),
        rustix::process::PidfdFlags::empty(),
    )
    .unwrap()
}

fn fixture(lifetime: Duration) -> (AgentdUnixFinalUseGrantProvider, UnixStream) {
    let (client, server) = UnixStream::pair().unwrap();
    let provider = AgentdUnixFinalUseGrantProvider::protected_stream(
        client,
        std::process::id(),
        pidfd(std::process::id()),
        Duration::from_millis(500),
        lifetime,
        rustix::process::geteuid().as_raw(),
    )
    .unwrap();
    (provider, server)
}

fn read(stream: &mut UnixStream) -> serde_json::Value {
    let mut length = [0; 4];
    stream.read_exact(&mut length).unwrap();
    let mut bytes = vec![0; u32::from_be_bytes(length) as usize];
    stream.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

fn send(stream: &mut UnixStream, reply: serde_json::Value) {
    let bytes = serde_json::to_vec(&reply).unwrap();
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    stream.write_all(&bytes).unwrap();
}

#[test]
fn root_issuer_preserves_typed_objective_then_original_final_use_on_one_lane() {
    let (provider, mut server) = fixture(Duration::from_secs(3));
    let expected = signed(body());
    let reply = expected.clone();
    let binding = FinalUseBinding {
        subject_id: "original-agent".into(),
        destination_id: "original-notes".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let expected_binding = binding.clone();
    let server = thread::spawn(move || {
        assert_eq!(
            read(&mut server),
            json!({"schema_version":1,"operation":SIGN_OBJECTIVE,"body":body()})
        );
        send(
            &mut server,
            json!({"schema_version":1,"operation":SIGNED_OBJECTIVE,"ingress":reply}),
        );
        assert_eq!(
            read(&mut server),
            json!({"schema_version":1,"operation":OPERATION,"binding":expected_binding})
        );
        send(
            &mut server,
            json!({"schema_version":1,"revocations":{"authority_epoch":1,"revision":1,"revoked_grant_ids":[]},"grant":null,"denial_reason":"explicit denial"}),
        );
    });
    assert_eq!(provider.sign_objective(&body()).unwrap(), expected);
    assert_eq!(
        provider.request_grant(&binding),
        Err(AgentdFinalUseIssuerError::Denied)
    );
    server.join().unwrap();
}

#[test]
fn root_issuer_wrong_body_or_extra_field_permanently_closes_both_operations() {
    for extra in [false, true] {
        let (provider, mut server) = fixture(Duration::from_secs(3));
        let server = thread::spawn(move || {
            read(&mut server);
            let mut ingress = signed(body());
            if !extra {
                ingress.body.source_envelope_json.push(' ');
            }
            let mut reply =
                json!({"schema_version":1,"operation":SIGNED_OBJECTIVE,"ingress":ingress});
            if extra {
                reply["new_permission"] = json!(true);
            }
            send(&mut server, reply);
        });
        assert_eq!(
            provider.sign_objective(&body()),
            Err(AgentdFinalUseIssuerError::MalformedResponse)
        );
        assert_eq!(
            provider.sign_objective(&body()),
            Err(AgentdFinalUseIssuerError::ChannelClosed)
        );
        server.join().unwrap();
    }
}

#[test]
fn root_issuer_lifetime_is_absolute_and_lost_ack_never_reopens() {
    let (provider, mut server) = fixture(Duration::from_millis(80));
    let server = thread::spawn(move || {
        read(&mut server);
        thread::sleep(Duration::from_millis(150));
    });
    let before = Instant::now();
    assert_eq!(
        provider.sign_objective(&body()),
        Err(AgentdFinalUseIssuerError::DeadlineElapsed)
    );
    assert!(before.elapsed() < Duration::from_millis(300));
    assert_eq!(
        provider.sign_objective(&body()),
        Err(AgentdFinalUseIssuerError::ChannelClosed)
    );
    server.join().unwrap();
}

#[test]
fn root_issuer_legacy_constructor_cannot_request_signing_or_bypass_uid_zero() {
    let (client, mut server) = UnixStream::pair().unwrap();
    let provider = AgentdUnixFinalUseGrantProvider::from_stream(
        client,
        AgentdFinalUseIssuerPeer {
            uid: rustix::process::geteuid().as_raw(),
            pid: std::process::id(),
        },
        Duration::from_millis(100),
    )
    .unwrap();
    assert_eq!(
        provider.sign_objective(&body()),
        Err(AgentdFinalUseIssuerError::InvalidConfiguration)
    );
    drop(provider);
    assert_eq!(server.read(&mut [0; 1]).unwrap(), 0);
    if rustix::process::geteuid().as_raw() != 0 {
        let (client, _) = UnixStream::pair().unwrap();
        assert!(
            AgentdUnixFinalUseGrantProvider::from_root_stream(
                client,
                std::process::id(),
                pidfd(std::process::id()),
                Duration::from_millis(100),
                Duration::from_secs(1),
            )
            .is_err()
        );
    }
}

#[test]
fn root_issuer_dead_original_process_cannot_authorize_inherited_stream_reply() {
    use std::io::BufRead;
    use std::io::BufReader;
    use std::process::Command;
    use std::process::Stdio;
    let temporary = tempfile::tempdir().unwrap();
    let socket = temporary.path().join("issuer.sock");
    let reply = serde_json::to_string(
        &json!({"schema_version":1,"operation":SIGNED_OBJECTIVE,"ingress":signed(body())}),
    )
    .unwrap();
    let mut child = Command::new("python3")
        .arg("-c")
        .arg("import socket,sys,os,time,struct\ns=socket.socket(socket.AF_UNIX);s.bind(sys.argv[1]);s.listen(1);print('ready',flush=True)\nc,_=s.accept()\ndef take(n):\n b=b''\n while len(b)<n:b+=c.recv(n-len(b))\n return b\ntake(struct.unpack('>I',take(4))[0])\nif os.fork():os._exit(0)\ntime.sleep(.15);r=sys.argv[2].encode();c.sendall(struct.pack('>I',len(r))+r);os._exit(0)")
        .arg(&socket)
        .arg(reply)
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let held = pidfd(child.id());
    let mut ready = String::new();
    BufReader::new(child.stdout.take().unwrap())
        .read_line(&mut ready)
        .unwrap();
    assert_eq!(ready, "ready\n");
    let provider = AgentdUnixFinalUseGrantProvider::protected_stream(
        UnixStream::connect(&socket).unwrap(),
        child.id(),
        held,
        Duration::from_millis(500),
        Duration::from_secs(3),
        rustix::process::geteuid().as_raw(),
    )
    .unwrap();
    assert_eq!(
        provider.sign_objective(&body()),
        Err(AgentdFinalUseIssuerError::PeerDenied)
    );
    assert!(child.wait().unwrap().success());
    assert_eq!(
        provider.sign_objective(&body()),
        Err(AgentdFinalUseIssuerError::ChannelClosed)
    );
}
