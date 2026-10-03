//! Public original-owner reads must not load, reserve, dispatch, or guess.
use super::*;
use codex_app_server_protocol::ProjectCreateParams;
use codex_app_server_protocol::ProjectCreateResponse;
use codex_app_server_protocol::ProjectRoot;
use codex_app_server_protocol::ThreadLoadedListParams;
use codex_app_server_protocol::ThreadLoadedListResponse;
use codex_app_server_protocol::ThreadQueueObserveOutcome;
use codex_app_server_protocol::ThreadQueueObserveParams;
use codex_app_server_protocol::ThreadQueueObserveResponse;
use codex_app_server_protocol::ThreadSource;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

async fn observed_fixture(
    model_turns: usize,
) -> Result<(TestAppServer, TempDir, MockServer, ThreadQueueObserveParams)> {
    let responses = (0..model_turns)
        .map(|_| create_final_assistant_message_sse_response("original reply"))
        .collect::<Result<Vec<_>>>()?;
    let (mut app, home, server) = queue_app(responses).await?;
    let cwd = AbsolutePathBuf::from_absolute_path(home.path())?;
    let project: ProjectCreateResponse = app
        .request(|request_id| ClientRequest::ProjectCreate {
            request_id,
            params: ProjectCreateParams {
                name: "original protected chat".into(),
                roots: vec![ProjectRoot { path: cwd.clone() }],
                metadata: None,
                idempotency_key: "original-chat-project".into(),
            },
        })
        .await?;
    let thread = app
        .start_thread(ThreadStartParams {
            cwd: Some(cwd.as_path().to_string_lossy().into_owned()),
            project_id: Some(project.project.id.clone()),
            history_mode: Some(codex_app_server_protocol::ThreadHistoryMode::Paginated),
            thread_source: Some(ThreadSource::Feature("hepta-ui-chat".into())),
            ..Default::default()
        })
        .await?
        .thread;
    // Materialize through an original completed turn, then enqueue into an
    // unloaded owner. The ordinary queue wake must not race the observation.
    app.start_turn_and_wait_for_completion(TurnStartParams {
        thread_id: thread.id.clone(),
        input: vec![text("materialize the original protected thread")],
        ..Default::default()
    })
    .await?;
    drop(app);
    let app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let input = vec![text("original message")];
    let digest = user_input_payload_sha256(
        &input
            .into_iter()
            .map(UserInput::into_core)
            .collect::<Vec<_>>(),
    )?;
    Ok((
        app,
        home,
        server,
        ThreadQueueObserveParams {
            thread_id: thread.id,
            expected_project_id: project.project.id,
            expected_cwd: cwd,
            expected_thread_source: ThreadSource::Feature("hepta-ui-chat".into()),
            client_user_message_id: "original-message".into(),
            expected_payload_sha256: digest,
        },
    ))
}
// Match the original protected Send producer: atomically identify the request
// through QueueReconcile rather than the legacy unbound QueueAdd path.
async fn bound_queue_item(
    app: &mut TestAppServer,
    params: ThreadQueueAddParams,
) -> Result<QueuedSubmission> {
    let digest = user_input_payload_sha256(
        &params
            .input
            .clone()
            .into_iter()
            .map(UserInput::into_core)
            .collect::<Vec<_>>(),
    )?;
    let response: ThreadQueueReconcileResponse = app
        .request(|request_id| ClientRequest::ThreadQueueReconcile {
            request_id,
            params: ThreadQueueReconcileParams {
                thread_id: params.thread_id,
                input: params.input,
                client_user_message_id: params.client_user_message_id,
                expected_payload_sha256: digest,
                mode: ThreadQueueReconcileMode::AllowIfAbsent,
            },
        })
        .await?;
    let ThreadQueueReconcileOutcome::Queued {
        queued_submission, ..
    } = response.outcome
    else {
        anyhow::bail!("original protected Send did not bind the queued item");
    };
    Ok(queued_submission)
}
async fn observe(
    app: &mut TestAppServer,
    params: ThreadQueueObserveParams,
) -> Result<ThreadQueueObserveResponse> {
    app.request(|request_id| ClientRequest::ThreadQueueObserve { request_id, params })
        .await
}
async fn loaded(app: &mut TestAppServer) -> Result<ThreadLoadedListResponse> {
    app.request(|request_id| ClientRequest::ThreadLoadedList {
        request_id,
        params: ThreadLoadedListParams::default(),
    })
    .await
}

#[tokio::test]
async fn cold_observation_retains_pending_and_missing_without_loading_or_dispatching() -> Result<()>
{
    let (mut app, home, server, params) = observed_fixture(1).await?;
    let queued = bound_queue_item(
        &mut app,
        ThreadQueueAddParams {
            thread_id: params.thread_id.clone(),
            input: vec![text("original message")],
            client_user_message_id: params.client_user_message_id.clone(),
        },
    )
    .await?;
    drop(app);
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let unloaded = ThreadLoadedListResponse {
        data: vec![],
        next_cursor: None,
    };
    assert_eq!(loaded(&mut app).await?, unloaded);
    let queue_before = list_queue(&mut app, &params.thread_id).await?;
    let requests_before = server.received_requests().await.unwrap().len();
    let observed = observe(&mut app, params.clone()).await?;
    assert_eq!(
        observed,
        ThreadQueueObserveResponse {
            client_user_message_id: params.client_user_message_id.clone(),
            payload_sha256: params.expected_payload_sha256.clone(),
            outcome: ThreadQueueObserveOutcome::Pending {
                queued_submission_id: Some(queued.id)
            },
        }
    );
    let mut absent = params.clone();
    absent.client_user_message_id = "never-submitted-message".into();
    assert_eq!(
        observe(&mut app, absent).await?.outcome,
        ThreadQueueObserveOutcome::Missing
    );
    assert_eq!(list_queue(&mut app, &params.thread_id).await?, queue_before);
    assert_eq!(loaded(&mut app).await?, unloaded);
    assert_eq!(
        server.received_requests().await.unwrap().len(),
        requests_before
    );
    Ok(())
}

#[tokio::test]
async fn observation_rejects_changed_scope_and_payload_without_repairing_or_loading() -> Result<()>
{
    let (mut app, home, _server, params) = observed_fixture(1).await?;
    bound_queue_item(
        &mut app,
        ThreadQueueAddParams {
            thread_id: params.thread_id.clone(),
            input: vec![text("original message")],
            client_user_message_id: params.client_user_message_id.clone(),
        },
    )
    .await?;
    drop(app);
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let queue_before = list_queue(&mut app, &params.thread_id).await?;
    for changed in 0..4 {
        let mut wrong = params.clone();
        match changed {
            0 => wrong.expected_project_id = "foreign-project".into(),
            1 => {
                wrong.expected_cwd =
                    AbsolutePathBuf::from_absolute_path(home.path().join("foreign-workspace"))?
            }
            2 => wrong.expected_thread_source = ThreadSource::Feature("foreign-source".into()),
            _ => wrong.expected_payload_sha256 = "0".repeat(64),
        }
        let id = app
            .send_raw_request("thread/queue/observe", Some(serde_json::to_value(wrong)?))
            .await?;
        let _: JSONRPCError = timeout(
            READ_TIMEOUT,
            app.read_stream_until_error_message(RequestId::Integer(id)),
        )
        .await??;
    }
    assert_eq!(list_queue(&mut app, &params.thread_id).await?, queue_before);
    assert_eq!(
        loaded(&mut app).await?,
        ThreadLoadedListResponse {
            data: vec![],
            next_cursor: None
        }
    );
    Ok(())
}

#[tokio::test]
async fn cold_observation_reads_cancelled_identity_without_resubmission() -> Result<()> {
    let (mut app, home, _server, params) = observed_fixture(1).await?;
    let queued = bound_queue_item(
        &mut app,
        ThreadQueueAddParams {
            thread_id: params.thread_id.clone(),
            input: vec![text("original message")],
            client_user_message_id: params.client_user_message_id.clone(),
        },
    )
    .await?;
    let _: ThreadQueueDeleteResponse = app
        .request(|request_id| ClientRequest::ThreadQueueDelete {
            request_id,
            params: ThreadQueueDeleteParams {
                thread_id: params.thread_id.clone(),
                queued_submission_id: queued.id,
            },
        })
        .await?;
    drop(app);
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    assert_eq!(
        observe(&mut app, params.clone()).await?.outcome,
        ThreadQueueObserveOutcome::Cancelled
    );
    assert!(
        list_queue(&mut app, &params.thread_id)
            .await?
            .data
            .is_empty()
    );
    assert_eq!(
        loaded(&mut app).await?,
        ThreadLoadedListResponse {
            data: vec![],
            next_cursor: None
        }
    );
    Ok(())
}

#[tokio::test]
async fn cold_observation_reads_the_exact_persisted_turn_without_resuming_it() -> Result<()> {
    let (mut app, home, server, params) = observed_fixture(2).await?;
    let _: ThreadResumeResponse = app
        .request(|request_id| ClientRequest::ThreadResume {
            request_id,
            params: ThreadResumeParams {
                thread_id: params.thread_id.clone(),
                ..Default::default()
            },
        })
        .await?;
    let _queued = bound_queue_item(
        &mut app,
        ThreadQueueAddParams {
            thread_id: params.thread_id.clone(),
            input: vec![text("original message")],
            client_user_message_id: params.client_user_message_id.clone(),
        },
    )
    .await?;
    let completed: TurnCompletedNotification =
        timeout(READ_TIMEOUT, app.read_notification("turn/completed")).await??;
    assert_eq!(completed.turn.status, TurnStatus::Completed);
    drop(app);
    let submitted_requests = server.received_requests().await.unwrap().len();
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    assert_eq!(
        observe(&mut app, params.clone()).await?.outcome,
        ThreadQueueObserveOutcome::Persisted {
            turn_id: completed.turn.id,
            terminal: Some(codex_app_server_protocol::ThreadQueueObservedTerminal::Completed),
        }
    );
    assert_eq!(
        loaded(&mut app).await?,
        ThreadLoadedListResponse {
            data: vec![],
            next_cursor: None
        }
    );
    assert!(
        list_queue(&mut app, &params.thread_id)
            .await?
            .data
            .is_empty()
    );
    assert_eq!(
        server.received_requests().await.unwrap().len(),
        submitted_requests
    );
    Ok(())
}
