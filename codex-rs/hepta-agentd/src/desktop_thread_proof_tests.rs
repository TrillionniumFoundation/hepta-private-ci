//! Original protocol DTO fixtures only; no Root grant, Core persistence or GUI qualification.
use super::*;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

fn route() -> AgentdTextSessionConfig {
    AgentdTextSessionConfig {
        control_socket: "/fixture/agentd.sock".into(),
        agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18").unwrap(),
        spawn_generation: 1,
        thread_id: "original-thread".into(),
        app_server_session_id: "original-session".into(),
        codex_home: "/fixture/home".into(),
    }
}
fn callback(tool: &str) -> DynamicToolCallParams {
    DynamicToolCallParams {
        thread_id: route().thread_id,
        turn_id: "same-turn".into(),
        call_id: "original-call".into(),
        namespace: None,
        tool: tool.into(),
        arguments: if tool == REPLACE_TOOL {
            json!({"text":"原文","expected_revision":0})
        } else {
            json!({"left":"12","operator":"add","right":"30","expected_revision":0})
        },
    }
}
fn item(params: &DynamicToolCallParams, status: DynamicToolCallStatus) -> ThreadItem {
    ThreadItem::DynamicToolCall {
        id: params.call_id.clone(),
        namespace: params.namespace.clone(),
        tool: params.tool.clone(),
        arguments: params.arguments.clone(),
        status,
        content_items: None,
        success: None,
        duration_ms: None,
    }
}

#[test]
fn each_app_requires_current_exact_callback_but_can_observe_its_completed_original_item() {
    let route = route();
    for tool in [REPLACE_TOOL, CALCULATOR_EVALUATE_TOOL] {
        let params = callback(tool);
        let original = item(&params, DynamicToolCallStatus::InProgress);
        let call =
            VerifiedDesktopThreadCall::from_original_item(&route, &params, &original).unwrap();
        assert_eq!(call.recorded_reference(&route).tool, tool);
        let mut changed = params.clone();
        changed.arguments["expected_revision"] = json!(1);
        assert!(
            VerifiedDesktopThreadCall::from_original_item(&route, &changed, &original).is_err()
        );
        let completed = item(&params, DynamicToolCallStatus::Completed);
        assert!(
            VerifiedDesktopThreadCall::from_original_item(&route, &params, &completed).is_err()
        );
        let observed = VerifiedDesktopThreadOperation::from_original_item(
            &route,
            &params.turn_id,
            &params.call_id,
            &completed,
        )
        .unwrap();
        assert_eq!(
            observed.original_item().callback_digest(),
            call.callback_digest()
        );
        assert_eq!(observed.original_item().tool(), tool);
    }
}

#[test]
fn neither_app_can_choose_authority_or_replace_the_original_callback_route() {
    for tool in [REPLACE_TOOL, CALCULATOR_EVALUATE_TOOL] {
        for field in [
            "principal",
            "authority",
            "target",
            "destination_id",
            "operation_id",
            "policy_generation",
        ] {
            let mut params = callback(tool);
            params.arguments[field] = json!("not-a-capability");
            assert!(
                VerifiedDesktopThreadCall::from_original_item(
                    &route(),
                    &params,
                    &item(&params, DynamicToolCallStatus::InProgress)
                )
                .is_err()
            );
        }
        let mut params = callback(tool);
        params.thread_id = "foreign-thread".into();
        assert!(
            VerifiedDesktopThreadCall::from_original_item(
                &route(),
                &params,
                &item(&params, DynamicToolCallStatus::InProgress)
            )
            .is_err()
        );
        params = callback(tool);
        params.namespace = Some("foreign-namespace".into());
        assert!(
            VerifiedDesktopThreadCall::from_original_item(
                &route(),
                &params,
                &item(&params, DynamicToolCallStatus::InProgress)
            )
            .is_err()
        );
    }
}

#[test]
fn actual_callback_decoder_enforces_canonical_operands_and_app_specific_status_selection() {
    for left in ["+12", "012", "-0", " 12", "", "9223372036854775808"] {
        let mut params = callback(CALCULATOR_EVALUATE_TOOL);
        params.arguments["left"] = json!(left);
        assert!(
            VerifiedDesktopThreadCall::validate_callback(&route(), &params).is_err(),
            "{left}"
        );
    }
    for left in ["0", "-12", "-9223372036854775808", "9223372036854775807"] {
        let mut params = callback(CALCULATOR_EVALUATE_TOOL);
        params.arguments["left"] = json!(left);
        assert!(
            VerifiedDesktopThreadCall::validate_callback(&route(), &params).is_ok(),
            "{left}"
        );
    }
    let mut text = callback(REPLACE_TOOL);
    text.arguments["text"] = json!("中".repeat(1366));
    assert!(VerifiedDesktopThreadCall::validate_callback(&route(), &text).is_err());
    for (tool, selector, wrong) in [
        (
            STATUS_TOOL,
            "latest_original_replace",
            "latest_original_evaluate",
        ),
        (
            CALCULATOR_STATUS_TOOL,
            "latest_original_evaluate",
            "latest_original_replace",
        ),
    ] {
        let mut params = callback(tool);
        params.arguments = json!({"selector":{"kind":selector}});
        assert!(VerifiedDesktopThreadCall::validate_callback(&route(), &params).is_ok());
        params.arguments = json!({"selector":{"kind":wrong}});
        assert!(VerifiedDesktopThreadCall::validate_callback(&route(), &params).is_err());
    }
}
