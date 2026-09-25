#![cfg(unix)]

use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_command_execution_sse_response;
use app_test_support::create_final_assistant_message_sse_response;
use app_test_support::create_mock_responses_server_sequence_unchecked;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::JSONRPCError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerRequest;
use codex_app_server_protocol::ThreadHistoryMode;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadQueueAddParams;
use codex_app_server_protocol::ThreadQueueAddResponse;
use codex_app_server_protocol::ThreadQueueListParams;
use codex_app_server_protocol::ThreadQueueListResponse;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::ThreadTurnsListParams;
use codex_app_server_protocol::ThreadTurnsListResponse;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnEnvironmentParams;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnInterruptResponse;
use codex_app_server_protocol::TurnRecoverParams;
use codex_app_server_protocol::TurnRecoverResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_features::Feature;
use codex_utils_absolute_path::AbsolutePathBuf;
use core_test_support::responses as test_responses;
use core_test_support::skip_if_remote;
use tempfile::TempDir;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::Respond;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;

const READ_TIMEOUT: Duration = Duration::from_secs(10);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(25);
const INVALID_REQUEST_ERROR_CODE: i64 = -32600;
const FIRST_RESPONSE_DELAY: Duration = Duration::from_secs(30);
const STABLE_CLIENT_ID: &str = "recover-stable-client-message";
const ORIGINAL_USER_TEXT: &str = "continue this exact interrupted turn";

#[tokio::test]
async fn turn_recover_requires_hepta_turn_recovery_feature() -> Result<()> {
    let server = MockServer::start().await;
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_root_config(r#"approvals_reviewer = "user""#)
        .write(codex_home.path())?;
    let mut app = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    let thread_id = start_thread(&mut app).await?;

    let error = recover_error(&mut app, &thread_id, "disabled-feature-turn").await?;
    assert_eq!(error.error.code, INVALID_REQUEST_ERROR_CODE);
    assert_eq!(
        error.error.message,
        "turn/recover requires features.hepta_turn_recovery=true"
    );
    assert!(model_requests(&server).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn recover_rejects_busy_completed_and_cross_thread_turns() -> Result<()> {
    skip_if_remote!(Ok(()), "uses a host-local approval-blocked command fixture");

    let server = create_mock_responses_server_sequence_unchecked(vec![
        blocked_turn_response("recover-busy-command")?,
        create_final_assistant_message_sse_response("completed normally")?,
    ])
    .await;
    let (mut app, _codex_home) = configured_app(&server).await?;

    let busy_thread = start_thread(&mut app).await?;
    let busy_turn = start_turn(
        &mut app,
        &busy_thread,
        "keep this turn waiting for approval",
        Some("busy-client-id"),
    )
    .await?;
    let approval = timeout(READ_TIMEOUT, app.read_stream_until_request_message()).await??;
    assert!(matches!(
        approval,
        ServerRequest::CommandExecutionRequestApproval { .. }
    ));

    let busy_error = recover_error(&mut app, &busy_thread, &busy_turn).await?;
    assert_eq!(busy_error.error.code, INVALID_REQUEST_ERROR_CODE);
    assert!(busy_error.error.message.contains("not interrupted"));

    let completed_thread = start_thread(&mut app).await?;
    let completed_turn = start_turn(
        &mut app,
        &completed_thread,
        "finish this turn",
        Some("completed-client-id"),
    )
    .await?;
    let completed: TurnCompletedNotification =
        timeout(READ_TIMEOUT, app.read_notification("turn/completed")).await??;
    assert_eq!(completed.turn.id, completed_turn);
    assert_eq!(completed.turn.status, TurnStatus::Completed);

    let completed_error = recover_error(&mut app, &completed_thread, &completed_turn).await?;
    assert_eq!(completed_error.error.code, INVALID_REQUEST_ERROR_CODE);
    assert!(completed_error.error.message.contains("not interrupted"));

    let _: TurnInterruptResponse = app
        .request(|request_id| ClientRequest::TurnInterrupt {
            request_id,
            params: TurnInterruptParams {
                thread_id: busy_thread.clone(),
                turn_id: busy_turn.clone(),
            },
        })
        .await?;
    let interrupted: TurnCompletedNotification =
        timeout(READ_TIMEOUT, app.read_notification("turn/completed")).await??;
    assert_eq!(interrupted.turn.id, busy_turn);
    assert_eq!(interrupted.turn.status, TurnStatus::Interrupted);

    let approval_pending_error = recover_error(&mut app, &busy_thread, &busy_turn).await?;
    assert_eq!(
        approval_pending_error.error.code,
        INVALID_REQUEST_ERROR_CODE
    );
    assert!(
        approval_pending_error
            .error
            .message
            .contains("not interrupted")
    );

    let cross_thread_error = recover_error(&mut app, &completed_thread, &busy_turn).await?;
    assert_eq!(cross_thread_error.error.code, INVALID_REQUEST_ERROR_CODE);
    assert!(
        cross_thread_error
            .error
            .message
            .contains("is not the interrupted tail")
    );

    let model_requests = model_requests(&server).await?;
    assert_eq!(model_requests.len(), 2, "rejected recovery must not sample");
    Ok(())
}

#[tokio::test]
async fn cold_sigkill_recovery_preserves_turn_and_deduplicates_stable_queue_input() -> Result<()> {
    skip_if_remote!(
        Ok(()),
        "kills a host-local app-server child before its first provider response"
    );

    let server = create_delayed_first_responses_server(vec![
        create_final_assistant_message_sse_response("first response must never arrive")?,
        create_final_assistant_message_sse_response("recovered successfully")?,
        create_final_assistant_message_sse_response("next turn consumed resume hook")?,
    ])
    .await;
    let (mut first, codex_home) = configured_app_with_resume_hook(&server).await?;
    let persistent_workspace = recovery_workspace(&codex_home, "legacy")?;
    let ThreadStartResponse {
        thread,
        runtime_workspace_roots: original_runtime_workspace_roots,
        ..
    } = start_thread_with_persistent_environment(
        &mut first,
        persistent_workspace.clone(),
        /*history_mode*/ None,
    )
    .await?;
    let thread_id = thread.id;
    assert!(
        !original_runtime_workspace_roots.is_empty(),
        "automatic test environment must exercise persisted runtime workspace roots"
    );
    let turn_id = start_turn(
        &mut first,
        &thread_id,
        ORIGINAL_USER_TEXT,
        Some(STABLE_CLIENT_ID),
    )
    .await?;
    wait_for_model_request_count(&server, 1).await?;

    let queued: ThreadQueueAddResponse = first
        .request(|request_id| ClientRequest::ThreadQueueAdd {
            request_id,
            params: ThreadQueueAddParams {
                thread_id: thread_id.clone(),
                input: vec![text(ORIGINAL_USER_TEXT)],
                client_user_message_id: STABLE_CLIENT_ID.to_string(),
            },
        })
        .await?;
    assert_eq!(
        queued.queued_submission.client_user_message_id,
        STABLE_CLIENT_ID
    );
    assert_eq!(list_queue(&mut first, &thread_id).await?.data.len(), 1);

    // SIGKILL leaves no TurnAborted event. The request has crossed its durable
    // Ready boundary, but no provider event has reached Core, so turn/recover
    // may safely qualify the stale InProgress tail.
    first.kill_ungracefully().await?;
    drop(first);

    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    let resume_id = restarted
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread_id.clone(),
            config: Some(HashMap::from([(
                "bypass_hook_trust".to_string(),
                serde_json::json!(true),
            )])),
            ..Default::default()
        })
        .await?;
    let resumed: ThreadResumeResponse =
        timeout(READ_TIMEOUT, restarted.read_response(resume_id)).await??;
    assert_eq!(resumed.thread.id, thread_id);
    assert_eq!(
        resumed.runtime_workspace_roots, original_runtime_workspace_roots,
        "cold resume without an override must hydrate roots from persisted turn context"
    );
    let resumed_tail = resumed
        .thread
        .turns
        .last()
        .context("cold resume should expose the stale turn tail")?;
    assert_eq!(resumed_tail.id, turn_id);
    assert_eq!(resumed_tail.status, TurnStatus::Interrupted);

    let queued_before_recovery = list_queue(&mut restarted, &thread_id).await?;
    assert_eq!(
        queued_before_recovery.data,
        vec![queued.queued_submission],
        "cold resume must preserve recovery priority over queued input"
    );
    assert_eq!(
        model_requests(&server).await?.len(),
        1,
        "cold resume must not dispatch or reconcile the queue before recovery"
    );

    let recovered: TurnRecoverResponse = restarted
        .request(|request_id| ClientRequest::TurnRecover {
            request_id,
            params: TurnRecoverParams {
                thread_id: thread_id.clone(),
                turn_id: turn_id.clone(),
            },
        })
        .await?;
    assert_eq!(recovered.turn.id, turn_id);
    assert_eq!(recovered.turn.status, TurnStatus::InProgress);

    let completed: TurnCompletedNotification =
        timeout(READ_TIMEOUT, restarted.read_notification("turn/completed")).await??;
    assert_eq!(completed.thread_id, thread_id);
    assert_eq!(completed.turn.id, turn_id);
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    wait_for_queue_empty(&mut restarted, &thread_id).await?;
    let hook_log = codex_home.path().join("resume_session_start_hook.jsonl");
    assert!(
        !hook_log.exists(),
        "cold recovery must preserve the pending resume SessionStart hook"
    );

    let next_turn_id = start_turn(
        &mut restarted,
        &thread_id,
        "start a genuinely new turn",
        Some("post-recovery-client-id"),
    )
    .await?;
    let next_completed: TurnCompletedNotification =
        timeout(READ_TIMEOUT, restarted.read_notification("turn/completed")).await??;
    assert_eq!(next_completed.turn.id, next_turn_id);
    let hook_inputs = fs::read_to_string(&hook_log)?
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(serde_json::from_str::<serde_json::Value>)
        .collect::<serde_json::Result<Vec<_>>>()?;
    assert_eq!(hook_inputs.len(), 1);
    assert_eq!(hook_inputs[0]["source"].as_str(), Some("resume"));

    let read: ThreadReadResponse = restarted
        .request(|request_id| ClientRequest::ThreadRead {
            request_id,
            params: ThreadReadParams {
                thread_id: thread_id.clone(),
                include_turns: true,
            },
        })
        .await?;
    assert_eq!(
        read.thread
            .turns
            .iter()
            .filter(|turn| turn.id == turn_id)
            .count(),
        1,
        "recovery must reopen one logical turn instead of duplicating its id"
    );
    let stable_user_items = read
        .thread
        .turns
        .iter()
        .flat_map(|turn| turn.items.iter())
        .filter(|item| {
            matches!(
                item,
                ThreadItem::UserMessage {
                    client_id: Some(client_id),
                    ..
                } if client_id == STABLE_CLIENT_ID
            )
        })
        .count();
    assert_eq!(stable_user_items, 1, "recovery must not add a user item");

    let requests = model_requests(&server).await?;
    assert_eq!(
        requests.len(),
        3,
        "recovery and the next new turn should each add one model request"
    );
    let recovered_body = requests[1].body_json::<serde_json::Value>()?;
    assert_eq!(
        count_exact_strings(&recovered_body, ORIGINAL_USER_TEXT),
        1,
        "recovered model context must contain the original user message once"
    );
    Ok(())
}

#[tokio::test]
async fn cold_resume_explicit_workspace_roots_override_is_fail_closed_for_recovery() -> Result<()> {
    skip_if_remote!(
        Ok(()),
        "kills a host-local app-server child before testing recovery context drift"
    );

    let server =
        create_delayed_first_responses_server(vec![create_final_assistant_message_sse_response(
            "first response must never arrive",
        )?])
        .await;
    let (mut first, codex_home) = configured_app(&server).await?;
    let persistent_workspace = recovery_workspace(&codex_home, "root-drift")?;
    let ThreadStartResponse {
        thread,
        runtime_workspace_roots: original_runtime_workspace_roots,
        ..
    } = start_thread_with_persistent_environment(
        &mut first,
        persistent_workspace,
        /*history_mode*/ None,
    )
    .await?;
    let thread_id = thread.id;
    let turn_id = start_turn(
        &mut first,
        &thread_id,
        "reject recovery after an explicit workspace-root change",
        Some("workspace-root-drift-client-id"),
    )
    .await?;
    wait_for_model_request_count(&server, 1).await?;

    first.kill_ungracefully().await?;
    drop(first);

    let override_root_dir = TempDir::new()?;
    let override_root = AbsolutePathBuf::try_from(override_root_dir.path().to_path_buf())?;
    assert!(
        !original_runtime_workspace_roots.contains(&override_root),
        "explicit override fixture must differ from persisted roots"
    );
    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    let resume_id = restarted
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread_id.clone(),
            runtime_workspace_roots: Some(vec![override_root.clone()]),
            ..Default::default()
        })
        .await?;
    let resumed: ThreadResumeResponse =
        timeout(READ_TIMEOUT, restarted.read_response(resume_id)).await??;
    assert_eq!(
        resumed.runtime_workspace_roots,
        vec![override_root],
        "explicit runtime workspace roots must take precedence over persisted roots"
    );

    let error = recover_error(&mut restarted, &thread_id, &turn_id).await?;
    assert_eq!(error.error.code, INVALID_REQUEST_ERROR_CODE);
    assert!(
        error.error.message.contains("recovery"),
        "unexpected recovery drift error: {}",
        error.error.message
    );
    assert_eq!(
        model_requests(&server).await?.len(),
        1,
        "workspace-root drift must fail closed before another physical provider send"
    );
    Ok(())
}

#[tokio::test]
async fn cold_resume_explicit_cwd_override_is_fail_closed_for_recovery() -> Result<()> {
    skip_if_remote!(
        Ok(()),
        "kills a host-local app-server child before testing recovery cwd drift"
    );

    let server =
        create_delayed_first_responses_server(vec![create_final_assistant_message_sse_response(
            "first response must never arrive",
        )?])
        .await;
    let (mut first, codex_home) = configured_app(&server).await?;
    let persistent_workspace = recovery_workspace(&codex_home, "cwd-drift")?;
    let ThreadStartResponse { thread, .. } = start_thread_with_persistent_environment(
        &mut first,
        persistent_workspace.clone(),
        /*history_mode*/ None,
    )
    .await?;
    let thread_id = thread.id;
    let turn_id = start_turn(
        &mut first,
        &thread_id,
        "reject recovery after an explicit cwd change",
        Some("cwd-drift-client-id"),
    )
    .await?;
    wait_for_model_request_count(&server, 1).await?;

    first.kill_ungracefully().await?;
    drop(first);

    let override_cwd_dir = TempDir::new()?;
    let override_cwd = AbsolutePathBuf::try_from(override_cwd_dir.path().to_path_buf())?;
    assert_ne!(override_cwd, persistent_workspace);
    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    let resume_id = restarted
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread_id.clone(),
            cwd: Some(override_cwd.as_path().display().to_string()),
            ..Default::default()
        })
        .await?;
    let resumed: ThreadResumeResponse =
        timeout(READ_TIMEOUT, restarted.read_response(resume_id)).await??;
    assert_eq!(
        resumed.cwd, override_cwd,
        "explicit cwd must take precedence over the persisted recovery environment"
    );

    let error = recover_error(&mut restarted, &thread_id, &turn_id).await?;
    assert_eq!(error.error.code, INVALID_REQUEST_ERROR_CODE);
    assert!(
        error.error.message.contains("no longer valid"),
        "unexpected terminal recovery drift error: {}",
        error.error.message
    );
    assert_eq!(
        model_requests(&server).await?.len(),
        1,
        "cwd drift must fail closed before another physical provider send"
    );
    Ok(())
}

#[tokio::test]
async fn cold_sigkill_after_provider_output_is_not_recoverable() -> Result<()> {
    skip_if_remote!(
        Ok(()),
        "kills a host-local app-server child after provider output"
    );

    let server = create_mock_responses_server_sequence_unchecked(vec![blocked_turn_response(
        "nonrecoverable-command",
    )?])
    .await;
    let (mut first, codex_home) = configured_app(&server).await?;
    let thread_id = start_thread(&mut first).await?;
    let turn_id = start_turn(
        &mut first,
        &thread_id,
        "provider output closes recovery",
        Some("nonrecoverable-client-id"),
    )
    .await?;
    let approval = timeout(READ_TIMEOUT, first.read_stream_until_request_message()).await??;
    assert!(matches!(
        approval,
        ServerRequest::CommandExecutionRequestApproval { .. }
    ));

    first.kill_ungracefully().await?;
    drop(first);

    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    let resume_id = restarted
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread_id.clone(),
            ..Default::default()
        })
        .await?;
    let _: ThreadResumeResponse =
        timeout(READ_TIMEOUT, restarted.read_response(resume_id)).await??;

    let error = recover_error(&mut restarted, &thread_id, &turn_id).await?;
    assert_eq!(error.error.code, INVALID_REQUEST_ERROR_CODE);
    assert!(error.error.message.contains("not interrupted"));
    assert_eq!(model_requests(&server).await?.len(), 1);
    Ok(())
}

#[tokio::test]
async fn cold_paginated_sigkill_recovery_uses_canonical_context_tail() -> Result<()> {
    skip_if_remote!(
        Ok(()),
        "kills a host-local app-server child with paginated history"
    );

    let server = create_delayed_first_responses_server(vec![
        create_final_assistant_message_sse_response("paginated first response must not arrive")?,
        create_final_assistant_message_sse_response("paginated recovery completed")?,
    ])
    .await;
    let (mut first, codex_home) = configured_app(&server).await?;
    let persistent_workspace = recovery_workspace(&codex_home, "paginated")?;
    let ThreadStartResponse {
        thread,
        runtime_workspace_roots: original_runtime_workspace_roots,
        ..
    } = start_thread_with_persistent_environment(
        &mut first,
        persistent_workspace.clone(),
        Some(ThreadHistoryMode::Paginated),
    )
    .await?;
    let thread_id = thread.id;
    let turn_id = start_turn(
        &mut first,
        &thread_id,
        "recover the paginated turn",
        Some("paginated-recovery-client-id"),
    )
    .await?;
    wait_for_model_request_count(&server, 1).await?;

    first.kill_ungracefully().await?;
    drop(first);

    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    let resume_id = restarted
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread_id.clone(),
            ..Default::default()
        })
        .await?;
    let resumed: ThreadResumeResponse =
        timeout(READ_TIMEOUT, restarted.read_response(resume_id)).await??;
    assert_eq!(
        resumed.runtime_workspace_roots, original_runtime_workspace_roots,
        "paginated cold resume must hydrate roots from canonical turn context"
    );
    let resumed_tail = resumed
        .thread
        .turns
        .last()
        .context("paginated cold resume should expose the stale tail")?;
    assert_eq!(resumed_tail.id, turn_id);
    assert_eq!(resumed_tail.status, TurnStatus::Interrupted);

    let recovered: TurnRecoverResponse = restarted
        .request(|request_id| ClientRequest::TurnRecover {
            request_id,
            params: TurnRecoverParams {
                thread_id: thread_id.clone(),
                turn_id: turn_id.clone(),
            },
        })
        .await?;
    assert_eq!(recovered.turn.id, turn_id);
    assert_eq!(recovered.turn.status, TurnStatus::InProgress);

    let completed: TurnCompletedNotification =
        timeout(READ_TIMEOUT, restarted.read_notification("turn/completed")).await??;
    assert_eq!(completed.thread_id, thread_id);
    assert_eq!(completed.turn.id, turn_id);
    assert_eq!(completed.turn.status, TurnStatus::Completed);

    let turns: ThreadTurnsListResponse = restarted
        .request(|request_id| ClientRequest::ThreadTurnsList {
            request_id,
            params: ThreadTurnsListParams {
                thread_id: thread_id.clone(),
                cursor: None,
                limit: Some(20),
                sort_direction: None,
                items_view: None,
            },
        })
        .await?;
    assert_eq!(
        turns.data.iter().filter(|turn| turn.id == turn_id).count(),
        1,
        "paginated recovery must preserve one logical turn identity"
    );
    assert_eq!(model_requests(&server).await?.len(), 2);
    Ok(())
}

#[tokio::test]
async fn same_process_ephemeral_interrupted_turn_recovers_from_listener_state() -> Result<()> {
    skip_if_remote!(Ok(()), "uses a host-local approval-blocked command fixture");

    let server = create_delayed_first_responses_server(vec![
        create_final_assistant_message_sse_response("ephemeral first response must not arrive")?,
        create_final_assistant_message_sse_response("ephemeral recovery completed")?,
    ])
    .await;
    let (mut app, _codex_home) = configured_app(&server).await?;
    let ThreadStartResponse { thread, .. } = app
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ephemeral: Some(true),
            ..Default::default()
        })
        .await?;
    let thread_id = thread.id;
    let turn_id = start_turn(
        &mut app,
        &thread_id,
        "recover this ephemeral turn",
        Some("ephemeral-recovery-client-id"),
    )
    .await?;
    wait_for_model_request_count(&server, 1).await?;

    let _: TurnInterruptResponse = app
        .request(|request_id| ClientRequest::TurnInterrupt {
            request_id,
            params: TurnInterruptParams {
                thread_id: thread_id.clone(),
                turn_id: turn_id.clone(),
            },
        })
        .await?;
    let interrupted: TurnCompletedNotification =
        timeout(READ_TIMEOUT, app.read_notification("turn/completed")).await??;
    assert_eq!(interrupted.turn.id, turn_id);
    assert_eq!(interrupted.turn.status, TurnStatus::Interrupted);

    let recovered: TurnRecoverResponse = app
        .request(|request_id| ClientRequest::TurnRecover {
            request_id,
            params: TurnRecoverParams {
                thread_id: thread_id.clone(),
                turn_id: turn_id.clone(),
            },
        })
        .await?;
    assert_eq!(recovered.turn.id, turn_id);
    assert_eq!(recovered.turn.status, TurnStatus::InProgress);

    let completed: TurnCompletedNotification =
        timeout(READ_TIMEOUT, app.read_notification("turn/completed")).await??;
    assert_eq!(completed.thread_id, thread_id);
    assert_eq!(completed.turn.id, turn_id);
    assert_eq!(completed.turn.status, TurnStatus::Completed);

    let requests = model_requests(&server).await?;
    assert_eq!(requests.len(), 2);
    let recovered_body = requests[1].body_json::<serde_json::Value>()?;
    assert_eq!(
        count_exact_strings(&recovered_body, "recover this ephemeral turn"),
        1,
        "ephemeral recovery must not inject new user input"
    );
    Ok(())
}

async fn configured_app(server: &MockServer) -> Result<(TestAppServer, TempDir)> {
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_approval_policy("untrusted")
        .enable_feature(Feature::HeptaTurnRecovery)
        .with_root_config(r#"approvals_reviewer = "user""#)
        .write(codex_home.path())?;
    let app = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    Ok((app, codex_home))
}

async fn configured_app_with_resume_hook(server: &MockServer) -> Result<(TestAppServer, TempDir)> {
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_approval_policy("untrusted")
        .enable_feature(Feature::HeptaTurnRecovery)
        .with_root_config(r#"approvals_reviewer = "user""#)
        .write(codex_home.path())?;
    write_resume_session_start_hook(codex_home.path())?;
    let app = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .build_initialized_with_timeout(STARTUP_TIMEOUT)
        .await?;
    Ok((app, codex_home))
}

fn write_resume_session_start_hook(codex_home: &Path) -> Result<()> {
    let script_path = codex_home.join("resume_session_start_hook.py");
    let log_path = codex_home.join("resume_session_start_hook.jsonl");
    let script = format!(
        r#"import json
from pathlib import Path
import sys

payload = json.load(sys.stdin)
with Path(r"{log_path}").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload) + "\n")
"#,
        log_path = log_path.display(),
    );
    let hooks = serde_json::json!({
        "hooks": {
            "SessionStart": [{
                "matcher": "resume",
                "hooks": [{
                    "type": "command",
                    "command": format!("python3 {}", script_path.display()),
                }]
            }]
        }
    });
    fs::write(script_path, script)?;
    fs::write(codex_home.join("hooks.json"), hooks.to_string())?;
    Ok(())
}

async fn start_thread(app: &mut TestAppServer) -> Result<String> {
    Ok(start_thread_with_runtime_workspace_roots(app).await?.0)
}

async fn start_thread_with_runtime_workspace_roots(
    app: &mut TestAppServer,
) -> Result<(String, Vec<AbsolutePathBuf>)> {
    let ThreadStartResponse {
        thread,
        runtime_workspace_roots,
        ..
    } = app
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;
    Ok((thread.id, runtime_workspace_roots))
}

fn recovery_workspace(codex_home: &TempDir, name: &str) -> Result<AbsolutePathBuf> {
    let workspace = codex_home.path().join(format!("recovery-workspace-{name}"));
    fs::create_dir_all(&workspace)?;
    Ok(AbsolutePathBuf::try_from(workspace)?)
}

async fn start_thread_with_persistent_environment(
    app: &mut TestAppServer,
    workspace: AbsolutePathBuf,
    history_mode: Option<ThreadHistoryMode>,
) -> Result<ThreadStartResponse> {
    let environment_id = app.auto_env_params()?.environment_id;
    let request_id = app
        .send_thread_start_request(ThreadStartParams {
            model: Some("mock-model".to_string()),
            history_mode,
            environments: Some(vec![TurnEnvironmentParams {
                environment_id,
                cwd: workspace.into(),
                runtime_workspace_roots: None,
            }]),
            ..Default::default()
        })
        .await?;
    timeout(READ_TIMEOUT, app.read_response(request_id)).await?
}

async fn start_turn(
    app: &mut TestAppServer,
    thread_id: &str,
    input: &str,
    client_user_message_id: Option<&str>,
) -> Result<String> {
    let TurnStartResponse { turn } = app
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread_id.to_string(),
                client_user_message_id: client_user_message_id.map(str::to_string),
                input: vec![text(input)],
                ..Default::default()
            },
        })
        .await?;
    Ok(turn.id)
}

async fn recover_error(
    app: &mut TestAppServer,
    thread_id: &str,
    turn_id: &str,
) -> Result<JSONRPCError> {
    let request_id = app
        .send_raw_request(
            "turn/recover",
            Some(serde_json::json!({
                "threadId": thread_id,
                "turnId": turn_id,
            })),
        )
        .await?;
    timeout(
        READ_TIMEOUT,
        app.read_stream_until_error_message(RequestId::Integer(request_id)),
    )
    .await?
}

async fn list_queue(app: &mut TestAppServer, thread_id: &str) -> Result<ThreadQueueListResponse> {
    app.request(|request_id| ClientRequest::ThreadQueueList {
        request_id,
        params: ThreadQueueListParams {
            thread_id: thread_id.to_string(),
            cursor: None,
            limit: None,
        },
    })
    .await
}

async fn wait_for_queue_empty(app: &mut TestAppServer, thread_id: &str) -> Result<()> {
    timeout(READ_TIMEOUT, async {
        loop {
            if list_queue(app, thread_id).await?.data.is_empty() {
                return Ok::<(), anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await??;
    Ok(())
}

async fn create_delayed_first_responses_server(responses: Vec<String>) -> MockServer {
    let server = test_responses::start_mock_server().await;
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(DelayedFirstSeqResponder {
            calls: AtomicUsize::new(0),
            responses,
        })
        .mount(&server)
        .await;
    server
}

struct DelayedFirstSeqResponder {
    calls: AtomicUsize,
    responses: Vec<String>,
}

impl Respond for DelayedFirstSeqResponder {
    fn respond(&self, _request: &wiremock::Request) -> ResponseTemplate {
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        let response = self
            .responses
            .get(call)
            .expect("mock model response should exist");
        let response = test_responses::sse_response(response.clone());
        if call == 0 {
            response.set_delay(FIRST_RESPONSE_DELAY)
        } else {
            response
        }
    }
}

async fn wait_for_model_request_count(server: &MockServer, expected: usize) -> Result<()> {
    timeout(READ_TIMEOUT, async {
        loop {
            if model_requests(server).await?.len() >= expected {
                return Ok::<(), anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await??;
    Ok(())
}

async fn model_requests(server: &MockServer) -> Result<Vec<wiremock::Request>> {
    Ok(server
        .received_requests()
        .await
        .context("mock request capture unavailable")?
        .into_iter()
        .filter(|request| request.url.path().ends_with("/responses"))
        .collect())
}

fn blocked_turn_response(call_id: &str) -> Result<String> {
    create_command_execution_sse_response(
        vec![
            "python3".to_string(),
            "-c".to_string(),
            "import time; time.sleep(10)".to_string(),
        ],
        /*workdir*/ None,
        /*timeout_ms*/ Some(10_000),
        call_id,
    )
}

fn text(value: &str) -> UserInput {
    UserInput::Text {
        text: value.to_string(),
        text_elements: Vec::new(),
    }
}

fn count_exact_strings(value: &serde_json::Value, expected: &str) -> usize {
    match value {
        serde_json::Value::String(value) => usize::from(value == expected),
        serde_json::Value::Array(values) => values
            .iter()
            .map(|value| count_exact_strings(value, expected))
            .sum(),
        serde_json::Value::Object(values) => values
            .values()
            .map(|value| count_exact_strings(value, expected))
            .sum(),
        _ => 0,
    }
}
