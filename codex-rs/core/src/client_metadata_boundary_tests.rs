use super::test_model_client;
use super::test_model_info;
use super::test_responses_metadata_for_client;
use crate::Prompt;
use crate::function_tool::FunctionCallError;
use crate::session::step_context::StepContext;
use crate::session::tests::make_session_and_context;
use crate::test_support::TestCodexResponsesRequestKind;
use crate::tools::ExecutedToolCallRecorder;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::ExecCommandHandler;
use crate::tools::parallel::ToolCallRuntime;
use crate::tools::registry::CoreToolRuntime;
use crate::tools::registry::ToolRegistry;
use crate::tools::router::ToolCall;
use crate::tools::router::ToolRouter;
use crate::turn_diff_tracker::TurnDiffTracker;
use codex_code_mode::CellId;
use codex_features::Feature;
use codex_model_provider_info::CHATGPT_CODEX_BASE_URL;
use codex_model_provider_info::ModelProviderInfo;
use codex_model_provider_info::OPENAI_API_BASE_URL;
use codex_protocol::auth::AuthMode;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::SessionSource;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn failed_nested_exec_metadata_survives_only_for_official_provider() {
    let (mut session, mut turn) = make_session_and_context().await;
    for feature in [Feature::CodeMode, Feature::ExecutedToolCallMetadata] {
        Arc::make_mut(&mut turn.config)
            .features
            .enable(feature)
            .expect("test config should allow code-mode metadata");
    }
    let recorder = Arc::new(ExecutedToolCallRecorder::default());
    session.services.executed_tool_calls = Some(Arc::clone(&recorder));
    let handler = Arc::new(ExecCommandHandler::default()) as Arc<dyn CoreToolRuntime>;
    let router = Arc::new(ToolRouter::from_parts(
        ToolRegistry::from_tools([handler]),
        Vec::new(),
    ));
    let step = StepContext::for_test(Arc::new(turn)).with_tool_router_for_test(router);
    let runtime = ToolCallRuntime::new(
        Arc::new(session),
        step,
        Arc::new(Mutex::new(TurnDiffTracker::new())),
    );
    recorder.register_cell(&CellId::new("failed-exec-cell".to_string()), "call-1");

    // Exercise the same original handler failure as the JavaScript integration
    // test. No command can execute because its required `cmd` is absent.
    let error = runtime
        .handle_tool_call_with_source(
            ToolCall {
                tool_name: codex_tools::ToolName::plain("exec_command"),
                call_id: "nested-call-1".to_string(),
                payload: ToolPayload::Function {
                    arguments: "{}".to_string(),
                },
                encrypted_function_args: None,
            },
            ToolCallSource::CodeMode {
                cell_id: "failed-exec-cell".to_string(),
                runtime_tool_call_id: "nested-call-1".to_string(),
            },
            CancellationToken::new(),
        )
        .await
        .err()
        .expect("the original exec handler must reject the missing command");
    assert!(
        matches!(&error, FunctionCallError::RespondToModel(message) if message.contains("missing field `cmd`")),
        "unexpected nested handler error: {error:?}"
    );

    let mut prompt = Prompt {
        input: vec![ResponseItem::CustomToolCallOutput {
            id: None,
            call_id: "call-1".to_string(),
            name: None,
            output: FunctionCallOutputPayload::from_text("caught handler error".to_string()),
            internal_chat_message_metadata_passthrough: None,
        }],
        ..Default::default()
    };
    assert!(recorder.attach_pending_to_prompt(&mut prompt.input, &mut HashMap::new()));
    let original_input = prompt.input.clone();
    let expected_calls = json!([{ "name": "exec_command", "arguments": {} }]);
    assert_eq!(
        serde_json::to_value(&prompt.input[0]).expect("prompt item should serialize")["internal_chat_message_metadata_passthrough"]
            ["executed_tool_calls"],
        expected_calls
    );

    let client = test_model_client(SessionSource::Exec);
    let responses_metadata = test_responses_metadata_for_client(
        &client,
        Some("turn-1"),
        "window-1".to_string(),
        /*parent_thread_id*/ None,
        TestCodexResponsesRequestKind::Turn,
    );
    for (base_url, auth_mode, expected) in [
        (OPENAI_API_BASE_URL, AuthMode::ApiKey, Some(expected_calls)),
        ("https://custom.example/v1", AuthMode::ApiKey, None),
        (CHATGPT_CODEX_BASE_URL, AuthMode::Chatgpt, None),
    ] {
        let provider = ModelProviderInfo::create_openai_provider(Some(base_url.to_string()))
            .to_api_provider(Some(auth_mode))
            .expect("provider should build");
        let mut request = client
            .build_responses_request(
                &prompt,
                &test_model_info(),
                /*effort*/ None,
                ReasoningSummary::None,
                /*service_tier*/ None,
                &responses_metadata,
                &provider,
            )
            .expect("request should build");
        client.prepare_response_items_for_request(&mut request.input, &provider);
        let wire = serde_json::to_value(request).expect("request should serialize");
        let metadata = wire["input"][0].get("internal_chat_message_metadata_passthrough");
        assert_eq!(
            metadata.and_then(|metadata| metadata.get("executed_tool_calls")),
            expected.as_ref(),
            "original request preparation must enforce the resolved endpoint: {base_url}"
        );
        if expected.is_none() {
            assert!(metadata.is_none(), "private metadata leaked to {base_url}");
        }
    }
    assert_eq!(prompt.input, original_input);
}
