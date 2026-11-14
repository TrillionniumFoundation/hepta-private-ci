//! Exercise attempted-tool recording through actual dispatch, then apply the
//! resolved endpoint policy to the request copy. Attempt metadata is transient.

use super::test_model_client;
use crate::session::step_context::StepContext;
use crate::tools::ExecutedToolCallRecorder;
use crate::tools::context::ToolPayload;
use crate::tools::parallel::ToolCallRuntime;
use crate::tools::router::ToolCall;
use crate::tools::router::ToolCallSource;
use crate::turn_diff_tracker::TurnDiffTracker;
use codex_code_mode::CellId;
use codex_features::Feature;
use codex_model_provider_info::CHATGPT_CODEX_BASE_URL;
use codex_model_provider_info::ModelProviderInfo;
use codex_protocol::auth::AuthMode;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_protocol::models::ResponseItem;
use codex_protocol::openai_models::ToolMode;
use codex_protocol::protocol::SessionSource;
use codex_tools::ToolName;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::collections::HashMap;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

async fn recording_runtime() -> (ToolCallRuntime, Arc<ExecutedToolCallRecorder>) {
    let (mut session, mut turn) = crate::session::tests::make_session_and_context().await;
    Arc::make_mut(&mut turn.config)
        .features
        .enable(Feature::ExecutedToolCallMetadata)
        .expect("enable attempted-tool recording");
    Arc::make_mut(&mut turn.model_info).tool_mode = Some(ToolMode::Direct);
    let recorder = Arc::new(ExecutedToolCallRecorder::default());
    session.services.executed_tool_calls = Some(Arc::clone(&recorder));
    let step = StepContext::for_test(Arc::new(turn));
    let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
    (
        ToolCallRuntime::new(Arc::new(session), step, tracker),
        recorder,
    )
}

#[tokio::test]
async fn rejected_dispatch_preserves_request_attempts_and_endpoint_privacy_on_replay() {
    let (runtime, recorder) = recording_runtime().await;
    let escaped = "\\".repeat(4_096);
    let normal = "\"payload\"";
    let cases = [
        (
            ToolName::namespaced("test_namespace::", "unsupported_tool"),
            ToolPayload::Custom {
                input: normal.to_string(),
            },
            json!({"name": "test_namespace::__unsupported_tool", "arguments": normal}),
        ),
        (
            ToolName::namespaced("test_namespace::", "unsupported_tool"),
            ToolPayload::Custom {
                input: escaped.clone(),
            },
            json!({"name": "test_namespace::__unsupported_tool", "arguments": {
                "_codex_executed_tool_call_truncated": {
                    "original_bytes": serde_json::to_vec(&escaped).expect("serialize input").len(),
                    "max_bytes": 8 * 1024,
                }
            }}),
        ),
        (
            ToolName::namespaced("mcp__rmcp", "echo"),
            ToolPayload::Function {
                arguments: json!({"message": "hook e2e ping"}).to_string(),
            },
            json!({"name": "mcp__rmcp__echo", "arguments": {"message": "hook e2e ping"}}),
        ),
        (
            ToolName::namespaced("rmcp", "echo"),
            ToolPayload::Function {
                arguments: json!({"message": "hook e2e ping"}).to_string(),
            },
            json!({"name": "rmcp__echo", "arguments": {"message": "hook e2e ping"}}),
        ),
        (
            ToolName::plain("exec"),
            ToolPayload::Custom {
                input: normal.to_string(),
            },
            json!({"name": "exec", "arguments": normal}),
        ),
    ];
    let mut history = Vec::new();
    let mut expected_calls = Vec::new();
    for (index, (tool_name, payload, expected)) in cases.into_iter().enumerate() {
        let output = runtime
            .clone()
            .handle_tool_call(
                ToolCall {
                    tool_name,
                    call_id: format!("attempt-{index}"),
                    payload,
                    encrypted_function_args: None,
                },
                CancellationToken::new(),
            )
            .await
            .expect("failed dispatch should produce a model-visible error");
        let output = ResponseItem::from(output);
        assert!(
            serde_json::to_value(&output).expect("serialize error")["output"]
                .as_str()
                .expect("text error")
                .contains("unsupported")
        );
        history.push(output);
        expected_calls.push(json!([expected]));
    }
    let original_history = history.clone();
    for _ in 0..2 {
        let mut prompt = history.clone();
        assert!(recorder.attach_pending_to_prompt(&mut prompt, &mut HashMap::new()));
        for (item, expected) in prompt.iter().zip(&expected_calls) {
            assert_eq!(
                serde_json::to_value(item).expect("serialize recorded item")["internal_chat_message_metadata_passthrough"]
                    ["executed_tool_calls"],
                *expected
            );
        }
        let client = test_model_client(SessionSource::Exec);
        for (endpoint, auth, keep_metadata) in [
            ("https://api.openai.com/v1", AuthMode::ApiKey, true),
            ("https://proxy.example.com/v1", AuthMode::ApiKey, false),
            (CHATGPT_CODEX_BASE_URL, AuthMode::Chatgpt, false),
        ] {
            let provider = ModelProviderInfo::create_openai_provider(Some(endpoint.to_string()))
                .to_api_provider(Some(auth))
                .expect("resolved provider");
            let mut wire = prompt.clone();
            client.prepare_response_items_for_request(&mut wire, &provider);
            for ((item, stored), expected) in wire.iter().zip(&history).zip(&expected_calls) {
                let actual = serde_json::to_value(item).expect("wire item");
                if keep_metadata {
                    assert_eq!(
                        actual["internal_chat_message_metadata_passthrough"]["executed_tool_calls"],
                        *expected
                    );
                } else {
                    assert!(
                        actual
                            .get("internal_chat_message_metadata_passthrough")
                            .is_none()
                    );
                }
                assert_eq!(
                    actual["output"],
                    serde_json::to_value(stored).expect("stored item")["output"]
                );
            }
        }
    }
    assert_eq!(
        history, original_history,
        "request preparation must not mutate durable items"
    );
}

#[tokio::test]
async fn nested_failed_dispatch_records_attempt_for_its_cell_output() {
    let (runtime, recorder) = recording_runtime().await;
    let cell = CellId::new("nested-cell".to_string());
    recorder.register_cell(&cell, "cell-output");
    let result = runtime
        .handle_tool_call_with_source(
            ToolCall {
                tool_name: ToolName::plain("exec_command"),
                call_id: "invalid-nested-call".to_string(),
                payload: ToolPayload::Function {
                    arguments: "{}".to_string(),
                },
                encrypted_function_args: None,
            },
            ToolCallSource::CodeMode {
                cell_id: "nested-cell".to_string(),
                runtime_tool_call_id: "invalid-nested-call".to_string(),
            },
            CancellationToken::new(),
        )
        .await;
    assert!(result.is_err(), "missing nested handler must fail dispatch");
    let mut prompt = [ResponseItem::CustomToolCallOutput {
        id: None,
        call_id: "cell-output".to_string(),
        name: None,
        output: FunctionCallOutputPayload::from_text("caught nested error".to_string()),
        internal_chat_message_metadata_passthrough: None,
    }];
    assert!(recorder.attach_pending_to_prompt(&mut prompt, &mut HashMap::new()));
    let item: Value = serde_json::to_value(&prompt[0]).expect("cell output");
    assert_eq!(
        item["internal_chat_message_metadata_passthrough"]["executed_tool_calls"],
        json!([{"name": "exec_command", "arguments": {}}])
    );
}
