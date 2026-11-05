use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_final_assistant_message_sse_response;
use app_test_support::create_mock_responses_server_sequence;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadBackgroundTerminalsListParams;
use codex_app_server_protocol::ThreadBackgroundTerminalsListResponse;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedParams;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedResponse;
use codex_app_server_protocol::ThreadBackgroundTerminalsTerminateObservedStatus;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use core_test_support::responses;
use serde_json::json;
use std::time::Duration;
use tempfile::TempDir;
use tokio::time::timeout;

#[cfg(windows)]
const READ_TIMEOUT: Duration = Duration::from_secs(25);
#[cfg(not(windows))]
const READ_TIMEOUT: Duration = Duration::from_secs(10);
const METHOD: &str = "thread/backgroundTerminals/terminateObserved";

async fn background_terminals(
    app: &mut TestAppServer,
    thread_id: &str,
) -> Result<ThreadBackgroundTerminalsListResponse> {
    app.request(|request_id| ClientRequest::ThreadBackgroundTerminalsList {
        request_id,
        params: ThreadBackgroundTerminalsListParams {
            thread_id: thread_id.to_string(),
            cursor: None,
            limit: None,
        },
    })
    .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn observed_termination_jsonrpc_reaches_core_and_original_child() -> Result<()> {
    let codex_home = TempDir::new()?;
    // The original App/Core executor starts a real local OS process. The model
    // alone is a mock; no fake process result or manager entry is installed.
    let command = if cfg!(windows) {
        r#"powershell.exe -NoProfile -NonInteractive -Command "Write-Output termination-observed-ready; Start-Sleep -Seconds 60""#
    } else {
        "/bin/sh -c 'printf termination-observed-ready; exec sleep 60'"
    };
    let arguments = serde_json::to_string(&json!({
        "cmd": command,
        "yield_time_ms": 10,
    }))?;
    let model = create_mock_responses_server_sequence(vec![
        responses::sse(vec![
            responses::ev_response_created("termination-observed-command"),
            responses::ev_function_call("original-child", "exec_command", &arguments),
            responses::ev_completed("termination-observed-command"),
        ]),
        create_final_assistant_message_sse_response("background process started")?,
    ])
    .await;
    MockResponsesConfig::new(&model.uri())
        .with_sandbox_mode("danger-full-access")
        .with_provider_config("supports_websockets = false")
        .with_extra_config(
            "[features]\nunified_exec = true\nshell_zsh_fork = false\nunified_exec_zsh_fork = false",
        )
        .write(codex_home.path())?;
    let mut app = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .without_managed_config()
        .build_initialized()
        .await?;

    let result: Result<()> = async {
        let ThreadStartResponse { thread, .. } = app
            .request(|request_id| ClientRequest::ThreadStart {
                request_id,
                params: ThreadStartParams {
                    model: Some("mock-model".to_string()),
                    ..Default::default()
                },
            })
            .await?;
        let TurnStartResponse { turn } = app
            .request(|request_id| ClientRequest::TurnStart {
                request_id,
                params: TurnStartParams {
                    thread_id: thread.id.clone(),
                    input: vec![UserInput::Text {
                        text: "start the background process".to_string(),
                        text_elements: Vec::new(),
                    }],
                    ..Default::default()
                },
            })
            .await?;
        let completed: TurnCompletedNotification =
            timeout(READ_TIMEOUT, app.read_notification("turn/completed")).await??;
        ensure!(completed.turn.id == turn.id, "wrong completed turn");
        ensure!(
            completed.turn.status == TurnStatus::Completed,
            "the original command turn failed: {:?}",
            completed.turn
        );
        // Completing the real initial tool turn releases its initial execution
        // owner before the new cleanup-confirmation operation is admitted.
        let before = background_terminals(&mut app, &thread.id).await?;
        ensure!(before.data.len() == 1, "expected one live original process");
        let process_id = before.data[0].process_id.clone();

        for budget in [None, Some(0_u32)] {
            let mut params = json!({
                "threadId": thread.id,
                "processId": process_id,
            });
            if let Some(budget) = budget {
                params["observationTimeoutMs"] = json!(budget);
            }
            let id = app.send_raw_request(METHOD, Some(params)).await?;
            let error = timeout(
                READ_TIMEOUT,
                app.read_stream_until_error_message(RequestId::Integer(id)),
            )
            .await??;
            ensure!(
                error.error.code == -32600,
                "invalid budget was not rejected"
            );
            let still_live = background_terminals(&mut app, &thread.id).await?;
            ensure!(
                still_live.data.len() == 1,
                "invalid input changed the owner"
            );
            ensure!(
                still_live.data[0].process_id == process_id,
                "invalid input replaced the original process"
            );
        }

        let outcome: ThreadBackgroundTerminalsTerminateObservedResponse = app
            .request(
                |request_id| ClientRequest::ThreadBackgroundTerminalsTerminateObserved {
                    request_id,
                    params: ThreadBackgroundTerminalsTerminateObservedParams {
                        thread_id: thread.id.clone(),
                        process_id: process_id.clone(),
                        observation_timeout_ms: 5_000,
                    },
                },
            )
            .await?;
        ensure!(
            outcome.status == ThreadBackgroundTerminalsTerminateObservedStatus::Confirmed,
            "the original child exit and cleanup were not confirmed"
        );
        ensure!(
            background_terminals(&mut app, &thread.id)
                .await?
                .data
                .is_empty(),
            "the confirmed original process remains listed"
        );
        // This is a new explicit observation after success, never an automatic
        // retry of an unknown result. The removed entry cannot produce a second confirmation.
        let after: ThreadBackgroundTerminalsTerminateObservedResponse = app
            .request(
                |request_id| ClientRequest::ThreadBackgroundTerminalsTerminateObserved {
                    request_id,
                    params: ThreadBackgroundTerminalsTerminateObservedParams {
                        thread_id: thread.id.clone(),
                        process_id,
                        observation_timeout_ms: 5_000,
                    },
                },
            )
            .await?;
        ensure!(
            after.status == ThreadBackgroundTerminalsTerminateObservedStatus::NotConfirmed,
            "a missing original owner was falsely confirmed"
        );
        Ok(())
    }
    .await;

    // Attempt original App teardown even when a diagnostic assertion fails.
    // Preserve the first failure; a teardown result is never process confirmation.
    let shutdown = timeout(READ_TIMEOUT, app.shutdown_gracefully()).await;
    if result.is_err() {
        eprintln!("observed-termination fixture shutdown: {shutdown:?}");
    }
    result?;
    ensure!(
        shutdown.context("app shutdown timed out")??.success(),
        "app shutdown failed"
    );
    Ok(())
}
