//! Synthetic Core hints only. No real consent, Root effect or training is made.
use super::*;
use codex_app_server_protocol::DynamicToolCallStatus;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn fixture() -> (
    OriginalTrainingTrigger,
    oneshot::Receiver<PairedPreparationRequest>,
    PairedPreparationRequest,
    ThreadItem,
) {
    let manifest = crate::PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(b"synthetic failure"),
        failure_bytes: 17,
        correction_sha256: Digest32::of_bytes(b"synthetic correction"),
        correction_bytes: 20,
    };
    let plan = PairedTrainingPlanV1 {
        preparation: crate::PairedPreparationRegistration {
            study: Digest32::of_bytes(b"synthetic study"),
            enrollment: Digest32::of_bytes(b"synthetic enrollment"),
            frozen_materials: manifest.commitment().unwrap(),
            principal_id: "synthetic-human".into(),
            policy_generation: Generation::new(1).unwrap(),
        },
        manifest,
        operation: Digest32::of_bytes(b"synthetic operation"),
    };
    let delivery = Digest32::of_bytes(b"synthetic delivery");
    let request = plan
        .request_for_original("original-turn".into(), delivery)
        .unwrap();
    let item = ThreadItem::UserMessage {
        id: "original-user-item".into(),
        client_id: Some(format!("hepta.authbus:{delivery}")),
        content: vec![UserInput::Text {
            text: plan.consent_text().unwrap(),
            text_elements: vec![],
        }],
    };
    let (trigger, receiver) = OriginalTrainingTrigger::new(plan, "original-thread".into()).unwrap();
    (trigger, receiver, request, item)
}

#[tokio::test]
async fn paired_training_hint_waits_for_exact_thread_purpose_and_single_plain_text() {
    let (mut trigger, mut receiver, request, item) = fixture();
    trigger
        .observe_completed("different-thread", "original-turn", &item)
        .unwrap();
    let mut other = item.clone();
    if let ThreadItem::UserMessage { content, .. } = &mut other {
        *content = vec![UserInput::Text {
            text: "ordinary chat".into(),
            text_elements: vec![],
        }];
    }
    trigger
        .observe_completed("original-thread", "original-turn", &other)
        .unwrap();
    if let ThreadItem::UserMessage { content, .. } = &mut other {
        *content = vec![UserInput::Text {
            text: crate::PairedLearningDataUse::EvaluateOnlyAfterFreeze {
                freeze: Digest32::of_bytes(b"freeze"),
                task: Digest32::of_bytes(b"task"),
            }
            .consent_text(request.original.study),
            text_elements: vec![],
        }];
    }
    trigger
        .observe_completed("original-thread", "original-turn", &other)
        .unwrap();
    let mut multi = item.clone();
    if let ThreadItem::UserMessage { content, .. } = &mut multi {
        content.push(content[0].clone());
    }
    trigger
        .observe_completed("original-thread", "original-turn", &multi)
        .unwrap();
    assert!(matches!(
        receiver.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    ));
    trigger
        .observe_completed("original-thread", "original-turn", &item)
        .unwrap();
    assert_eq!(receiver.await.unwrap(), request);
}

#[tokio::test]
async fn paired_training_hint_ignores_direct_or_noncanonical_client_and_tool_item() {
    let (mut trigger, mut receiver, request, item) = fixture();
    for id in [
        None,
        Some("direct-client".into()),
        Some(format!("hepta.authbus:{}", request.original.delivery_id).to_uppercase()),
    ] {
        let mut changed = item.clone();
        if let ThreadItem::UserMessage { client_id, .. } = &mut changed {
            *client_id = id;
        }
        trigger
            .observe_completed("original-thread", "original-turn", &changed)
            .unwrap();
    }
    let tool = ThreadItem::DynamicToolCall {
        id: format!("hepta.authbus:{}", request.original.delivery_id),
        namespace: None,
        tool: "hepta_notes_state".into(),
        arguments: serde_json::json!({}),
        status: DynamicToolCallStatus::Failed,
        content_items: None,
        success: None,
        duration_ms: None,
    };
    trigger
        .observe_completed("original-thread", "original-turn", &tool)
        .unwrap();
    assert!(matches!(
        receiver.try_recv(),
        Err(oneshot::error::TryRecvError::Empty)
    ));
    trigger
        .observe_completed("original-thread", "original-turn", &item)
        .unwrap();
    assert_eq!(receiver.await.unwrap(), request);
}

#[tokio::test]
async fn paired_training_hint_is_one_use_and_does_not_rearm_after_delivery() {
    let (mut trigger, receiver, request, item) = fixture();
    trigger
        .observe_completed("original-thread", "original-turn", &item)
        .unwrap();
    assert_eq!(receiver.await.unwrap(), request);
    trigger
        .observe_completed("original-thread", "different-turn", &item)
        .unwrap();
    assert!(trigger.request.is_none());
}

#[test]
fn paired_training_hint_refuses_closed_consumer_without_rearming() {
    let (mut trigger, receiver, _, item) = fixture();
    drop(receiver);
    assert!(
        trigger
            .observe_completed("original-thread", "original-turn", &item)
            .is_err()
    );
    assert!(trigger.request.is_none());
}
