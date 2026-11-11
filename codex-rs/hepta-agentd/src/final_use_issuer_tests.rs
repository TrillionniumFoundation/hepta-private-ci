use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::collections::BTreeSet;
use std::sync::mpsc;
use std::thread;

fn binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "agent-one".into(),
        destination_id: "trill.notes:session:task:incarnation".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    }
}

fn peer() -> AgentdFinalUseIssuerPeer {
    // SAFETY: geteuid has no arguments or memory preconditions.
    AgentdFinalUseIssuerPeer {
        uid: unsafe { libc::geteuid() },
        pid: std::process::id(),
    }
}

fn fixture(timeout: Duration) -> (AgentdUnixFinalUseGrantProvider, UnixStream) {
    let (client, server) = UnixStream::pair().unwrap();
    server
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    server
        .set_write_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    (
        AgentdUnixFinalUseGrantProvider::from_stream(client, peer(), timeout).unwrap(),
        server,
    )
}

fn signed() -> SignedFinalUseGrant {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "isolated-test-issuer".into(),
        authority_epoch: 1,
        grant_id: "test-grant".into(),
        nonce: [7; 32],
        binding: binding(),
        not_before_unix_ms: now - 1_000,
        expires_at_unix_ms: now + 60_000,
    };
    // Test-only key; no provider or production configuration contains it.
    let signature = SigningKey::from_bytes(&[58; 32])
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn response(grant: SignedFinalUseGrant) -> serde_json::Value {
    json!({"schema_version":1, "grant":grant, "denial_reason":null,
        "revocations":{"authority_epoch":999, "revision":999, "revoked_grant_ids":["test-grant"]}})
}

fn read_request(stream: &mut UnixStream) {
    let mut length = [0; 4];
    stream.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!(length <= MAX_REQUEST_BYTES);
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes).unwrap();
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&bytes).unwrap(),
        json!({"schema_version":1, "operation":OPERATION, "binding":binding()})
    );
}

fn send_response(stream: &mut UnixStream, value: &serde_json::Value) {
    let bytes = serde_json::to_vec(value).unwrap();
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    stream.write_all(&bytes).unwrap();
}

#[test]
fn original_authority_verifies_grants_without_trusting_the_provider_head() {
    let (provider, mut server) = fixture(Duration::from_secs(1));
    let expected = signed();
    let reply = response(expected.clone());
    let server = thread::spawn(move || {
        read_request(&mut server);
        send_response(&mut server, &reply);
    });
    let received = provider.request_grant(&binding()).unwrap();
    assert_eq!(received, expected);
    server.join().unwrap();

    let directory = tempfile::tempdir().unwrap();
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "isolated-test-issuer".into(),
        SigningKey::from_bytes(&[58; 32]).verifying_key().to_bytes(),
        head.clone(),
    )
    .unwrap();
    let mut forged = received.clone();
    forged.signature[0] ^= 1;
    assert!(authority.claim(&forged, &binding()).is_err());
    assert_eq!(authority.revocation_head().unwrap(), head);
    let token = authority.claim(&received, &binding()).unwrap();
    assert!(token.enter(&binding()).is_ok());
    assert!(authority.claim(&received, &binding()).is_err());
}

#[test]
fn wrong_peer_and_unbounded_timeouts_fail_before_any_request() {
    for (expected, timeout, error) in [
        (
            AgentdFinalUseIssuerPeer {
                pid: peer().pid + 1,
                ..peer()
            },
            Duration::from_secs(1),
            AgentdFinalUseIssuerError::PeerDenied,
        ),
        (
            AgentdFinalUseIssuerPeer {
                uid: peer().uid + 1,
                ..peer()
            },
            Duration::from_secs(1),
            AgentdFinalUseIssuerError::PeerDenied,
        ),
        (
            peer(),
            Duration::ZERO,
            AgentdFinalUseIssuerError::InvalidConfiguration,
        ),
        (
            peer(),
            MAX_TIMEOUT + Duration::from_millis(1),
            AgentdFinalUseIssuerError::InvalidConfiguration,
        ),
    ] {
        let (client, mut server) = UnixStream::pair().unwrap();
        assert!(
            matches!(AgentdUnixFinalUseGrantProvider::from_stream(client, expected, timeout), Err(actual) if actual == error)
        );
        assert_eq!(server.read(&mut [0]).unwrap(), 0);
    }
}

#[test]
fn malformed_or_wrong_binding_responses_fence_the_channel_without_retry() {
    let good = response(signed());
    let mut wrong_binding = good.clone();
    wrong_binding["grant"]["grant"]["binding"]["subject_id"] = json!("another-agent");
    let mut unknown = good.clone();
    unknown["unexpected"] = json!(true);
    let mut schema = good.clone();
    schema["schema_version"] = json!(2);
    let mut both = good.clone();
    both["denial_reason"] = json!("deny");
    let mut short_signature = good;
    short_signature["grant"]["signature"] = json!([1, 2]);
    for (reply, expected) in [
        (wrong_binding, AgentdFinalUseIssuerError::BindingMismatch),
        (unknown, AgentdFinalUseIssuerError::MalformedResponse),
        (schema, AgentdFinalUseIssuerError::MalformedResponse),
        (both, AgentdFinalUseIssuerError::MalformedResponse),
        (short_signature, AgentdFinalUseIssuerError::InvalidGrant),
    ] {
        let (provider, mut server) = fixture(Duration::from_secs(1));
        let server = thread::spawn(move || {
            read_request(&mut server);
            send_response(&mut server, &reply);
            assert_eq!(server.read(&mut [0]).unwrap(), 0);
        });
        assert_eq!(provider.request_grant(&binding()), Err(expected));
        assert_eq!(
            provider.request_grant(&binding()),
            Err(AgentdFinalUseIssuerError::ChannelClosed)
        );
        server.join().unwrap();
    }
}

#[test]
fn oversized_and_empty_frames_are_rejected_without_reading_a_body() {
    for length in [0_u32, MAX_RESPONSE_BYTES as u32 + 1, u32::MAX] {
        let (provider, mut server) = fixture(Duration::from_secs(1));
        let server = thread::spawn(move || {
            read_request(&mut server);
            server.write_all(&length.to_be_bytes()).unwrap();
            assert_eq!(server.read(&mut [0]).unwrap(), 0);
        });
        assert_eq!(
            provider.request_grant(&binding()),
            Err(AgentdFinalUseIssuerError::MalformedResponse)
        );
        server.join().unwrap();
    }
}

#[test]
fn truncated_response_closes_the_channel_and_oversized_binding_writes_nothing() {
    let (provider, mut server) = fixture(Duration::from_secs(1));
    let mut oversized = binding();
    oversized.subject_id = "x".repeat(129);
    assert_eq!(
        provider.request_grant(&oversized),
        Err(AgentdFinalUseIssuerError::InvalidGrant)
    );
    // The first complete request must still be the exact original binding.
    let server = thread::spawn(move || {
        read_request(&mut server);
        server.write_all(&10_u32.to_be_bytes()).unwrap();
        server.write_all(b"{").unwrap();
        server.shutdown(Shutdown::Write).unwrap();
        assert_eq!(server.read(&mut [0]).unwrap(), 0);
    });
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::Unavailable)
    );
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::ChannelClosed)
    );
    server.join().unwrap();
}

#[test]
fn total_deadline_is_not_extended_by_partial_response_progress() {
    let (provider, mut server) = fixture(Duration::from_millis(50));
    let server = thread::spawn(move || {
        read_request(&mut server);
        let bytes = serde_json::to_vec(&response(signed())).unwrap();
        for byte in (bytes.len() as u32).to_be_bytes() {
            thread::sleep(Duration::from_millis(20));
            if server.write_all(&[byte]).is_err() {
                return;
            }
        }
        let _ = server.write_all(&bytes);
    });
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::DeadlineElapsed)
    );
    assert_eq!(
        provider.request_grant(&binding()),
        Err(AgentdFinalUseIssuerError::ChannelClosed)
    );
    server.join().unwrap();
}

#[test]
fn concurrent_requests_do_not_interleave_and_complete_denial_can_be_observed() {
    let (provider, mut server) = fixture(Duration::from_secs(1));
    let provider = std::sync::Arc::new(provider);
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let server = thread::spawn(move || {
        read_request(&mut server);
        entered_tx.send(()).unwrap();
        release_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        let mut denied = response(signed());
        denied["grant"] = serde_json::Value::Null;
        denied["denial_reason"] = json!("operator denied");
        send_response(&mut server, &denied);
        read_request(&mut server);
        send_response(&mut server, &response(signed()));
    });
    let first = std::sync::Arc::clone(&provider);
    let first = thread::spawn(move || first.request_grant(&binding()));
    entered_rx.recv_timeout(Duration::from_secs(1)).unwrap();
    let busy = provider.request_grant(&binding());
    release_tx.send(()).unwrap();
    assert_eq!(busy, Err(AgentdFinalUseIssuerError::Busy));
    assert_eq!(
        first.join().unwrap(),
        Err(AgentdFinalUseIssuerError::Denied)
    );
    assert!(provider.request_grant(&binding()).is_ok());
    server.join().unwrap();
}
