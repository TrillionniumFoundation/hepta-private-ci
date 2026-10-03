use super::*;
use crate::chat_owner::*;
use crate::chat_timeline::{History, ProjectionError, ViewFence};
use sha2::{Digest, Sha256};
#[test]
fn late_history_and_stream_remain_bound_to_original_room() {
    let mut workspace = ChatWorkspace::default();
    let fence = ViewFence {
        owner_session: "owner-session".into(),
        generation: 1,
    };
    let ticket = workspace
        .begin_history(0, "thread-a", fence.clone())
        .unwrap();
    workspace.new_draft();
    workspace.edit("room B draft".into());
    workspace
        .receive_history(
            &ticket,
            History {
                thread_id: "thread-a".into(),
                title: "Room A".into(),
                revision: 1,
                event_sequence: 0,
                messages: vec![],
            },
        )
        .unwrap();
    assert!(workspace.timeline().is_none());
    assert_eq!(workspace.draft().text, "room B draft");
    workspace.select(0);
    assert_eq!(
        workspace.timeline().unwrap().history().unwrap().thread_id,
        "thread-a"
    );
    let fresh = workspace.begin_history(0, "thread-a", fence).unwrap();
    assert_eq!(
        workspace.receive_delta(&ticket, "late", 1, "stale"),
        Err(ProjectionError::Stale)
    );
    assert_ne!(ticket, fresh);
}
#[test]
fn actual_owner_adapter_is_consumed_without_manufacturing_a_message() {
    let mut workspace = ChatWorkspace::default();
    workspace.edit("authorized text".into());
    let scope = OwnerScope {
        principal_id: "human".into(),
        session_id: "owner-session".into(),
        connection_generation: 1,
        permission_revision: 2,
        agent_id: "agent".into(),
        agent_generation: 3,
        thread_id: "thread-a".into(),
    };
    workspace
        .install_owner(
            OwnerSession {
                protocol: CHAT_OWNER_PROTOCOL.into(),
                scope: scope.clone(),
                expires_at_ms: 1000,
                capabilities: vec![
                    ChatCapability::SubmitSignedText,
                    ChatCapability::ReadDeliveryStatus,
                ],
            },
            10,
        )
        .unwrap();
    workspace.edit("authorized text".into());
    let history = workspace
        .begin_history(
            0,
            "thread-a",
            ViewFence {
                owner_session: scope.session_id.clone(),
                generation: 1,
            },
        )
        .unwrap();
    workspace
        .receive_history(
            &history,
            History {
                thread_id: "thread-a".into(),
                title: "Room A".into(),
                revision: 1,
                event_sequence: 0,
                messages: vec![],
            },
        )
        .unwrap();
    #[derive(serde::Serialize)]
    struct Body<'a> {
        spawn_generation: u64,
        thread_id: &'a str,
        text: &'a str,
    }
    let body = serde_json::to_vec(&Body {
        spawn_generation: 3,
        thread_id: "thread-a",
        text: "authorized text",
    })
    .unwrap();
    let reference = SignedTextRef::new(
        scope.clone(),
        SignedEnvelopeMetadata {
            host_reference: "retained-by-host".into(),
            issuer_id: "issuer".into(),
            key_epoch: 1,
            message_id: "message-a".into(),
            sequence: 1,
            expires_at_ms: 900,
            payload_sha256: Sha256::digest(body).into(),
            envelope_sha256: [2; 32],
        },
        "authorized text".into(),
    )
    .unwrap();
    workspace
        .stage_authorized_text(0, reference.clone())
        .unwrap();
    let SubmissionAdmission::Dispatch(ticket) = workspace.begin_authorized_submit(0, 20).unwrap()
    else {
        panic!("first dispatch")
    };
    assert!(matches!(
        workspace.begin_authorized_submit(0, 21).unwrap(),
        SubmissionAdmission::Existing(_)
    ));
    workspace.delivery_unknown(&ticket).unwrap();
    let SubmissionAdmission::Dispatch(retry) =
        workspace.retry_exact_initial("message-a", 22).unwrap()
    else {
        panic!("exact retry")
    };
    assert_eq!(retry.envelope(), &reference);
    workspace.new_draft();
    workspace.edit("different room draft".into());
    let receipt = workspace
        .observe_delivery(
            &retry,
            OwnerDeliveryObservation {
                observer: scope,
                message_id: "message-a".into(),
                payload_sha256: reference.metadata().payload_sha256,
                envelope_sha256: [2; 32],
                delivery_id: [3; 32],
                state: OwnerDeliveryState::QueueAccepted,
                delivery_attempts: 1,
                queue_receipt_digest: Some([4; 32]),
            },
            23,
        )
        .unwrap();
    assert_eq!(receipt.state, DeliveryState::QueueAccepted);
    assert_eq!(workspace.draft().text, "different room draft");
    assert!(workspace.timeline().is_none());
    workspace.select(0);
    assert!(
        workspace
            .timeline()
            .unwrap()
            .history()
            .unwrap()
            .messages
            .is_empty()
    );
    assert_eq!(
        workspace.delivery_for(0, 24).unwrap().state,
        DeliveryState::QueueAccepted
    );
}
