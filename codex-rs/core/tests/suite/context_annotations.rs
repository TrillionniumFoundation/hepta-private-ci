use anyhow::Result;
use codex_core::CodexThread;
use codex_core::TurnInputRequest;
use codex_core::config::CurrentTimeReminderConfig;
use codex_core::config::RolloutBudgetConfig;
use codex_core::config::TokenBudgetConfig;
use codex_features::Feature;
use codex_history::RolloutItem;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::openai_models::InputModality;
use codex_protocol::protocol::AdditionalContextEntry;
use codex_protocol::protocol::AdditionalContextKind;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::GuardianAssessmentAction;
use codex_protocol::protocol::GuardianAssessmentEvent;
use codex_protocol::protocol::GuardianAssessmentStatus;
use codex_protocol::protocol::Op;
use codex_protocol::user_input::UserInput;
use core_test_support::responses::ResponsesRequest;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use pretty_assertions::assert_eq;
use serde_json::Value;
use std::collections::BTreeMap;
use std::collections::HashMap;

/// The only model-specific projections used by these annotation fixtures.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum RequestInputProjection {
    Unchanged,
    ResponsesLiteMessageImages,
    TextOnlyMessageMedia,
}

fn assert_local_item_matches_wire(local: &Value, wire: &Value, projection: RequestInputProjection) {
    let mut expected: ResponseItem =
        serde_json::from_value(local.clone()).expect("local response item");
    expected.clear_content_item_kinds();
    if let ResponseItem::Message { content, .. } = &mut expected {
        for part in content {
            match (projection, part) {
                (
                    RequestInputProjection::ResponsesLiteMessageImages,
                    ContentItem::InputImage { detail, .. },
                ) => *detail = None,
                (RequestInputProjection::TextOnlyMessageMedia, part) => match part {
                    ContentItem::InputImage { .. } => {
                        *part = ContentItem::InputText {
                            text: "image content omitted because you do not support image input"
                                .into(),
                        };
                    }
                    ContentItem::InputAudio { .. } => {
                        *part = ContentItem::InputText {
                            text: "audio content omitted because you do not support audio input"
                                .into(),
                        };
                    }
                    _ => {}
                },
                _ => {}
            }
        }
    }
    assert_eq!(
        serde_json::to_value(expected).expect("projected local response item"),
        *wire,
        "local annotations must bind to the complete captured wire item ({projection:?})"
    );
}

fn local_item_id_for_request(input: &[Value], index: usize) -> Option<&str> {
    let item = &input[index];
    let id = item["id"].as_str();
    if id.is_none()
        && item["type"] == "message"
        && matches!(item["role"].as_str(), Some("user" | "developer"))
    {
        assert!(
            index == 1
                && input[0]["type"] == "additional_tools"
                && input[0]["role"] == "developer"
                && input[0]["tools"].is_array()
                && item["role"] == "developer"
                && item["content"].as_array().is_some_and(|content| {
                    content.len() == 1
                        && content[0]["type"] == "input_text"
                        && content[0]["text"]
                            .as_str()
                            .is_some_and(|text| !text.is_empty())
                }),
            "locally generated request item must retain a matchable ID: {item}"
        );
    }
    id
}

/// Finds the exact persisted items sent to a compatible provider.
pub(super) async fn local_input_for_request(
    thread: &CodexThread,
    request: &ResponsesRequest,
) -> Vec<Value> {
    local_input_for_request_with_projection(thread, request, RequestInputProjection::Unchanged)
        .await
}

/// Finds persisted copies of the items sent in this request, in request order.
///
/// Loopback providers must not receive local classifications. Match stable item
/// IDs and compare every matched item's complete projected JSON, rather than
/// reconstructing annotations from text or adding them to the captured request.
/// Unchanged items differ only by classifications. Explicit media projections
/// follow client_common::strip_image_details and context_manager::normalize;
/// they never exempt role, type, ordinary text, order, or other metadata.
/// Locally generated user/developer items must retain IDs;
/// the only exception is the request-generated Responses Lite instruction
/// prefix, covered by the client's no-network request-builder tests. Server
/// output may have non-prefixed IDs removed by the production wire preparation.
pub(super) async fn local_input_for_request_with_projection(
    thread: &CodexThread,
    request: &ResponsesRequest,
    projection: RequestInputProjection,
) -> Vec<Value> {
    let input = request.input();
    assert!(
        input.iter().all(|item| {
            item.pointer("/internal_chat_message_metadata_passthrough/content_item_kinds")
                .is_none()
        }),
        "compatible provider must not receive local classifications: {input:?}"
    );
    thread
        .flush_rollout()
        .await
        .expect("flush local annotations");
    let history = thread
        .load_history(/*include_archived*/ false)
        .await
        .expect("load local annotations");
    let mut local_items = HashMap::new();
    for item in history.items {
        let items = match item {
            RolloutItem::ResponseItem(item) => vec![item],
            RolloutItem::Compacted(item) => item.replacement_history.unwrap_or_default(),
            _ => Vec::new(),
        };
        for item in items {
            let item = serde_json::to_value(item.item).expect("serialize local response item");
            if let Some(id) = item["id"].as_str() {
                if let Some(previous) = local_items.insert(id.to_string(), item.clone()) {
                    assert_eq!(
                        previous, item,
                        "local item {id} changed across history entries; cannot bind its annotations to this request"
                    );
                }
            }
        }
    }
    input
        .iter()
        .enumerate()
        .filter_map(|(index, item)| local_item_id_for_request(&input, index).map(|id| (id, item)))
        .map(|(id, wire)| {
            let local = local_items
                .get(id)
                .unwrap_or_else(|| panic!("request item {id} is missing from local history"));
            assert_local_item_matches_wire(local, wire, projection);
            local.clone()
        })
        .collect()
}

/// Returns whether a local item's classifications exactly match this sequence.
pub(super) fn has_content_kinds(items: &[Value], kinds: &[&str]) -> bool {
    items.iter().any(|item| {
        item["internal_chat_message_metadata_passthrough"]["content_item_kinds"]
            == serde_json::json!(kinds)
    })
}

#[test]
fn only_generated_lite_prefix_may_omit_a_local_message_id() {
    let lite = vec![
        serde_json::json!({"type": "additional_tools", "role": "developer", "tools": []}),
        serde_json::json!({
            "type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "base instructions"}],
        }),
        serde_json::json!({
            "type": "message", "role": "user", "id": "msg_local",
            "content": [{"type": "input_text", "text": "text-only turn"}],
        }),
    ];
    // Prefix recognition does not opt the text-only turn into media projection.
    assert_eq!(local_item_id_for_request(&lite, 1), None);
    assert_eq!(local_item_id_for_request(&lite, 2), Some("msg_local"));
    for role in ["user", "developer"] {
        let mut non_lite = vec![lite[1].clone()];
        non_lite[0]["role"] = serde_json::json!(role);
        assert!(std::panic::catch_unwind(|| local_item_id_for_request(&non_lite, 0)).is_err());
    }
    let mut misplaced = lite.clone();
    misplaced.swap(1, 2);
    assert!(std::panic::catch_unwind(|| local_item_id_for_request(&misplaced, 2)).is_err());
    for (index, field, wrong) in [
        (0, "type", serde_json::json!("message")),
        (0, "role", serde_json::json!("user")),
        (0, "tools", serde_json::json!(null)),
        (1, "role", serde_json::json!("user")),
        (1, "content", serde_json::json!([])),
    ] {
        let mut invalid = lite.clone();
        invalid[index][field] = wrong;
        assert!(
            std::panic::catch_unwind(|| local_item_id_for_request(&invalid, 1)).is_err(),
            "invalid generated-prefix field {index}.{field} must reject an ID-less local message"
        );
    }
}

#[test]
fn local_annotation_binding_requires_exact_projected_wire_payload() {
    let local = serde_json::json!({
        "type": "message", "id": "msg_local", "role": "user",
        "content": [
            {"type": "input_image", "image_url": "data:image/png;base64,aW1hZ2U=", "detail": "high"},
            {"type": "input_audio", "audio_url": "data:audio/wav;base64,YXVkaW8="},
            {"type": "input_text", "text": "keep this caption"},
        ],
        "internal_chat_message_metadata_passthrough": {
            "content_item_kinds": ["user.image", "user.audio", "user.text"],
            "turn_id": "turn-1", "create_time": 123,
        },
    });
    let mut exact_wire = local.clone();
    exact_wire["internal_chat_message_metadata_passthrough"]
        .as_object_mut()
        .expect("metadata")
        .remove("content_item_kinds");
    let mut lite_wire = exact_wire.clone();
    lite_wire["content"] = serde_json::json!([
        {"type": "input_image", "image_url": "data:image/png;base64,aW1hZ2U="},
        {"type": "input_audio", "audio_url": "data:audio/wav;base64,YXVkaW8="},
        {"type": "input_text", "text": "keep this caption"},
    ]);
    let mut text_wire = exact_wire.clone();
    text_wire["content"] = serde_json::json!([
        {"type": "input_text", "text": "image content omitted because you do not support image input"},
        {"type": "input_text", "text": "audio content omitted because you do not support audio input"},
        {"type": "input_text", "text": "keep this caption"},
    ]);
    let cases = [
        (RequestInputProjection::Unchanged, exact_wire.clone()),
        (
            RequestInputProjection::ResponsesLiteMessageImages,
            lite_wire,
        ),
        (RequestInputProjection::TextOnlyMessageMedia, text_wire),
    ];
    for (projection, wire) in cases {
        assert_local_item_matches_wire(&local, &wire, projection);
        for (pointer, wrong) in [
            ("/type", serde_json::json!("other")),
            ("/role", serde_json::json!("developer")),
            ("/content/2/text", serde_json::json!("different caption")),
            (
                "/content/0",
                serde_json::json!({"type": "input_text", "text": "unapproved media replacement"}),
            ),
            (
                "/internal_chat_message_metadata_passthrough/turn_id",
                serde_json::json!("turn-2"),
            ),
            (
                "/internal_chat_message_metadata_passthrough/create_time",
                serde_json::json!(456),
            ),
        ] {
            let mut mismatched = wire.clone();
            *mismatched.pointer_mut(pointer).expect("fixture field") = wrong;
            assert!(
                std::panic::catch_unwind(|| {
                    assert_local_item_matches_wire(&local, &mismatched, projection);
                })
                .is_err(),
                "same-ID change at {pointer} must fail for {projection:?}"
            );
        }
        let mut reordered = wire.clone();
        reordered["content"]
            .as_array_mut()
            .expect("content")
            .swap(0, 1);
        assert!(
            std::panic::catch_unwind(|| {
                assert_local_item_matches_wire(&local, &reordered, projection);
            })
            .is_err(),
            "media order must remain bound for {projection:?}"
        );
        if projection != RequestInputProjection::Unchanged {
            assert!(
                std::panic::catch_unwind(|| {
                    assert_local_item_matches_wire(
                        &local,
                        &wire,
                        RequestInputProjection::Unchanged,
                    );
                })
                .is_err(),
                "transformed media requires explicit projection"
            );
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn first_request_item_types_roles_and_content_annotations() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    let response = mount_sse_once(
        &server,
        sse(vec![ev_response_created("resp-1"), ev_completed("resp-1")]),
    )
    .await;
    let test = test_codex()
        .with_model_info_override("gpt-5.5", |model_info| {
            model_info.input_modalities.push(InputModality::Audio);
        })
        .with_config(|config| {
            config.developer_instructions = Some("Keep world-state annotations aligned.".into());
            config.model_context_window = Some(128_000);
            config.current_time_reminder = Some(CurrentTimeReminderConfig::default());
            config.token_budget = Some(TokenBudgetConfig {
                guidance_message: Some("Preserve important context.".into()),
                ..TokenBudgetConfig::default()
            });
            config.rollout_budget = Some(RolloutBudgetConfig {
                limit_tokens: 100,
                reminder_at_remaining_tokens: Vec::new(),
                sampling_token_weight: 1.0,
                prefill_token_weight: 1.0,
            });
            config.multi_agent_v2.root_agent_usage_hint_text =
                Some("Coordinate available subagents.".into());
            config.multi_agent_v2.multi_agent_mode_hint_text =
                Some("Delegate independent work.".into());
            for feature in [
                Feature::CurrentTimeReminder,
                Feature::DeferredExecutor,
                Feature::MultiAgentV2,
                Feature::TokenBudget,
            ] {
                config
                    .features
                    .enable(feature)
                    .expect("test config should allow feature update");
            }
        })
        .build_with_auto_env(&server)
        .await?;

    test.codex
        .submit(Op::ApproveGuardianDeniedAction {
            event: GuardianAssessmentEvent {
                id: "guardian-review".to_string(),
                target_item_id: None,
                plugin_id: None,
                script_path: None,
                turn_id: "guardian-turn".to_string(),
                started_at_ms: 0,
                completed_at_ms: Some(1),
                status: GuardianAssessmentStatus::Denied,
                risk_level: None,
                user_authorization: None,
                rationale: None,
                decision_source: None,
                action: GuardianAssessmentAction::McpToolCall {
                    server: "example".to_string(),
                    tool_name: "write".to_string(),
                    connector_id: None,
                    connector_name: None,
                    tool_title: None,
                },
            },
        })
        .await?;
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::RawResponseItem(_))
    })
    .await;

    test.codex
        .start_or_steer_turn(
            TurnInputRequest::user_input(vec![
                UserInput::Text {
                    text: "inspect world state".to_string(),
                    text_elements: Vec::new(),
                },
                UserInput::Image {
                    image_url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==".to_string(),
                    detail: None,
                },
                UserInput::Audio {
                    audio_url: "data:audio/wav;base64,AAAA".to_string(),
                },
            ])
            .with_additional_context(BTreeMap::from([
                (
                    "browser_info".to_string(),
                    AdditionalContextEntry {
                        value: "tab one".to_string(),
                        kind: AdditionalContextKind::Untrusted,
                    },
                ),
                (
                    "automation_info".to_string(),
                    AdditionalContextEntry {
                        value: "run one".to_string(),
                        kind: AdditionalContextKind::Application,
                    },
                ),
            ])),
        )
        .await?;
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;

    let request = response.single_request();
    let local_input = local_input_for_request(&test.codex, &request).await;
    assert_eq!(local_input.len(), request.input().len());
    // The local classification snapshot remains positive, and removing only
    // classifications must produce the complete compatible-provider payload.
    let wire_input = local_input
        .iter()
        .map(|item| {
            let mut item: codex_protocol::models::ResponseItem =
                serde_json::from_value(item.clone()).expect("local response item");
            item.clear_content_item_kinds();
            serde_json::to_value(item).expect("compatible response item")
        })
        .collect::<Vec<_>>();
    assert_eq!(wire_input, request.input());
    assert!(has_content_kinds(
        &local_input,
        &["guardian.approved_action"]
    ));
    let mut guardian_item = local_input
        .first()
        .cloned()
        .expect("guardian approval should be the first context item");
    guardian_item
        .as_object_mut()
        .expect("guardian approval should be an object")
        .remove("id");
    let guardian_metadata = guardian_item["internal_chat_message_metadata_passthrough"]
        .as_object_mut()
        .expect("guardian approval should have passthrough metadata");
    guardian_metadata.remove("turn_id");
    guardian_metadata.remove("create_time");
    let approved_action = serde_json::to_string_pretty(&serde_json::json!({
        "action": {
            "type": "mcp_tool_call",
            "server": "example",
            "tool_name": "write",
            "connector_id": null,
            "connector_name": null,
            "tool_title": null,
        },
        "outcome": "allowed",
    }))?;
    assert_eq!(
        guardian_item,
        serde_json::json!({
            "type": "message",
            "role": "developer",
            "content": [{
                "type": "input_text",
                "text": format!(
                    "The user has manually approved a specific action that was previously `Rejected`.\n\n\
                     Treat this as approval to perform that exact action in the same context in which it was originally requested.\n\
                     Do not assume this also authorizes similar operations with different payloads.\n\n\
                     Approved action:\n\
                     {approved_action}"
                ),
            }],
            "internal_chat_message_metadata_passthrough": {
                "content_item_kinds": ["guardian.approved_action"],
            },
        })
    );

    let items = local_input
        .into_iter()
        .map(|item| {
            let item_type = item["type"].as_str().expect("response item type");
            let role = item["role"].as_str().unwrap_or("-");
            let content_annotations =
                &item["internal_chat_message_metadata_passthrough"]["content_item_kinds"];
            format!("{item_type} {role} {content_annotations}")
        })
        .collect::<Vec<_>>()
        .join("\n");
    insta::assert_snapshot!(items, @r#"
    message developer ["guardian.approved_action"]
    message developer ["generic.developer_instructions","token_budget.context_window_guidance","permissions.instructions","environments.instructions"]
    message developer ["token_budget.context_window"]
    message developer ["multi_agent.usage_hint"]
    message developer ["multi_agent.mode_instructions"]
    message user ["environments.environment_context"]
    message developer ["additional_content.automation_info"]
    message user ["additional_content.browser_info"]
    message user ["user.text","user.image","user.audio"]
    message developer ["rollout_budget.remaining_tokens"]
    message developer ["current_time.reminder"]
    "#);

    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn content_item_kinds_are_omitted_when_feature_disabled() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    let response = mount_sse_once(
        &server,
        sse(vec![ev_response_created("resp-1"), ev_completed("resp-1")]),
    )
    .await;
    let test = test_codex()
        .with_config(|config| {
            config.developer_instructions = Some("Keep other metadata intact.".into());
            config
                .features
                .disable(Feature::ContentItemKinds)
                .expect("test config should allow ContentItemKinds override");
        })
        .build_with_auto_env(&server)
        .await?;

    test.submit_text_turn("inspect request metadata").await?;

    let request = response.single_request();
    let local_input = local_input_for_request(&test.codex, &request).await;
    assert!(has_content_kinds(&local_input, &["user.text"]));
    let input = request.input();
    assert!(input.iter().all(|item| {
        item.pointer("/internal_chat_message_metadata_passthrough/content_item_kinds")
            .is_none()
    }));
    assert!(input.iter().any(|item| {
        item.pointer("/internal_chat_message_metadata_passthrough/turn_id")
            .is_some()
    }));

    Ok(())
}
