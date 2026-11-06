//! Protocol fixtures exercise refusal and identity; they are not a model,
//! Root authorization, or a real Notes application.
use super::*;
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::ThreadItem;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

fn route() -> AgentdTextSessionConfig {
    AgentdTextSessionConfig {
        control_socket: "/fixture/agentd.sock".into(),
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18").unwrap(),
        spawn_generation: 1,
        thread_id: "original-thread".into(),
        app_server_session_id: "original-app-server-session".into(),
        codex_home: "/fixture/home".into(),
    }
}
fn callback() -> DynamicToolCallParams {
    DynamicToolCallParams {
        thread_id: route().thread_id,
        turn_id: "original-turn".into(),
        call_id: "model-call-1".into(),
        namespace: None,
        tool: REPLACE_TOOL.into(),
        arguments: json!({"text":"原线程保存","expected_revision":7}),
    }
}
fn item(params: &DynamicToolCallParams) -> ThreadItem {
    ThreadItem::DynamicToolCall {
        id: params.call_id.clone(),
        namespace: params.namespace.clone(),
        tool: params.tool.clone(),
        arguments: params.arguments.clone(),
        status: DynamicToolCallStatus::InProgress,
        content_items: None,
        success: None,
        duration_ms: None,
    }
}

#[test]
fn original_callback_requires_exact_in_progress_item_and_fixed_thread() {
    let route = route();
    let params = callback();
    let original = item(&params);
    let proof = VerifiedNotesThreadCall::from_original_item(&route, &params, &original).unwrap();
    let id = proof.intent_id(&route).unwrap();
    let mut changed_arguments = params.clone();
    changed_arguments.arguments["text"] = json!("changed text");
    assert!(
        VerifiedNotesThreadCall::from_original_item(&route, &changed_arguments, &original).is_err()
    );
    let changed = VerifiedNotesThreadCall::from_original_item(
        &route,
        &changed_arguments,
        &item(&changed_arguments),
    )
    .unwrap();
    assert_eq!(
        changed.intent_id(&route).unwrap(),
        id,
        "changed arguments cannot create a second operation for the same callback"
    );
    let mut changed_thread = params.clone();
    changed_thread.thread_id = "other-thread".into();
    assert!(
        VerifiedNotesThreadCall::from_original_item(
            &route,
            &changed_thread,
            &item(&changed_thread)
        )
        .is_err()
    );
    let mut completed = original;
    if let ThreadItem::DynamicToolCall { status, .. } = &mut completed {
        *status = DynamicToolCallStatus::Completed;
    }
    assert!(VerifiedNotesThreadCall::from_original_item(&route, &params, &completed).is_err());
    let mut other_turn = params;
    other_turn.turn_id = "different-original-turn".into();
    let other =
        VerifiedNotesThreadCall::from_original_item(&route, &other_turn, &item(&other_turn))
            .unwrap();
    assert_ne!(other.intent_id(&route).unwrap(), id);
}

#[test]
fn model_arguments_cannot_supply_identity_authority_or_a_new_tool_route() {
    let route = route();
    for field in [
        "principal",
        "principal_scope",
        "thread_id",
        "authority",
        "target",
        "operation_id",
        "policy_generation",
    ] {
        let mut params = callback();
        params.arguments[field] = json!("forged");
        assert!(
            VerifiedNotesThreadCall::from_original_item(&route, &params, &item(&params)).is_err(),
            "{field}"
        );
    }
    let mut params = callback();
    params.namespace = Some("forged".into());
    assert!(VerifiedNotesThreadCall::from_original_item(&route, &params, &item(&params)).is_err());
    params = callback();
    params.arguments["text"] = json!("中".repeat(1366));
    assert!(
        VerifiedNotesThreadCall::from_original_item(&route, &params, &item(&params)).is_err(),
        "UTF-8 byte bound applies even when the JSON character bound passes"
    );
    let tools = original_notes_thread_tools();
    assert_eq!(tools.len(), 3);
    for tool in tools {
        let DynamicToolSpec::Function(tool) = tool else {
            panic!("fixed function catalog");
        };
        assert_eq!(tool.input_schema["additionalProperties"], false);
    }
}

#[test]
fn retained_unknown_item_can_only_be_referenced_for_read_only_status() {
    let route = route();
    let params = callback();
    let mut original = item(&params);
    if let ThreadItem::DynamicToolCall {
        status, success, ..
    } = &mut original
    {
        *status = DynamicToolCallStatus::Failed;
        *success = Some(false);
    }
    assert!(VerifiedNotesThreadCall::from_original_item(&route, &params, &original).is_err());
    let observed = VerifiedNotesThreadOperation::from_original_item(
        &route,
        &params.turn_id,
        &params.call_id,
        &original,
    )
    .unwrap();
    let pending =
        VerifiedNotesThreadCall::from_original_item(&route, &params, &item(&params)).unwrap();
    assert_eq!(
        observed.original_item().intent_id(&route).unwrap(),
        pending.intent_id(&route).unwrap()
    );
    assert!(
        VerifiedNotesThreadOperation::from_original_item(
            &route,
            &params.turn_id,
            "different-call",
            &original
        )
        .is_err()
    );
    let mut status = callback();
    status.tool = STATUS_TOOL.into();
    status.arguments = json!({"turn_id":params.turn_id,"call_id":params.call_id});
    assert!(VerifiedNotesThreadCall::from_original_item(&route, &status, &item(&status)).is_ok());
    status.arguments["thread_id"] = json!("forged");
    assert!(VerifiedNotesThreadCall::from_original_item(&route, &status, &item(&status)).is_err());
    assert!(
        VerifiedNotesThreadOperation::from_original_item(
            &route,
            &status.turn_id,
            &status.call_id,
            &item(&status)
        )
        .is_err(),
        "a status item cannot supply a mutation reference"
    );
}

#[test]
fn a_new_call_cannot_escape_the_original_turn_operation_fence() {
    let route = route();
    let first = callback();
    let first = VerifiedNotesThreadCall::from_original_item(&route, &first, &item(&first)).unwrap();
    let mut later = callback();
    later.call_id = "new-call-after-unknown-result".into();
    later.arguments["expected_revision"] = json!(8);
    let later = VerifiedNotesThreadCall::from_original_item(&route, &later, &item(&later)).unwrap();
    assert_eq!(
        first.turn_intent_id(&route).unwrap(),
        later.turn_intent_id(&route).unwrap(),
        "a new call/revision in the same turn must reach the same original writer operation"
    );
    assert_ne!(
        first.intent_id(&route).unwrap(),
        later.intent_id(&route).unwrap(),
        "the signed source must still distinguish and refuse a different original call"
    );
}
