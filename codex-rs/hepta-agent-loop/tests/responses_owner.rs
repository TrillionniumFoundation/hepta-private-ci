#![cfg(feature = "responses-api")]

use codex_api::ResponseEvent;
use codex_hepta_agent_loop::Error;
use codex_hepta_agent_loop::ModelEvent;
use codex_hepta_agent_loop::ModelRequest;
use codex_hepta_agent_loop::ResponsesBridgeLimits;
use codex_hepta_agent_loop::ResponsesBridgeStatus;
use codex_hepta_agent_loop::ResponsesContinuation;
use codex_hepta_agent_loop::ResponsesContinuationOwner;
use codex_hepta_agent_loop::Result;
use codex_hepta_agent_loop::TurnBinding;
use codex_hepta_agent_loop::forward_responses_stream;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::TokenUsage;
use futures::stream;
use pretty_assertions::assert_eq;
use serde_json::json;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

#[derive(Default)]
struct Owner {
    continuation: Option<ResponsesContinuation>,
    fail_commit: bool,
}

impl ResponsesContinuationOwner for Owner {
    async fn retain(
        &mut self,
        binding: &TurnBinding,
        request: &ModelRequest,
        continuation: ResponsesContinuation,
    ) -> Result<Digest32> {
        assert_eq!(binding.run_id.as_str(), "run:1");
        assert_eq!(request.request_id.as_str(), "model:1");
        if self.fail_commit {
            return Err(Error::Owner("fixture persistence failure".into()));
        }
        self.continuation = Some(continuation);
        Ok(Digest32::of_bytes(b"retained full continuation"))
    }
}

fn item(value: serde_json::Value) -> ResponseItem {
    serde_json::from_value(value).expect("valid provider fixture")
}

fn message(text: &str) -> ResponseItem {
    item(json!({"type":"message", "id":"msg_1", "role":"assistant",
        "phase":"final_answer", "content":[{"type":"output_text","text":text}]}))
}

fn function() -> ResponseItem {
    item(
        json!({"type":"function_call", "id":"fc_1", "call_id":"call:1",
        "name":"owned.read", "arguments":"{\"path\":\"fixture.txt\"}"}),
    )
}

fn completed() -> ResponseEvent {
    ResponseEvent::Completed {
        response_id: "resp_1".into(),
        token_usage: Some(TokenUsage {
            input_tokens: 5,
            output_tokens: 3,
            total_tokens: 8,
            reasoning_output_tokens: 1,
            codex_rollout_budget_units: Some(serde_json::Number::from(9)),
            ..Default::default()
        }),
        end_turn: Some(true),
    }
}

async fn forward(
    source: Vec<ResponseEvent>,
    owner: &mut Owner,
) -> (Result<ResponsesBridgeStatus>, Vec<ModelEvent>) {
    let binding = TurnBinding {
        run_id: StableId::new("run:1").expect("run ID"),
        turn_id: StableId::new("turn:1").expect("turn ID"),
        generation: Generation::new(1).expect("generation"),
        admission_digest: Digest32::of_bytes(b"admitted"),
        deadline_unix_ms: u64::MAX,
    };
    let request = ModelRequest {
        request_id: StableId::new("model:1").expect("request ID"),
        payload: "compiled payload".into(),
        context_digest: Digest32::of_bytes(b"compiled payload"),
        input_tokens: 5,
        maximum_provider_input_tokens: 8,
        maximum_output_tokens: 10,
    };
    let (tx, mut rx) = mpsc::channel(16);
    let result = forward_responses_stream(
        &binding,
        &request,
        stream::iter(source.into_iter().map(Ok)),
        owner,
        tx,
        ResponsesBridgeLimits {
            maximum_items: 8,
            maximum_retained_bytes: 4096,
            maximum_visible_bytes: 1024,
        },
        &CancellationToken::new(),
    )
    .await;
    let mut observed = Vec::new();
    while let Some(event) = rx.recv().await {
        observed.push(event.expect("projected event"));
    }
    (result, observed)
}

#[tokio::test]
async fn complete_items_retain_opaque_reasoning_and_message_phase_before_completion() {
    let reasoning = item(json!({"type":"reasoning", "id":"rs_1", "summary":[],
        "encrypted_content":"opaque-provider-reasoning"}));
    let text = message("answer");
    let mut owner = Owner::default();
    let (result, events) = forward(
        vec![
            ResponseEvent::OutputItemDone(reasoning.clone()),
            ResponseEvent::OutputTextDelta("answer".into()),
            ResponseEvent::OutputItemDone(text.clone()),
            completed(),
        ],
        &mut owner,
    )
    .await;
    assert_eq!(
        result.expect("forward succeeds"),
        ResponsesBridgeStatus::Completed
    );
    let retained = owner.continuation.expect("retained before completion");
    assert_eq!(retained.items, vec![reasoning, text]);
    assert_eq!(
        retained.provider_rollout_budget_units,
        Some(serde_json::Number::from(9))
    );
    assert!(
        matches!(events.last(), Some(ModelEvent::Completed { continuation_digest, .. }) if !continuation_digest.is_zero())
    );
}

#[tokio::test]
async fn partial_tool_deltas_never_become_executable_arguments() {
    let mut owner = Owner::default();
    let (result, events) = forward(
        vec![
            ResponseEvent::ToolCallInputDelta {
                item_id: "fc_1".into(),
                call_id: Some("call:1".into()),
                delta: "{\"path\":".into(),
            },
            ResponseEvent::OutputItemDone(function()),
            completed(),
        ],
        &mut owner,
    )
    .await;
    assert_eq!(
        result.expect("forward succeeds"),
        ResponsesBridgeStatus::Completed
    );
    assert_eq!(events.len(), 2);
    assert!(
        matches!(&events[0], ModelEvent::ToolCall(call) if call.arguments == "{\"path\":\"fixture.txt\"}")
    );
    assert!(matches!(&events[1], ModelEvent::Completed { .. }));
}

#[tokio::test]
async fn incomplete_stream_retains_no_terminal_continuation() {
    let mut owner = Owner::default();
    let (result, events) = forward(
        vec![ResponseEvent::OutputTextDelta("partial".into())],
        &mut owner,
    )
    .await;
    assert_eq!(
        result.expect("EOF is unresolved"),
        ResponsesBridgeStatus::Incomplete
    );
    assert!(owner.continuation.is_none());
    assert!(
        !events
            .iter()
            .any(|event| matches!(event, ModelEvent::Completed { .. }))
    );
}

#[tokio::test]
async fn failed_retention_cannot_publish_completion() {
    let mut owner = Owner {
        fail_commit: true,
        ..Default::default()
    };
    let (result, events) = forward(
        vec![
            ResponseEvent::OutputItemDone(message("answer")),
            completed(),
        ],
        &mut owner,
    )
    .await;
    assert!(matches!(result, Err(Error::Owner(_))));
    assert!(
        !events
            .iter()
            .any(|event| matches!(event, ModelEvent::Completed { .. }))
    );
}

#[tokio::test]
async fn inconsistent_text_or_absent_usage_cannot_become_terminal_success() {
    let mut owner = Owner::default();
    let (result, _) = forward(
        vec![
            ResponseEvent::OutputTextDelta("different".into()),
            ResponseEvent::OutputItemDone(message("answer")),
            completed(),
        ],
        &mut owner,
    )
    .await;
    assert!(matches!(
        result,
        Err(Error::Contract("provider text projection mismatch"))
    ));
    assert!(owner.continuation.is_none());
    let (result, _) = forward(
        vec![ResponseEvent::Completed {
            response_id: "resp_1".into(),
            token_usage: None,
            end_turn: Some(true),
        }],
        &mut owner,
    )
    .await;
    assert!(matches!(
        result,
        Err(Error::Contract("provider usage absent"))
    ));
    assert!(owner.continuation.is_none());
}

#[tokio::test]
async fn namespace_is_rejected_instead_of_silently_routing_to_another_tool() {
    let mut owner = Owner::default();
    let tool = item(json!({"type":"function_call", "call_id":"call:1",
        "namespace":"different-owner", "name":"owned.read", "arguments":"{}"}));
    let (result, events) = forward(
        vec![ResponseEvent::OutputItemDone(tool), completed()],
        &mut owner,
    )
    .await;
    assert!(matches!(
        result,
        Err(Error::Contract("unsupported function-call projection"))
    ));
    assert!(events.is_empty());
    assert!(owner.continuation.is_none());
}

#[tokio::test]
async fn terminal_event_cannot_discard_unfinished_tools_or_opaque_items() {
    for partial in [
        ResponseEvent::ToolCallInputDelta {
            item_id: "fc_1".into(),
            call_id: Some("call:1".into()),
            delta: "{".into(),
        },
        ResponseEvent::OutputItemAdded(item(json!({"type":"reasoning", "id":"rs_1",
            "summary":[], "encrypted_content":null}))),
    ] {
        let mut owner = Owner::default();
        let (result, events) = forward(vec![partial, completed()], &mut owner).await;
        assert!(matches!(
            result,
            Err(Error::Contract("provider completion has unfinished items"))
        ));
        assert!(owner.continuation.is_none());
        assert!(
            !events
                .iter()
                .any(|event| matches!(event, ModelEvent::Completed { .. }))
        );
    }
}

#[tokio::test]
async fn duplicate_completed_item_cannot_duplicate_visible_context() {
    let mut owner = Owner::default();
    let (result, _) = forward(
        vec![
            ResponseEvent::OutputItemDone(message("answer")),
            ResponseEvent::OutputItemDone(message("answer")),
            completed(),
        ],
        &mut owner,
    )
    .await;
    assert!(matches!(
        result,
        Err(Error::Contract("duplicate completed provider item"))
    ));
    assert!(owner.continuation.is_none());
}
