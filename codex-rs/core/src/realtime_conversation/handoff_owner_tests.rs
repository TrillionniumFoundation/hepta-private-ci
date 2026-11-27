use super::RealtimeHandoffOutputGate;
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
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::TurnAbortedEvent;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use tokio::sync::Mutex;

pub(super) fn handoff(
    kind: RealtimeSessionKind,
) -> (RealtimeHandoffState, Receiver<RealtimeOutbound>) {
    let (tx, rx) = async_channel::bounded(/*cap*/ 8);
    (
        RealtimeHandoffState {
            identity: Arc::new(()),
            output_gate: Arc::new(RealtimeHandoffOutputGate::default()),
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

pub(super) async fn output_complete(handoff: &RealtimeHandoffState) -> bool {
    let gate = &handoff.output_gate;
    let _permit = gate
        .permit
        .acquire()
        .await
        .expect("the output gate is never closed");
    gate.complete.load(Ordering::Relaxed)
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
        assert_eq!(
            prepared
                .stream
                .as_ref()
                .expect("server-managed stream guard")
                .active_handoff
                .as_deref(),
            Some("first")
        );
        assert!(second.admitted.get().is_none());
        prepared.commit();
    }
    let second_owner = second.admitted.get().expect("steer admitted owner");
    assert!(Arc::ptr_eq(
        &first_owner.handoff.stream,
        &second_owner.handoff.stream
    ));
    assert!(Arc::ptr_eq(
        &first_owner.handoff.output_gate,
        &second_owner.handoff.output_gate
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
        owner.handoff.stream.lock().await.active_handoff.as_deref(),
        Some("first")
    );
    let manager = RealtimeConversationManager::new();
    manager
        .handoff_out(&turn, "result".to_string(), Some(MessagePhase::FinalAnswer))
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

#[tokio::test]
async fn only_the_matching_aborted_owner_retires_without_a_completion_acknowledgement() {
    for kind in [RealtimeSessionKind::V1, RealtimeSessionKind::V2] {
        let (session, first, _events) = make_session_and_context_with_rx().await;
        let (_second_session, second, _second_events) = make_session_and_context_with_rx().await;
        let (state, rx) = handoff(kind);
        let first_request = RealtimeHandoffRequest::new(state.clone(), "first".to_string());
        first_request.prepare(&first).await.commit();
        let steer = RealtimeHandoffRequest::new(state.clone(), "steer".to_string());
        steer.prepare(&first).await.commit();
        let first_owner = steer.admitted.get().expect("accepted owner");
        session
            .send_event(
                &first,
                EventMsg::TurnAborted(TurnAbortedEvent {
                    turn_id: Some("different-turn".to_string()),
                    reason: TurnAbortReason::Interrupted,
                    started_at: None,
                    completed_at: None,
                    duration_ms: None,
                }),
            )
            .await;
        assert!(!output_complete(&first_owner.handoff).await);
        assert!(rx.try_recv().is_err());
        session
            .send_event(
                &first,
                EventMsg::TurnAborted(TurnAbortedEvent {
                    turn_id: Some(first.sub_id.clone()),
                    reason: TurnAbortReason::Interrupted,
                    started_at: None,
                    completed_at: None,
                    duration_ms: None,
                }),
            )
            .await;
        assert!(output_complete(&first_owner.handoff).await);
        assert!(
            first_owner
                .handoff
                .stream
                .lock()
                .await
                .active_handoff
                .is_none()
        );
        if matches!(kind, RealtimeSessionKind::V2) {
            assert_eq!(
                rx.recv()
                    .await
                    .expect("only the accepted steering acknowledgement"),
                RealtimeOutbound::HandoffSteerAck {
                    handoff_id: "steer".to_string(),
                }
            );
        }
        assert!(rx.try_recv().is_err());
        let next = RealtimeHandoffRequest::new(state, "next".to_string());
        next.prepare(&second).await.commit();
        let manager = RealtimeConversationManager::new();
        manager.clear_active_handoff(&first).await;
        send_owned_handoff_output(
            &first_owner.handoff,
            Some(RealtimeOutbound::HandoffAppend {
                handoff_id: "first".to_string(),
                text: "late aborted timer".to_string(),
                phase: Some(MessagePhase::Commentary),
            }),
            /*complete*/ false,
        )
        .await
        .expect("retired owner's timer is ignored");
        manager
            .handoff_out(
                &second,
                "next output".to_string(),
                Some(MessagePhase::FinalAnswer),
            )
            .await
            .expect("next owner remains active");
        let expected_text = match kind {
            RealtimeSessionKind::V1 => "next output",
            RealtimeSessionKind::V2 => "[BACKEND] next output",
        };
        assert_eq!(
            rx.recv().await.expect("next owner output"),
            RealtimeOutbound::HandoffUpdate {
                handoff_id: "next".to_string(),
                text: expected_text.to_string(),
                phase: Some(MessagePhase::FinalAnswer),
            }
        );
        assert!(rx.try_recv().is_err());
    }
}

#[tokio::test]
async fn accepted_client_managed_conversation_rebinds_cleanup_without_rerouting_old_output() {
    let (_session, turn, _events) = make_session_and_context_with_rx().await;
    let (_next_session, next_turn, _next_events) = make_session_and_context_with_rx().await;
    let (old, old_rx) = handoff(RealtimeSessionKind::V2);
    let old_request = RealtimeHandoffRequest::new(old, "old-server".to_string());
    old_request.prepare(&turn).await.commit();
    let old_owner = Arc::clone(old_request.admitted.get().expect("old accepted owner"));
    // Original conversation stop closes its receiver, not the accepted Core turn.
    drop(old_rx);
    let (mut current, current_rx) = handoff(RealtimeSessionKind::V2);
    current.client_managed_handoffs = true;
    current.stream.lock().await.active_handoff = Some("received-client".to_string());
    let request = RealtimeHandoffRequest::new(current.clone(), "received-client".to_string());
    let manager = RealtimeConversationManager::new();
    assert!(Arc::ptr_eq(
        &turn
            .extension_data
            .get::<RealtimeTurnHandoff>()
            .expect("receipt must not replace the accepted owner")
            .handoff
            .identity,
        &old_owner.handoff.identity
    ));
    manager
        .handoff_out(&turn, "old output".to_string(), /*phase*/ None)
        .await
        .expect_err("old output stays on the stopped conversation");
    assert!(current_rx.try_recv().is_err());
    {
        let stream = current.stream.lock().await;
        let prepared = request
            .prepare(&turn)
            .now_or_never()
            .expect("client-managed admission must not lock the global stream");
        assert!(prepared.stream.is_none());
        prepared.commit();
        assert_eq!(stream.active_handoff.as_deref(), Some("received-client"));
        request
            .flush_admitted()
            .now_or_never()
            .expect("original client-managed ACK handling is not repeated")
            .expect("no new ACK send");
    }
    let current_owner = request
        .admitted
        .get()
        .expect("accepted client-managed owner");
    assert!(Arc::ptr_eq(
        &current_owner.handoff.identity,
        &current.identity
    ));
    assert!(Arc::ptr_eq(&current_owner.handoff.stream, &current.stream));
    assert!(Arc::ptr_eq(
        &current_owner.handoff.output_gate,
        &current.output_gate
    ));
    manager
        .handoff_out(
            &turn,
            "client-owned output".to_string(),
            /*phase*/ None,
        )
        .await
        .expect("original client-managed output remains a no-op");
    manager
        .handoff_aborted(&turn)
        .await
        .expect("original abort no-op");
    assert_eq!(
        current.stream.lock().await.active_handoff.as_deref(),
        Some("received-client")
    );
    manager
        .handoff_complete(&turn)
        .await
        .expect("original completion no-op");
    manager.clear_active_handoff(&turn).await;
    assert!(current.stream.lock().await.active_handoff.is_none());
    assert!(!output_complete(&current).await);
    assert!(current_rx.try_recv().is_err());
    send_owned_handoff_output(
        &old_owner.handoff,
        Some(RealtimeOutbound::HandoffAppend {
            handoff_id: "old-server".to_string(),
            text: "late old timer".to_string(),
            phase: None,
        }),
        /*complete*/ false,
    )
    .await
    .expect_err("the old timer still holds only its stopped conversation");
    assert!(current_rx.try_recv().is_err());
    current.stream.lock().await.active_handoff = Some("next-client".to_string());
    let next_request = RealtimeHandoffRequest::new(current.clone(), "next-client".to_string());
    next_request.prepare(&next_turn).await.commit();
    manager
        .handoff_complete(&next_turn)
        .await
        .expect("next completion no-op");
    manager.clear_active_handoff(&next_turn).await;
    assert!(current.stream.lock().await.active_handoff.is_none());
    assert!(!output_complete(&current).await);
    assert!(current_rx.try_recv().is_err());
}

#[tokio::test]
async fn server_managed_readmission_does_not_inherit_a_prior_client_managed_global_stream() {
    let (_session, turn, _events) = make_session_and_context_with_rx().await;
    let (mut client, client_rx) = handoff(RealtimeSessionKind::V2);
    client.client_managed_handoffs = true;
    client.stream.lock().await.active_handoff = Some("received-client".to_string());
    let client_request = RealtimeHandoffRequest::new(client.clone(), "received-client".to_string());
    client_request.prepare(&turn).await.commit();
    drop(client_rx);
    let (server, server_rx) = handoff(RealtimeSessionKind::V2);
    let request = RealtimeHandoffRequest::new(server.clone(), "server-c".to_string());
    request.prepare(&turn).await.commit();
    let owner = request.admitted.get().expect("accepted server owner");
    assert!(Arc::ptr_eq(&owner.handoff.identity, &server.identity));
    assert!(!Arc::ptr_eq(&owner.handoff.stream, &client.stream));
    assert!(!Arc::ptr_eq(&owner.handoff.stream, &server.stream));
    assert!(!Arc::ptr_eq(
        &owner.handoff.output_gate,
        &client.output_gate
    ));
    assert!(!Arc::ptr_eq(
        &owner.handoff.output_gate,
        &server.output_gate
    ));
    assert!(!owner.handoff.client_managed_handoffs);
    assert_eq!(
        client.stream.lock().await.active_handoff.as_deref(),
        Some("received-client")
    );
    let manager = RealtimeConversationManager::new();
    manager
        .handoff_out(&turn, "C output".to_string(), /*phase*/ None)
        .await
        .expect("only the accepted server conversation receives output");
    manager
        .handoff_complete(&turn)
        .await
        .expect("server completion");
    manager.clear_active_handoff(&turn).await;
    assert_eq!(
        server_rx.recv().await.expect("server output"),
        RealtimeOutbound::HandoffUpdate {
            handoff_id: "server-c".to_string(),
            text: "[BACKEND] C output".to_string(),
            phase: None,
        }
    );
    assert_eq!(
        server_rx.recv().await.expect("server completion"),
        RealtimeOutbound::CompletedHandoff {
            handoff_id: "server-c".to_string(),
            text: "[BACKEND] C output".to_string(),
            phase: None,
        }
    );
    assert!(server_rx.try_recv().is_err());
    assert!(server.stream.lock().await.active_handoff.is_none());
    assert_eq!(
        client.stream.lock().await.active_handoff.as_deref(),
        Some("received-client")
    );
}
