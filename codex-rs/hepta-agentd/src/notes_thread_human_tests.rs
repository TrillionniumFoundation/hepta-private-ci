//! Explicit signed protocol fixtures. No Root human binding, actual model,
//! registered UI, admission store or effect authority is fabricated here.
use super::*;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::AgentId;
use codex_hepta_evidence::AuthBusDeliveryStatus;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

fn fixture() -> (AgentdTextSessionConfig, ThreadItem, AuthBusRetainedDelivery) {
    let route = AgentdTextSessionConfig {
        control_socket: "/fixture/agentd.sock".into(),
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18").unwrap(),
        spawn_generation: 1,
        thread_id: "original-thread".into(),
        app_server_session_id: "original-session".into(),
        codex_home: "/fixture/home".into(),
    };
    let body = crate::AuthBusTextBody {
        spawn_generation: 1,
        thread_id: route.thread_id.clone(),
        text: "请将这段内容保存到 Notes".into(),
    };
    let payload = crate::authbus_ingress::payload(&body).unwrap();
    let key = SigningKey::from_bytes(&[39; 32]);
    let claims = SignedMessageClaims {
        issuer_id: StableId::new("fixture-root-text").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        message_id: StableId::new("fixture-text-message").unwrap(),
        subject_id: StableId::new(route.agent_id.as_str()).unwrap(),
        scope_digest: crate::authbus_ingress::scope(&route.agent_id),
        payload_digest: Digest32::of_bytes(&payload),
        sequence: 1,
        expires_at_ms: u64::MAX,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    let message = SignedMessage { claims, signature };
    let delivery_id = message.delivery_id();
    let original = ThreadItem::UserMessage {
        id: "original-user-item".into(),
        client_id: Some(format!("hepta.authbus:{delivery_id}")),
        content: vec![UserInput::Text {
            text: body.text,
            text_elements: vec![],
        }],
    };
    let status = AuthBusDeliveryStatus {
        delivery_id,
        issuer_id: message.claims.issuer_id.clone(),
        key_epoch: message.claims.key_epoch,
        subject_id: message.claims.subject_id.clone(),
        scope_digest: message.claims.scope_digest,
        state: AuthBusDeliveryState::Acked,
        fence: 1,
        attempts: 1,
        available_at_ms: 0,
        lease_until_ms: None,
        acknowledgement: Some(Digest32::of_bytes(b"fixture original Core acknowledgement")),
    };
    (
        route,
        original,
        AuthBusRetainedDelivery {
            message,
            payload,
            status,
        },
    )
}

#[test]
fn original_human_ingress_requires_exact_admitted_input_and_cannot_use_direct_turn_start() {
    let (route, original, retained) = fixture();
    let actual = original_ingress(&route, &original, retained).unwrap();
    assert_eq!(actual.body.thread_id, route.thread_id);
    let (route, mut original, retained) = fixture();
    if let ThreadItem::UserMessage { client_id, .. } = &mut original {
        *client_id = None;
    }
    assert!(original_ingress(&route, &original, retained).is_err());
    let (route, mut original, retained) = fixture();
    if let ThreadItem::UserMessage { content, .. } = &mut original {
        *content = vec![UserInput::Text {
            text: "direct replacement input".into(),
            text_elements: vec![],
        }];
    }
    assert!(original_ingress(&route, &original, retained).is_err());
    let (route, original, mut retained) = fixture();
    retained.status.state = AuthBusDeliveryState::Leased;
    retained.status.acknowledgement = None;
    assert!(
        original_ingress(&route, &original, retained).is_err(),
        "admission without retained original Core acknowledgement is insufficient"
    );
    let (route, original, mut retained) = fixture();
    retained.message.signature[0] ^= 1;
    assert!(original_ingress(&route, &original, retained).is_err());
    let (mut route, original, retained) = fixture();
    route.thread_id = "different-original-thread".into();
    assert!(original_ingress(&route, &original, retained).is_err());
}

#[test]
fn queue_reconciliation_must_observe_the_same_persisted_turn_without_new_admission() {
    use codex_app_server_protocol::ThreadQueueReconcileOutcome;
    use codex_app_server_protocol::ThreadQueueReconcileResponse;
    let mut response = ThreadQueueReconcileResponse {
        client_user_message_id: "original-client".into(),
        payload_sha256: "original-payload".into(),
        outcome: ThreadQueueReconcileOutcome::Persisted {
            turn_id: "original-turn".into(),
        },
    };
    assert!(
        confirm_original_queue(
            &response,
            "original-client",
            "original-payload",
            "original-turn"
        )
        .is_ok()
    );
    assert!(
        confirm_original_queue(
            &response,
            "other-client",
            "original-payload",
            "original-turn"
        )
        .is_err()
    );
    assert!(
        confirm_original_queue(
            &response,
            "original-client",
            "changed-payload",
            "original-turn"
        )
        .is_err()
    );
    assert!(
        confirm_original_queue(
            &response,
            "original-client",
            "original-payload",
            "different-turn"
        )
        .is_err()
    );
    for outcome in [
        ThreadQueueReconcileOutcome::Missing,
        ThreadQueueReconcileOutcome::Cancelled,
    ] {
        response.outcome = outcome;
        assert!(
            confirm_original_queue(
                &response,
                "original-client",
                "original-payload",
                "original-turn"
            )
            .is_err()
        );
    }
}
