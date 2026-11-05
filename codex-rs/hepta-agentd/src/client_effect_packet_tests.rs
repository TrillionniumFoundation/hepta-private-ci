use std::time::Duration;

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_uds::UnixListener;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::sleep;
use tokio::time::timeout;

use crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT;
use crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdCapability;
use crate::AgentdCapabilitySet;
use crate::AgentdClient;
use crate::AgentdError;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::AutomationEffectObservation;
use crate::AutomationEffectSnapshot;
use crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES;
use crate::MAX_CONTROL_FRAME_BYTES;

// Transport fixture only; these tests do not claim cryptographic acceptance.
fn fixture(wire: &[u8]) -> (AuthorizedEffectIntent, SignedFinalUseGrant) {
    let intent = AuthorizedEffectIntent {
        run_id: "packet-run".to_string(),
        step_id: "packet-step".to_string(),
        attempt: 1,
        operation_id: "provider.deliver".to_string(),
        subject_id: "019153a4-3088-7e03-a56a-9b1964f75ddd".to_string(),
        destination_id: "pon:fixture".to_string(),
        payload_digest: Sha256Digest::for_bytes(wire),
        final_use_scope_digest: Sha256Digest::for_bytes(b"packet-scope"),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    };
    let grant = SignedFinalUseGrant {
        grant: FinalUseGrant {
            schema_version: 2,
            signer_id: "security-owner".to_string(),
            authority_epoch: 1,
            grant_id: "packet-grant".to_string(),
            nonce: [7; 32],
            binding: intent.final_use_binding().expect("binding"),
            not_before_unix_ms: 1,
            expires_at_unix_ms: 1_001,
        },
        signature: vec![0x9f; 3_309],
    };
    (intent, grant)
}

async fn client_listener() -> (tempfile::TempDir, AgentdClient, UnixListener) {
    let directory = tempfile::tempdir().expect("temporary directory");
    let socket = directory.path().join("packet.sock");
    let listener = UnixListener::bind(&socket).await.expect("bind");
    let client = AgentdClient::new(
        socket,
        AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75ddd").expect("agent id"),
        /*spawn_generation*/ 3,
    )
    .expect("client");
    (directory, client, listener)
}

async fn request(listener: &mut UnixListener) -> (AgentdRequest, BufReader<UnixStream>) {
    let mut reader = BufReader::new(listener.accept().await.expect("accept"));
    let mut header = Vec::new();
    reader.read_until(b'\n', &mut header).await.expect("header");
    assert!(header.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
    (serde_json::from_slice(&header).expect("request"), reader)
}

fn response(request: &AgentdRequest, payload: AgentdPayload) -> AgentdResponse {
    AgentdResponse {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: request.request_id,
        agent_id: AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75ddd").expect("agent id"),
        spawn_generation: request.spawn_generation,
        current_generation: request.spawn_generation,
        payload,
    }
}

async fn reply(reader: &mut BufReader<UnixStream>, response: AgentdResponse) {
    let mut bytes = serde_json::to_vec(&response).expect("response");
    bytes.push(b'\n');
    reader.get_mut().write_all(&bytes).await.expect("write");
    reader.get_mut().shutdown().await.expect("response EOF");
}

fn advertised(id: &str) -> AgentdPayload {
    AgentdPayload::Capabilities(
        AgentdCapabilitySet::new(vec![
            AgentdCapability::new(id, /*major*/ 1, /*minor*/ 0).expect("capability"),
        ])
        .expect("capabilities"),
    )
}

#[tokio::test]
async fn packet_client_sends_exact_binary_then_eof_and_reads_bound_receipt() {
    let (_directory, client, mut listener) = client_listener().await;
    let wire: Vec<u8> = (0..=u8::MAX).cycle().take(49_508).collect();
    let (intent, grant) = fixture(&wire);
    let expected_intent = intent.clone();
    let expected_grant = grant.clone();
    let expected_wire = wire.clone();
    let expected = AutomationEffectSnapshot {
        run_id: intent.run_id.clone(),
        step_id: intent.step_id.clone(),
        attempt: intent.attempt,
        event_seq: 7,
        receipt_digest: Some(Sha256Digest::for_bytes(b"receipt")),
        observation: AutomationEffectObservation::Succeeded,
    };
    let returned = expected.clone();
    let server = tokio::spawn(async move {
        let (capabilities, mut reader) = request(&mut listener).await;
        assert_eq!(capabilities.method, AgentdMethod::Capabilities);
        reply(
            &mut reader,
            response(
                &capabilities,
                advertised(AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1),
            ),
        )
        .await;
        let (header, mut reader) = request(&mut listener).await;
        assert_eq!(
            header.method,
            AgentdMethod::AutomationExecuteEffectPacketV1 {
                intent: expected_intent,
                wire_len: 49_508,
                signed_grant: Box::new(expected_grant),
                command_id: "packet-command".to_string(),
            }
        );
        let mut body = Vec::new();
        reader.read_to_end(&mut body).await.expect("body and EOF");
        assert_eq!(body, expected_wire);
        reply(
            &mut reader,
            response(&header, AgentdPayload::AutomationEffect(returned)),
        )
        .await;
    });
    assert_eq!(
        client
            .automation_execute_effect_packet_v1(intent, &wire, grant, "packet-command".to_string())
            .await
            .expect("packet receipt"),
        expected
    );
    server.await.expect("server");
}

#[tokio::test]
async fn packet_client_refuses_legacy_capability_without_an_effect_connection() {
    let (_directory, client, mut listener) = client_listener().await;
    let (intent, grant) = fixture(b"packet");
    let server = tokio::spawn(async move {
        let (header, mut reader) = request(&mut listener).await;
        reply(
            &mut reader,
            response(&header, advertised(AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT)),
        )
        .await;
        listener
    });
    let error = client
        .automation_execute_effect_packet_v1(intent, b"packet", grant, "packet-command".to_string())
        .await
        .expect_err("legacy capability must not admit a packet");
    assert!(matches!(error, AgentdError::Protocol(message) if message.contains("does not advertise")));
    let mut listener = server.await.expect("server");
    assert!(timeout(Duration::from_millis(20), listener.accept()).await.is_err());
}

#[tokio::test]
async fn packet_client_refuses_bad_body_or_oversized_header_before_connecting() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let client = AgentdClient::new(
        directory.path().join("absent.sock"),
        AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75ddd").expect("agent id"),
        /*spawn_generation*/ 3,
    )
    .expect("client");
    let (intent, grant) = fixture(b"packet");
    for body in [
        Vec::new(),
        vec![0; MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES + 1],
        b"changed".to_vec(),
    ] {
        assert!(matches!(
            client
                .automation_execute_effect_packet_v1(
                    intent.clone(),
                    &body,
                    grant.clone(),
                    "packet-command".to_string(),
                )
                .await,
            Err(AgentdError::Invalid(_))
        ));
    }
    assert!(matches!(
        client
            .automation_execute_effect_packet_v1(
                intent,
                b"packet",
                grant,
                "x".repeat(MAX_CONTROL_FRAME_BYTES as usize),
            )
            .await,
        Err(AgentdError::Protocol(message)) if message.contains("header exceeded")
    ));
}

#[tokio::test]
async fn packet_responses_keep_identity_framing_and_overload_checks() {
    let (_directory, client, _listener) = client_listener().await;
    let request = AgentdRequest::capabilities(/*request_id*/ 7, /*spawn_generation*/ 3);
    let expected = response(
        &request,
        advertised(AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1),
    );
    for (field, value) in [
        ("schema_version", serde_json::json!(999)),
        ("request_id", serde_json::json!(8)),
        ("spawn_generation", serde_json::json!(4)),
        (
            "agent_id",
            serde_json::json!("019153a4-3088-7e03-a56a-9b1964f75dd3"),
        ),
    ] {
        let mut wrong = serde_json::to_value(&expected).expect("response");
        wrong[field] = value;
        let mut bytes = serde_json::to_vec(&wrong).expect("wrong identity");
        bytes.push(b'\n');
        assert!(matches!(
            client.decode_response(request.request_id, &bytes),
            Err(AgentdError::Protocol(message)) if message.contains("identity does not match")
        ));
    }
    let mut bytes = serde_json::to_vec(&expected).expect("response");
    assert!(client.decode_response(request.request_id, &bytes).is_err());
    bytes.push(b'\n');
    assert_eq!(
        client.decode_response(request.request_id, &bytes).expect("identity-bound response"),
        expected
    );
    assert!(matches!(
        client.decode_response(request.request_id, crate::AGENTD_CONTROL_OVERLOAD_FRAME),
        Err(AgentdError::Overloaded { retry_after_ms })
            if retry_after_ms == crate::AGENTD_OVERLOAD_RETRY_AFTER_MS
    ));
    let mut oversized = vec![b' '; MAX_CONTROL_FRAME_BYTES as usize];
    oversized.push(b'\n');
    assert!(matches!(
        client.decode_response(request.request_id, &oversized),
        Err(AgentdError::Protocol(message)) if message.contains("bounded response frame")
    ));
}

#[tokio::test]
async fn packet_client_deadline_includes_capability_discovery_and_response() {
    let (_directory, mut client, mut listener) = client_listener().await;
    client.timeout = Duration::from_secs(1);
    let (intent, grant) = fixture(b"packet");
    let server = tokio::spawn(async move {
        let (capabilities, mut reader) = request(&mut listener).await;
        sleep(Duration::from_millis(600)).await;
        reply(
            &mut reader,
            response(
                &capabilities,
                advertised(AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1),
            ),
        )
        .await;
        let (header, mut reader) = request(&mut listener).await;
        let mut body = Vec::new();
        reader.read_to_end(&mut body).await.expect("complete body");
        assert_eq!(body, b"packet");
        sleep(Duration::from_millis(600)).await;
        let mut bytes = serde_json::to_vec(&response(
            &header,
            AgentdPayload::AutomationEffect(AutomationEffectSnapshot {
                run_id: "packet-run".to_string(),
                step_id: "packet-step".to_string(),
                attempt: 1,
                event_seq: 7,
                receipt_digest: Some(Sha256Digest::for_bytes(b"receipt")),
                observation: AutomationEffectObservation::Succeeded,
            }),
        ))
        .expect("response");
        bytes.push(b'\n');
        // The shared deadline has closed the client; a fresh per-stage timeout
        // would incorrectly accept this late success instead.
        let _ = reader.get_mut().write_all(&bytes).await;
    });
    assert!(matches!(
        client
            .automation_execute_effect_packet_v1(intent, b"packet", grant, "packet-command".to_string())
            .await,
        Err(AgentdError::Protocol(message)) if message.contains("packet request timed out")
    ));
    server.await.expect("server observed the complete original packet");
}
