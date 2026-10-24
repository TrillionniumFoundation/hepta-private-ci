//! Same-UID framed transport qualification, not an authority/Current factory.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointReason;
use codex_hepta_memory::CognitiveCheckpointStatus;
use codex_hepta_memory::CognitiveCheckpointToken;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use pretty_assertions::assert_eq;

fn head() -> CognitiveCheckpointHead {
    let agent = AgentId::parse("019a2a19-0000-7000-8000-000000000003").unwrap();
    CognitiveCheckpointHead {
        schema_version: 1, owner_agent_id: agent.clone(), publisher_epoch: 1, counter: 1,
        last_mutation_sequence: 0,
        writer_binding: CognitiveCheckpointWriterBinding {
            lease_id: "framing-only".into(), generation: 1, authority_epoch: 1, owner_epoch: 1,
            authority_grant_digest: Sha256Digest::for_bytes(b"no production grant"),
            fencing_token_digest: Sha256Digest::for_bytes(b"no production fencing token"),
            expires_at_unix_seconds: 1,
        },
        peer_lifetime: CognitiveCheckpointPeerLifetime {
            uid: 60001, pid: 12345, boot_id: "framing-only".into(), process_start_ticks: 1,
        },
        phase: CognitiveCheckpointPhase::Current,
        last_current: CognitiveRecoveryAnchor {
            profile: "hepta:cognitive:exact-current-cut:v1".into(), owner_agent_id: agent,
            schema_digest: Sha256Digest::for_bytes(b"framing schema"),
            state_digest: Sha256Digest::for_bytes(b"framing state"),
        },
        proposal: None, last_request: None,
    }
}

fn ack() -> CognitiveCheckpointResponse {
    CognitiveCheckpointResponse {
        schema_version: 1, request_id: "00000000000000010000000000000001".into(),
        status: CognitiveCheckpointStatus::Ack, reason: None, head: Some(head()),
        token: Some(CognitiveCheckpointToken { publisher_epoch: 1, counter: 1,
            // Deliberately independent of head JSON. Only this server writes
            // the test token; successful client code must preserve its bytes.
            head_sha256: Sha256Digest::for_bytes(b"opaque token retained by the peer"),
        }),
    }
}

fn reply(server: &mut UnixStream, response: &CognitiveCheckpointResponse) {
    read_request(server);
    let bytes = serde_json::to_vec(response).unwrap();
    server.write_all(&(bytes.len() as u32).to_be_bytes()).unwrap();
    server.write_all(&bytes).unwrap();
}

#[tokio::test]
async fn initial_current_keeps_original_token_and_the_same_live_lane() {
    let (transport, mut server) = fixture(Duration::from_secs(1));
    let expected = ack();
    let peer = std::thread::spawn(move || {
        reply(&mut server, &ack());
        reply(&mut server, &ack());
    });
    let inputs = transport.into_protected_inputs(head()).await.unwrap();
    assert_eq!(inputs.current_receipt.head, expected.head.unwrap());
    assert_eq!(inputs.current_receipt.token, expected.token.unwrap());
    let next: CognitiveCheckpointResponse = serde_json::from_slice(
        &inputs.transport.exchange(&request()).await.unwrap()).unwrap();
    assert_eq!(next, ack());
    peer.join().unwrap();
}

#[tokio::test]
async fn changed_current_or_incomplete_ack_drops_the_consumed_lane_without_resend() {
    for mutation in 0..8 {
        let (transport, mut server) = fixture(Duration::from_secs(1));
        let mut response = ack();
        match mutation {
            0 => response.head.as_mut().unwrap().phase = CognitiveCheckpointPhase::Dirty,
            1 => response.head.as_mut().unwrap().writer_binding.owner_epoch += 1,
            2 => response.head.as_mut().unwrap().last_current.state_digest = Sha256Digest::for_bytes(b"changed"),
            3 => response.head.as_mut().unwrap().peer_lifetime.pid += 1,
            4 => response.token.as_mut().unwrap().counter += 1,
            5 => response.token = None,
            6 => response.reason = Some(CognitiveCheckpointReason::Unavailable),
            7 => response.status = CognitiveCheckpointStatus::Unknown,
            _ => unreachable!(),
        }
        let peer = std::thread::spawn(move || {
            reply(&mut server, &response);
            assert_eq!(server.read(&mut [0]).unwrap(), 0, "failed bootstrap must close with no second request");
        });
        assert!(transport.into_protected_inputs(head()).await.is_err());
        peer.join().unwrap();
    }
}

#[tokio::test]
async fn non_current_handoff_is_rejected_before_output_and_closes_owned_lane() {
    let (transport, mut server) = fixture(Duration::from_secs(1));
    let mut expected = head();
    expected.phase = CognitiveCheckpointPhase::Fenced;
    assert!(transport.into_protected_inputs(expected).await.is_err());
    assert_eq!(server.read(&mut [0]).unwrap(), 0);
}
