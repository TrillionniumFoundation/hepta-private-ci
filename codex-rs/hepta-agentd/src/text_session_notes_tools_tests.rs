use super::*;
use codex_app_server_protocol::DynamicToolCallOutputContentItem;
use pretty_assertions::assert_eq;
use serde_json::json;

fn original() -> ServerRequest {
    ServerRequest::DynamicToolCall {
        request_id: RequestId::Integer(17),
        params: DynamicToolCallParams {
            thread_id: "thread-original".into(),
            turn_id: "turn-original".into(),
            call_id: "call-original".into(),
            namespace: Some(NOTES_MODEL_NAMESPACE.into()),
            tool: NOTES_MODEL_TOOL.into(),
            arguments: json!({"text":"经人类确认的原文"}),
        },
    }
}

fn response() -> DynamicToolCallResponse {
    DynamicToolCallResponse {
        content_items: vec![DynamicToolCallOutputContentItem::InputText {
            text: "fixture original receipt, not a real effect qualification".into(),
        }],
        success: true,
    }
}

fn completed(call: &NotesToolCall, response: &DynamicToolCallResponse) -> ThreadItem {
    ThreadItem::DynamicToolCall {
        id: call.params.call_id.clone(),
        namespace: call.params.namespace.clone(),
        tool: call.params.tool.clone(),
        arguments: call.params.arguments.clone(),
        status: DynamicToolCallStatus::Completed,
        content_items: Some(response.content_items.clone()),
        success: Some(response.success),
        duration_ms: Some(1),
    }
}

#[test]
fn notes_callback_replay_preserves_write_fence_and_exact_call_identity() {
    let request = original();
    let mut callbacks = NotesToolCallbacks::default();
    callbacks
        .observe(
            /*connection_id*/ 7,
            "thread-original",
            "session-original",
            &request,
        )
        .unwrap();
    let call = callbacks.calls.values().next().unwrap().clone();
    callbacks.start_reply(&call, response()).unwrap();
    callbacks
        .observe(
            /*connection_id*/ 7,
            "thread-original",
            "session-original",
            &request,
        )
        .unwrap();
    assert_eq!(
        callbacks.original_mut(&call).unwrap().phase,
        NotesToolPhase::ReplyStarted
    );
    assert!(callbacks.start_reply(&call, response()).is_err());
    assert!(
        callbacks
            .observe(
                /*connection_id*/ 8,
                "thread-original",
                "session-original",
                &request
            )
            .is_err()
    );
    let mut changed = request.clone();
    let ServerRequest::DynamicToolCall { params, .. } = &mut changed else {
        unreachable!()
    };
    params.arguments = json!({"text":"changed argument"});
    assert!(
        callbacks
            .observe(
                /*connection_id*/ 7,
                "thread-original",
                "session-original",
                &changed
            )
            .is_err()
    );
    let mut alias = request;
    let ServerRequest::DynamicToolCall { request_id, .. } = &mut alias else {
        unreachable!()
    };
    *request_id = RequestId::String("17".into());
    assert!(
        callbacks
            .observe(
                /*connection_id*/ 7,
                "thread-original",
                "session-original",
                &alias
            )
            .is_err()
    );
    assert_eq!(callbacks.calls.len(), 1);
}

#[test]
fn notes_callback_completion_requires_original_item_and_exact_response() {
    let mut callbacks = NotesToolCallbacks::default();
    callbacks
        .observe(
            /*connection_id*/ 7,
            "thread-original",
            "session-original",
            &original(),
        )
        .unwrap();
    let call = callbacks.calls.values().next().unwrap().clone();
    callbacks.start_reply(&call, response()).unwrap();
    let item = completed(&call, &response());
    callbacks
        .observe_item("other-thread", "turn-original", &item)
        .unwrap();
    callbacks
        .observe_item("thread-original", "other-turn", &item)
        .unwrap();
    assert_eq!(
        callbacks.original_mut(&call).unwrap().phase,
        NotesToolPhase::ReplyStarted
    );
    callbacks
        .observe_item("thread-original", "turn-original", &item)
        .unwrap();
    assert_eq!(
        callbacks.original_mut(&call).unwrap().phase,
        NotesToolPhase::Completed
    );
    let unrelated = ThreadItem::Plan {
        id: call.params.call_id.clone(),
        text: "not a tool receipt".into(),
    };
    let mut retained = callbacks.original_mut(&call).unwrap().clone();
    assert!(retained.observe_item(&unrelated).is_err());
    let mut contradicted = response();
    contradicted.content_items.clear();
    assert!(
        retained
            .observe_item(&completed(&call, &contradicted))
            .is_err()
    );
    assert_eq!(retained.phase, NotesToolPhase::Completed);

    let mut mismatch = NotesToolCallbacks::default();
    mismatch
        .observe(
            /*connection_id*/ 7,
            "thread-original",
            "session-original",
            &original(),
        )
        .unwrap();
    mismatch.start_reply(&call, response()).unwrap();
    let mut different = response();
    different.content_items = vec![DynamicToolCallOutputContentItem::InputText {
        text: "same success flag, different receipt".into(),
    }];
    mismatch
        .observe_item(
            "thread-original",
            "turn-original",
            &completed(&call, &different),
        )
        .unwrap();
    assert_eq!(
        mismatch.original_mut(&call).unwrap().phase,
        NotesToolPhase::Closed
    );
    assert!(mismatch.start_reply(&call, response()).is_err());
}

#[test]
fn notes_callback_unanswered_completion_never_claims_our_response() {
    let mut callbacks = NotesToolCallbacks::default();
    callbacks
        .observe(
            /*connection_id*/ 7,
            "thread-original",
            "session-original",
            &original(),
        )
        .unwrap();
    let call = callbacks.calls.values().next().unwrap().clone();
    callbacks
        .observe_item(
            "thread-original",
            "turn-original",
            &completed(&call, &response()),
        )
        .unwrap();
    assert_eq!(
        callbacks.original_mut(&call).unwrap().phase,
        NotesToolPhase::Closed
    );
    assert!(callbacks.start_reply(&call, response()).is_err());
}

#[test]
fn notes_callback_late_in_progress_snapshot_cannot_reopen_a_closed_or_completed_call() {
    let mut callbacks = NotesToolCallbacks::default();
    callbacks
        .observe(
            /*connection_id*/ 7,
            "thread-original",
            "session-original",
            &original(),
        )
        .unwrap();
    let stale_pending = callbacks.calls.values().next().unwrap().clone();
    let mut in_progress = completed(&stale_pending, &response());
    let ThreadItem::DynamicToolCall {
        status,
        content_items,
        success,
        ..
    } = &mut in_progress
    else {
        unreachable!()
    };
    *status = DynamicToolCallStatus::InProgress;
    *content_items = None;
    *success = None;
    callbacks.original_mut(&stale_pending).unwrap().phase = NotesToolPhase::Closed;
    assert_eq!(
        callbacks
            .reconcile_snapshot(/*connection_id*/ 7, &stale_pending, &in_progress)
            .unwrap(),
        NotesToolPhase::Closed
    );

    let mut callbacks = NotesToolCallbacks::default();
    callbacks
        .observe(
            /*connection_id*/ 7,
            "thread-original",
            "session-original",
            &original(),
        )
        .unwrap();
    callbacks.start_reply(&stale_pending, response()).unwrap();
    callbacks
        .observe_item(
            "thread-original",
            "turn-original",
            &completed(&stale_pending, &response()),
        )
        .unwrap();
    assert_eq!(
        callbacks
            .reconcile_snapshot(/*connection_id*/ 7, &stale_pending, &in_progress)
            .unwrap(),
        NotesToolPhase::Completed
    );
    assert!(callbacks.start_reply(&stale_pending, response()).is_err());
}
