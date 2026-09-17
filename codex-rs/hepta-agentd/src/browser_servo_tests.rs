use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

struct ChannelTransport {
    outbound: mpsc::Sender<Vec<u8>>,
    inbound: mpsc::Receiver<Vec<u8>>,
}

impl BrowserServoTransport for ChannelTransport {
    fn write_frame(&mut self, bytes: &[u8]) -> Result<(), BrowserServoError> {
        self.outbound
            .send(bytes.to_vec())
            .map_err(|_| BrowserServoError::Unavailable("test Browser receiver closed".into()))
    }

    fn read_frame(&mut self) -> Result<Vec<u8>, BrowserServoError> {
        self.inbound
            .recv()
            .map_err(|_| BrowserServoError::Unavailable("test Browser sender closed".into()))
    }
}

struct Harness {
    port: Arc<BrowserServoPort<ChannelTransport>>,
    authority: FinalUseAuthority,
    outbound: mpsc::Receiver<Vec<u8>>,
    inbound: mpsc::Sender<Vec<u8>>,
    invocation: BrowserFinalUseInvocation,
    request_digest: [u8; 32],
    _state: tempfile::TempDir,
}

fn harness() -> Harness {
    let state = tempfile::tempdir().expect("authority tempdir");
    let signing = SigningKey::from_bytes(&[7u8; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        state.path(),
        "browser-test-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 7,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let request_digest = [0x11; 32];
    let binding = FinalUseBinding {
        subject_id: "principal.1".to_string(),
        destination_id: "browser.profile.1".to_string(),
        request_sha256: request_digest,
        scope_sha256: [0x22; 32],
        payload_sha256: [0x33; 32],
    };
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "browser-test-issuer".to_string(),
        authority_epoch: 7,
        grant_id: "browser-grant.1".to_string(),
        nonce: [0x44; 32],
        binding: binding.clone(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing input"))
        .to_bytes()
        .to_vec();
    let invocation = BrowserFinalUseInvocation {
        signed_grant: SignedFinalUseGrant { grant, signature },
        binding,
    };
    let (to_browser, outbound) = mpsc::channel();
    let (inbound, from_browser) = mpsc::channel();
    let port = Arc::new(BrowserServoPort::new(
        authority.clone(),
        ChannelTransport {
            outbound: to_browser,
            inbound: from_browser,
        },
    ));
    Harness {
        port,
        authority,
        outbound,
        inbound,
        invocation,
        request_digest,
        _state: state,
    }
}

fn decode_outbound(bytes: &[u8]) -> Value {
    let announced = u32::from_be_bytes(bytes[..4].try_into().expect("prefix")) as usize;
    assert_eq!(announced + 4, bytes.len());
    serde_json::from_slice(&bytes[4..]).expect("outbound JSON")
}

fn inbound_frame(sequence: u64, kind: &str, request_id: &str, payload: Value) -> Vec<u8> {
    let payload_digest =
        sha256_bytes(canonical_json(&payload).expect("canonical payload").as_bytes());
    let frame = json!({
        "schema": PROTOCOL_SCHEMA,
        "protocolVersion": PROTOCOL_VERSION,
        "sequence": sequence,
        "kind": kind,
        "requestId": request_id,
        "payloadDigest": hex_lower(&payload_digest),
        "payload": payload,
    });
    let body = canonical_json(&frame).expect("canonical frame").into_bytes();
    let mut bytes = Vec::with_capacity(body.len() + 4);
    bytes.extend_from_slice(&(body.len() as u32).to_be_bytes());
    bytes.extend_from_slice(&body);
    bytes
}

#[test]
fn revocation_after_final_validation_does_not_cancel_entered_effect() {
    let harness = harness();
    let port = Arc::clone(&harness.port);
    let invocation = harness.invocation.clone();
    let call = thread::spawn(move || {
        port.call(
            BrowserServoCall::effect(json!({"operationId":"operation.1"}), invocation)
                .expect("effect call"),
        )
    });

    let request = decode_outbound(&harness.outbound.recv().expect("request"));
    assert_eq!(request["kind"], "request");
    harness
        .inbound
        .send(inbound_frame(
            1,
            "authority_challenge",
            "browser.agentd.1",
            json!({
                "request": {"operationId":"operation.1"},
                "requestDigest": hex_lower(&harness.request_digest),
                "authorityEpoch": 7,
            }),
        ))
        .expect("challenge");

    // Receiving authority_enter proves that FinalUseAuthority completed its
    // final live check and the synchronous effect has entered.
    let enter = decode_outbound(&harness.outbound.recv().expect("authority enter"));
    assert_eq!(enter["kind"], "authority_enter");
    let witness = enter["payload"]["witnessDigest"]
        .as_str()
        .expect("witness")
        .to_string();

    let authority = harness.authority.clone();
    let (revoked_tx, revoked_rx) = mpsc::channel();
    let revoke = thread::spawn(move || {
        revoked_tx
            .send(authority.update_revocations(FinalUseRevocations {
                authority_epoch: 7,
                revision: 2,
                revoked_grant_ids: BTreeSet::from(["browser-grant.1".to_string()]),
            }))
            .expect("revocation result");
    });
    // Revocation is not serialized behind the Browser pipe/page execution.
    revoked_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("revocation completes after effect entry")
        .expect("revocation succeeds");
    revoke.join().expect("revocation thread");

    harness
        .inbound
        .send(inbound_frame(
            2,
            "dispatch_boundary",
            "browser.agentd.1",
            json!({
                "requestDigest": hex_lower(&harness.request_digest),
                "witnessDigest": witness,
                "localDispatchCrossed": true,
            }),
        ))
        .expect("dispatch boundary");
    harness
        .inbound
        .send(inbound_frame(
            3,
            "response",
            "browser.agentd.1",
            json!({"ok":true,"result":{"status":"indeterminate","terminalObserved":false}}),
        ))
        .expect("response");
    let result = call.join().expect("call thread").expect("Browser result");
    assert_eq!(result["status"], "indeterminate");
}

#[test]
fn revocation_committed_before_final_validation_denies_entry() {
    let harness = harness();
    harness
        .authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 7,
            revision: 2,
            revoked_grant_ids: BTreeSet::from(["browser-grant.1".to_string()]),
        })
        .expect("revoke before call");
    let port = Arc::clone(&harness.port);
    let invocation = harness.invocation.clone();
    let call = thread::spawn(move || {
        port.call(
            BrowserServoCall::effect(json!({"operationId":"operation.2"}), invocation)
                .expect("effect call"),
        )
    });
    let _request = harness.outbound.recv().expect("request");
    harness
        .inbound
        .send(inbound_frame(
            1,
            "authority_challenge",
            "browser.agentd.1",
            json!({
                "request": {"operationId":"operation.2"},
                "requestDigest": hex_lower(&harness.request_digest),
                "authorityEpoch": 7,
            }),
        ))
        .expect("challenge");
    let error = call.join().expect("call thread").expect_err("must reject");
    assert!(matches!(error, BrowserServoError::Authority(_)));
    assert!(matches!(
        harness.outbound.recv_timeout(Duration::from_millis(25)),
        Err(mpsc::RecvTimeoutError::Timeout)
    ));
}

#[test]
fn challenge_request_digest_must_match_signed_final_use_binding() {
    let harness = harness();
    let port = Arc::clone(&harness.port);
    let invocation = harness.invocation.clone();
    let call = thread::spawn(move || {
        port.call(
            BrowserServoCall::effect(json!({"operationId":"operation.3"}), invocation)
                .expect("effect call"),
        )
    });
    let _request = harness.outbound.recv().expect("request");
    harness
        .inbound
        .send(inbound_frame(
            1,
            "authority_challenge",
            "browser.agentd.1",
            json!({
                "request": {"operationId":"operation.3"},
                "requestDigest": hex_lower(&[0x99; 32]),
                "authorityEpoch": 7,
            }),
        ))
        .expect("challenge");
    let error = call.join().expect("call thread").expect_err("must reject");
    assert!(matches!(error, BrowserServoError::BindingMismatch(_)));
}

#[test]
fn non_effect_calls_never_enter_final_use_authority() {
    let harness = harness();
    let port = Arc::clone(&harness.port);
    let call = thread::spawn(move || {
        port.call(
            BrowserServoCall::read(
                BrowserServoMethod::ObservePage,
                json!({"profileId":"profile.1"}),
            )
            .expect("read call"),
        )
    });
    let request = decode_outbound(&harness.outbound.recv().expect("request"));
    assert_eq!(request["payload"]["method"], "observe_page");
    harness
        .inbound
        .send(inbound_frame(
            1,
            "response",
            "browser.agentd.1",
            json!({"ok":true,"result":{"origin":"https://example.com"}}),
        ))
        .expect("response");
    let result = call.join().expect("call thread").expect("result");
    assert_eq!(result["origin"], "https://example.com");
}
