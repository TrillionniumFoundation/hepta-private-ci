use super::RealtimeHandoffRequest;
use super::RealtimeTurnHandoff;
use super::send_owned_handoff_output;
use crate::realtime_conversation::RealtimeConversationManager;
use crate::realtime_conversation::RealtimeHandoffState;
use crate::realtime_conversation::RealtimeOutbound;
use crate::realtime_conversation::RealtimeSessionKind;
use crate::session::tests::make_session_and_context_with_rx;
use async_channel::Receiver;
use codex_api::RealtimeEventParser;
use codex_protocol::models::MessagePhase;
use codex_protocol::protocol::CodexResponseHandoffMode;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::sync::Arc;
use tokio::sync::Mutex;

fn handoff(kind: RealtimeSessionKind) -> (RealtimeHandoffState, Receiver<RealtimeOutbound>) {
    let (tx, rx) = async_channel::bounded(/*cap*/ 8);
    (
        RealtimeHandoffState {
            identity: Arc::new(()),
            output_complete: Arc::new(Mutex::new(/*t*/ false)),
            output_tx: tx,
            last_output: Arc::new(Mutex::new(/*t*/ None)),
            stream: Arc::new(Mutex::new(Default::default())),
            client_managed_handoffs: false,
            codex_responses_as_items: false,
            codex_response_item_prefix: None,
            codex_response_handoff_mode: CodexResponseHandoffMode::Thinking,
            codex_response_handoff_channel_prefixes: Arc::new(BTreeMap::new()),
            session_kind: kind,
            event_parser: match kind {
                RealtimeSessionKind::V1 => RealtimeEventParser::V1,
                RealtimeSessionKind::V2 => RealtimeEventParser::RealtimeV2,
            },
        },
        rx,
    )
}

#[tokio::test]
async fn receipt_and_cancelled_preparation_do_not_install_an_owner() {
    let (_session, turn, _events) = make_session_and_context_with_rx().await;
    let (state, rx) = handoff(RealtimeSessionKind::V1);
    let request = RealtimeHandoffRequest::new(state.clone(), "incoming".to_string());
    assert!(turn.extension_data.get::<RealtimeTurnHandoff>().is_none());
    assert!(state.stream.lock().await.active_handoff.is_none());
    {
        let _prepared = request.prepare(&turn).await;
        assert!(turn.extension_data.get::<RealtimeTurnHandoff>().is_none());
        assert!(request.admitted.get().is_none());
    }
    assert!(turn.extension_data.get::<RealtimeTurnHandoff>().is_none());
    assert!(state.stream.lock().await.active_handoff.is_none());
    assert!(rx.try_recv().is_err());
}

#[tokio::test]
async fn old_output_and_cleanup_cannot_target_a_new_turn_owner() {
    let (_first_session, first, _first_events) = make_session_and_context_with_rx().await;
    let (_second_session, second, _second_events) = make_session_and_context_with_rx().await;
    let (state, rx) = handoff(RealtimeSessionKind::V1);
    let first_request = RealtimeHandoffRequest::new(state.clone(), "first".to_string());
    first_request.prepare(&first).await.commit();
    let manager = RealtimeConversationManager::new();
    let second_request = RealtimeHandoffRequest::new(state.clone(), "second".to_string());
    manager
        .handoff_out(
            &first,
            "old output".to_string(),
            Some(MessagePhase::FinalAnswer),
        )
        .await
        .expect("old owner output");
    second_request.prepare(&second).await.commit();
    manager
        .handoff_complete(&first)
        .await
        .expect("old owner completion");
    manager.clear_active_handoff(&first).await;
    manager
        .handoff_out(
            &second,
            "new output".to_string(),
            Some(MessagePhase::FinalAnswer),
        )
        .await
        .expect("new owner output");
    let old_output = rx.recv().await.expect("old output retained");
    let new_output = rx.recv().await.expect("new output retained");
    assert_eq!(
        old_output,
        RealtimeOutbound::HandoffUpdate {
            handoff_id: "first".to_string(),
            text: "old output".to_string(),
            phase: Some(MessagePhase::FinalAnswer),
        }
    );
    assert_eq!(
        new_output,
        RealtimeOutbound::HandoffUpdate {
            handoff_id: "second".to_string(),
            text: "new output".to_string(),
            phase: Some(MessagePhase::FinalAnswer),
        }
    );
    let second_owner = second
        .extension_data
        .get::<RealtimeTurnHandoff>()
        .expect("second owner");
    assert_eq!(
        second_owner
            .handoff
            .stream
            .lock()
            .await
            .active_handoff
            .as_deref(),
        Some("second")
    );
    assert!(state.stream.lock().await.active_handoff.is_none());
    assert!(rx.try_recv().is_err());
}

#[tokio::test]
async fn v1_steering_changes_only_the_accepted_turn_owner() {
    let (_session, turn, _events) = make_session_and_context_with_rx().await;
    let (state, rx) = handoff(RealtimeSessionKind::V1);
    let first = RealtimeHandoffRequest::new(state.clone(), "first".to_string());
    first.prepare(&turn).await.commit();
    let first_owner = Arc::clone(first.admitted.get().expect("first admitted owner"));
    let second = RealtimeHandoffRequest::new(state, "second".to_string());
    {
        let prepared = second.prepare(&turn).await;
        assert_eq!(prepared.stream.active_handoff.as_deref(), Some("first"));
        assert!(second.admitted.get().is_none());
        prepared.commit();
    }
    let second_owner = second.admitted.get().expect("steer admitted owner");
    assert!(Arc::ptr_eq(
        &first_owner.handoff.stream,
        &second_owner.handoff.stream
    ));
    assert_eq!(
        second_owner
            .handoff
            .stream
            .lock()
            .await
            .active_handoff
            .as_deref(),
        Some("second")
    );
    second
        .flush_admitted()
        .await
        .expect("no V1 steering acknowledgement");
    assert!(rx.try_recv().is_err());
}

#[tokio::test]
async fn v2_accepted_steer_acknowledgement_precedes_owned_progress_and_completion() {
    let (_session, turn, _events) = make_session_and_context_with_rx().await;
    let (state, rx) = handoff(RealtimeSessionKind::V2);
    let first = RealtimeHandoffRequest::new(state.clone(), "first".to_string());
    first.prepare(&turn).await.commit();
    let second = RealtimeHandoffRequest::new(state, "steer".to_string());
    second.prepare(&turn).await.commit();
    let owner = second.admitted.get().expect("accepted steer owner");
    assert_eq!(
        owner
            .handoff
            .stream
            .lock()
            .await
            .active_handoff
            .as_deref(),
        Some("first")
    );
    let manager = RealtimeConversationManager::new();
    manager
        .handoff_out(
            &turn,
            "result".to_string(),
            Some(MessagePhase::FinalAnswer),
        )
        .await
        .expect("owned progress flushes accepted steering acknowledgement");
    second
        .flush_admitted()
        .await
        .expect("no duplicate acknowledgement");
    manager
        .handoff_complete(&turn)
        .await
        .expect("owned completion");
    assert_eq!(
        rx.recv().await.expect("steering acknowledgement"),
        RealtimeOutbound::HandoffSteerAck {
            handoff_id: "steer".to_string(),
        }
    );
    assert_eq!(
        rx.recv().await.expect("owned progress"),
        RealtimeOutbound::HandoffUpdate {
            handoff_id: "first".to_string(),
            text: "[BACKEND] result".to_string(),
            phase: Some(MessagePhase::FinalAnswer),
        }
    );
    assert_eq!(
        rx.recv().await.expect("owned completion"),
        RealtimeOutbound::CompletedHandoff {
            handoff_id: "first".to_string(),
            text: "[BACKEND] result".to_string(),
            phase: Some(MessagePhase::FinalAnswer),
        }
    );
    send_owned_handoff_output(
        &owner.handoff,
        Some(RealtimeOutbound::HandoffAppend {
            handoff_id: "first".to_string(),
            text: "late timer output".to_string(),
            phase: Some(MessagePhase::Commentary),
        }),
        /*complete*/ false,
    )
    .await
    .expect("a completed owner's late timer is ignored");
    assert!(rx.try_recv().is_err());
}
