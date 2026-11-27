use super::*;
use pretty_assertions::assert_eq;

#[derive(Clone, Copy)]
enum RequestedExecution {
    Managed,
    ExplicitlyUnsandboxed,
}

#[test_case(RequestedExecution::Managed; "approved_unavailable_cannot_escalate")]
#[test_case(RequestedExecution::ExplicitlyUnsandboxed; "explicit_unsandboxed_still_writes")]
#[tokio::test]
async fn apply_patch_preserves_requested_execution(execution: RequestedExecution) -> Result<()> {
    skip_if_remote!(
        Ok(()),
        "fixture files and unavailable Windows executor are local"
    );
    skip_if_no_network!(Ok(()));

    let directory = TempDir::new()?;
    let codex_home = directory.path().join("codex_home");
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&codex_home)?;
    std::fs::create_dir(&workspace)?;
    let patch = "*** Begin Patch\n*** Add File: must-not-escalate.txt\n+content\n*** End Patch\n";
    let server = create_mock_responses_server_sequence(vec![
        create_apply_patch_sse_response(patch, "patch-call")?,
        create_final_assistant_message_sse_response("done")?,
    ])
    .await;
    let sandbox_mode = match execution {
        RequestedExecution::Managed => "read-only",
        RequestedExecution::ExplicitlyUnsandboxed => "danger-full-access",
    };
    MockResponsesConfig::new(&server.uri())
        .with_approval_policy("on-request")
        .with_sandbox_mode(sandbox_mode)
        .write(&codex_home)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(&codex_home)
        .build_initialized()
        .await?;
    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            cwd: Some(workspace.to_string_lossy().into_owned()),
            ..Default::default()
        })
        .await?;
    let TurnStartResponse { turn } = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread.id.clone(),
                input: vec![V2UserInput::Text {
                    text: "apply the patch".to_string(),
                    text_elements: Vec::new(),
                }],
                cwd: Some(workspace.clone()),
                ..Default::default()
            },
        })
        .await?;

    if matches!(execution, RequestedExecution::Managed) {
        let request = timeout(
            DEFAULT_READ_TIMEOUT,
            mcp.read_stream_until_request_message(),
        )
        .await??;
        let ServerRequest::FileChangeRequestApproval { request_id, params } = request else {
            anyhow::bail!("expected file change approval");
        };
        assert_eq!(
            (params.item_id, params.thread_id, params.turn_id),
            ("patch-call".to_string(), thread.id.clone(), turn.id.clone()),
        );
        mcp.send_response(
            request_id,
            serde_json::to_value(FileChangeRequestApprovalResponse {
                decision: FileChangeApprovalDecision::AcceptForSession,
            })?,
        )
        .await?;
    }

    let completions = timeout(DEFAULT_READ_TIMEOUT, async {
        let mut completions = Vec::new();
        loop {
            match mcp.read_next_message().await? {
                JSONRPCMessage::Request(request) => {
                    anyhow::bail!("unexpected additional approval request: {request:?}");
                }
                JSONRPCMessage::Notification(notification)
                    if notification.method == "item/completed" =>
                {
                    let completed: ItemCompletedNotification = serde_json::from_value(
                        notification.params.expect("item completed params"),
                    )?;
                    if let ThreadItem::FileChange { id, status, .. } = completed.item {
                        assert_eq!(
                            (completed.thread_id, completed.turn_id),
                            (thread.id.clone(), turn.id.clone()),
                        );
                        completions.push((id, status));
                    }
                }
                JSONRPCMessage::Notification(notification)
                    if notification.method == "turn/completed" =>
                {
                    let completed: TurnCompletedNotification = serde_json::from_value(
                        notification.params.expect("turn completed params"),
                    )?;
                    assert_eq!(
                        (completed.thread_id, completed.turn.id),
                        (thread.id.clone(), turn.id.clone()),
                    );
                    break Ok::<_, anyhow::Error>(completions);
                }
                _ => {}
            }
        }
    })
    .await??;
    let path = workspace.join("must-not-escalate.txt");
    match execution {
        RequestedExecution::Managed => {
            assert_eq!(
                completions,
                vec![("patch-call".to_string(), PatchApplyStatus::Failed)]
            );
            assert!(!path.try_exists()?);
        }
        RequestedExecution::ExplicitlyUnsandboxed => {
            assert_eq!(
                completions,
                vec![("patch-call".to_string(), PatchApplyStatus::Completed)]
            );
            assert_eq!(std::fs::read_to_string(path)?, "content\n");
        }
    }
    Ok(())
}
