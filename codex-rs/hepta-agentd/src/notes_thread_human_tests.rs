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
    fixture_with_text("请将这段内容保存到 Notes".into())
}

fn fixture_with_text(
    text: String,
) -> (AgentdTextSessionConfig, ThreadItem, AuthBusRetainedDelivery) {
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
        text,
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
fn paired_scope_composes_with_original_admission_and_core_reconciliation() {
    use crate::PairedLearningDataUse;
    use crate::PairedTurnRequest;
    use codex_app_server_protocol::ThreadQueueReconcileOutcome;
    use codex_app_server_protocol::ThreadQueueReconcileResponse;

    let study = Digest32::of_bytes(b"fixture study");
    let usage = PairedLearningDataUse::EvaluateOnlyAfterFreeze {
        freeze: Digest32::of_bytes(b"fixture freeze"),
        task: Digest32::of_bytes(b"fixture task"),
    };
    let (route, original, retained) = fixture_with_text(usage.consent_text(study));
    let delivery_id = retained.status.delivery_id;
    let client_id = original_client_id(&original).unwrap().to_owned();
    let ingress = original_ingress(&route, &original, retained).unwrap();
    let owner = crate::text_session::TextOwnerReceipt {
        schema_version: 1,
        protocol: "hepta.ui-chat-owner.v1".into(),
        principal_id: "fixture-person".into(),
        session_id: "fixture-session".into(),
        permission_revision: 1,
        expires_at_ms: u64::MAX,
        route,
        can_interrupt: false,
        can_resolve_approvals: false,
        intent_namespace: "fixture".into(),
        next_intent_sequence: 1,
    };
    let request = PairedTurnRequest {
        turn_id: "original-turn".into(),
        delivery_id,
        study,
        usage,
        expected_principal: owner.principal_id.clone(),
    };
    // This is a protocol fixture, not a constructed VerifiedHumanTurn. The
    // product additionally performs the original live Root owner lookup.
    let mut queue = ThreadQueueReconcileResponse {
        client_user_message_id: client_id.clone(),
        payload_sha256: "fixture-original-input-digest".into(),
        outcome: ThreadQueueReconcileOutcome::Persisted {
            turn_id: request.turn_id.clone(),
        },
    };
    confirm_original_queue(&queue, &client_id, &queue.payload_sha256, &request.turn_id).unwrap();
    request
        .match_original(&client_id, &ingress.body.text, &owner)
        .unwrap();
    let mut wrong = request.clone();
    wrong.usage = PairedLearningDataUse::TrainOnFailureAndCorrection {
        failure: Digest32::of_bytes(b"fixture failure"),
        correction: Digest32::of_bytes(b"fixture correction"),
    };
    assert!(
        wrong
            .match_original(&client_id, &ingress.body.text, &owner)
            .is_err()
    );
    wrong = request.clone();
    wrong.expected_principal = "another-person".into();
    assert!(
        wrong
            .match_original(&client_id, &ingress.body.text, &owner)
            .is_err()
    );
    wrong = request.clone();
    wrong.delivery_id = Digest32::of_bytes(b"another delivery");
    assert!(
        wrong
            .match_original(&client_id, &ingress.body.text, &owner)
            .is_err()
    );
    assert!(
        request
            .match_original(&client_id, &(ingress.body.text + "\n"), &owner)
            .is_err()
    );
    queue.outcome = ThreadQueueReconcileOutcome::Cancelled;
    assert!(
        confirm_original_queue(&queue, &client_id, &queue.payload_sha256, &request.turn_id)
            .is_err()
    );
}

#[test]
fn acked_consent_lookup_binds_reference_route_and_retained_bytes() {
    let (route, original, retained) = fixture();
    let reference = original_client_id(&original).unwrap();
    let envelope = retained_text_ingress(&route, reference, retained).unwrap();
    assert_eq!(envelope.body.thread_id, route.thread_id);
    let (route, _, retained) = fixture();
    assert!(retained_text_ingress(&route, "hepta.authbus:missing", retained).is_err());
    let (mut route, _, retained) = fixture();
    route.thread_id.push('x');
    assert!(retained_text_ingress(&route, reference, retained).is_err());
    let (route, _, mut retained) = fixture();
    retained.status.acknowledgement = None;
    assert!(retained_text_ingress(&route, reference, retained).is_err());
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
