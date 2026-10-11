use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_fake_paginated_rollout;
use app_test_support::create_fake_rollout;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::JSONRPCError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadDeleteParams;
use codex_app_server_protocol::ThreadDeleteResponse;
use codex_app_server_protocol::ThreadDeletedNotification;
use codex_app_server_protocol::ThreadLoadedListParams;
use codex_app_server_protocol::ThreadLoadedListResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_core::find_thread_path_by_id_str;
use codex_protocol::ThreadId;
use codex_protocol::protocol::HistoryPosition;
use codex_state::DirectionalThreadSpawnEdgeStatus;
use codex_state::QueuedClientBindingFinalizeMode;
use codex_state::QueuedClientBindingFinalizeOutcome;
use codex_state::QueuedClientBindingFinalizeRequest;
use codex_state::QueuedClientBindingReserveOutcome;
use codex_state::QueuedClientDispatchClaimOutcome;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use std::path::Path;
use tempfile::TempDir;
use tokio::time::timeout;

const DEFAULT_READ_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10);

#[tokio::test]
async fn thread_delete_rejects_store_without_durable_hard_delete_fencing() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let codex_home = TempDir::new()?;
    let store_id = uuid::Uuid::new_v4();
    MockResponsesConfig::new(&server.uri())
        .with_root_config(&format!(
            "experimental_thread_store = {{ type = \"in_memory\", id = \"{store_id}\" }}"
        ))
        .write(codex_home.path())?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;
    let thread = mcp.start_thread(ThreadStartParams::default()).await?.thread;

    let request_id = mcp
        .send_thread_delete_request(ThreadDeleteParams {
            thread_id: thread.id,
        })
        .await?;
    let error: JSONRPCError = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(request_id)),
    )
    .await??;

    assert_eq!(error.error.code, -32601);
    assert_eq!(
        error.error.message,
        "thread/delete thread-store durable hard-delete fencing is not supported yet"
    );
    Ok(())
}

#[tokio::test]
async fn thread_delete_rejects_paginated_writer_owned_by_another_process() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(codex_home.path())?;
    let thread_id = create_fake_paginated_rollout(
        codex_home.path(),
        "2025-01-01T00-00-00",
        "2025-01-01T00:00:00Z",
        "owned",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    let mut owner = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;
    let _: ThreadResumeResponse = owner
        .request(|request_id| ClientRequest::ThreadResume {
            request_id,
            params: ThreadResumeParams {
                thread_id: thread_id.clone(),
                exclude_turns: true,
                ..Default::default()
            },
        })
        .await?;

    let mut other = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;
    let request_id = other
        .send_thread_delete_request(ThreadDeleteParams {
            thread_id: thread_id.clone(),
        })
        .await?;
    let error: JSONRPCError = timeout(
        DEFAULT_READ_TIMEOUT,
        other.read_stream_until_error_message(RequestId::Integer(request_id)),
    )
    .await??;
    assert_eq!(error.error.code, -32600);
    assert_eq!(
        error.error.message,
        format!("thread {thread_id} already has an active writer")
    );
    timeout(DEFAULT_READ_TIMEOUT, owner.shutdown_gracefully()).await??;
    let _: ThreadDeleteResponse = other
        .request(|request_id| ClientRequest::ThreadDelete {
            request_id,
            params: ThreadDeleteParams { thread_id },
        })
        .await?;
    Ok(())
}

#[tokio::test]
async fn thread_delete_refuses_active_exact_dispatch_before_removing_rollout() -> Result<()> {
    let codex_home = TempDir::new()?;
    let thread_id_string = create_delete_test_rollout(
        codex_home.path(),
        /*minute*/ 0,
        "active exact dispatch",
    )?;
    let thread_id = ThreadId::from_string(&thread_id_string)?;
    let sqlite_home = codex_home.path().to_string_lossy().into_owned();
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .with_env_overrides(&[("CODEX_SQLITE_HOME", Some(sqlite_home.as_str()))])
        .without_auto_env()
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;
    let state_db = StateRuntime::init(
        SqliteConfig::new_for_testing(codex_home.path().abs()),
        "mock_provider".into(),
    )
    .await?;
    let client_id = "matrix-delete-fence";
    let payload = format!(
        r#"{{"UserInput":{{"content":[{{"Text":{{"text":"delete race","text_elements":[]}}}}],"client_id":"{client_id}"}}}}"#
    );
    let digest = "a".repeat(64);
    let QueuedClientBindingReserveOutcome::Reserved(reservation) = state_db
        .thread_queue()
        .reserve_client_binding(thread_id, client_id, &digest, &payload)
        .await?
    else {
        panic!("fresh exact identity must reserve");
    };
    let QueuedClientBindingFinalizeOutcome::Queued { record, .. } = state_db
        .thread_queue()
        .finalize_client_binding(QueuedClientBindingFinalizeRequest {
            thread_id,
            client_id: client_id.to_string(),
            payload_sha256: digest.clone(),
            payload_json: payload,
            lease: reservation,
            mode: QueuedClientBindingFinalizeMode::AllowIfAbsent,
            observed_turn_id: None,
            runtime_capacity: None,
        })
        .await?
    else {
        panic!("fresh exact reservation must create one queue row");
    };
    let process_lock = state_db
        .thread_queue()
        .try_acquire_client_dispatch_lock(thread_id, client_id, &digest)?
        .expect("test owns the exact process lock");
    let QueuedClientDispatchClaimOutcome::Acquired(lease) = state_db
        .thread_queue()
        .claim_client_binding_dispatch(
            &process_lock,
            &record.id,
            "delete-race-owner",
            /*now_ms*/ 100,
            /*lease_expires_at_ms*/ 200,
        )
        .await?
    else {
        panic!("exact queue row must become dispatching");
    };

    let delete_id = mcp
        .send_thread_delete_request(ThreadDeleteParams {
            thread_id: thread_id_string.clone(),
        })
        .await?;
    let delete_err: JSONRPCError = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(delete_id)),
    )
    .await??;
    assert_eq!(delete_err.error.code, -32600);
    assert!(
        delete_err
            .error
            .message
            .contains("active exact queue dispatch"),
        "unexpected delete conflict: {}",
        delete_err.error.message
    );
    assert!(
        find_thread_path_by_id_str(
            codex_home.path(),
            &thread_id_string,
            /*state_db_ctx*/ None,
        )
        .await?
        .is_some(),
        "thread-store rollout must remain after queue-fence conflict"
    );

    state_db
        .thread_queue()
        .release_client_binding_dispatch(&process_lock, &lease)
        .await?;
    Ok(())
}

#[tokio::test]
async fn thread_delete_deletes_spawned_descendants() -> Result<()> {
    let codex_home = TempDir::new()?;

    let parent_id = create_delete_test_rollout(codex_home.path(), /*minute*/ 0, "parent")?;
    let child_id = create_delete_test_rollout(codex_home.path(), /*minute*/ 1, "child")?;
    let grandchild_id =
        create_delete_test_rollout(codex_home.path(), /*minute*/ 2, "grandchild")?;

    let state_db = StateRuntime::init(
        codex_state::SqliteConfig::new_for_testing(codex_home.path().abs()),
        "mock_provider".into(),
    )
    .await?;
    let parent_thread_id = ThreadId::from_string(&parent_id)?;
    let child_thread_id = ThreadId::from_string(&child_id)?;
    let grandchild_thread_id = ThreadId::from_string(&grandchild_id)?;

    for (parent, child, status) in [
        (
            parent_thread_id,
            child_thread_id,
            DirectionalThreadSpawnEdgeStatus::Closed,
        ),
        (
            child_thread_id,
            grandchild_thread_id,
            DirectionalThreadSpawnEdgeStatus::Open,
        ),
    ] {
        state_db
            .upsert_thread_spawn_edge(parent, child, status)
            .await?;
    }

    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;

    let _: ThreadDeleteResponse = mcp
        .request(|request_id| ClientRequest::ThreadDelete {
            request_id,
            params: ThreadDeleteParams {
                thread_id: parent_id.clone(),
            },
        })
        .await?;

    let mut deleted_ids = Vec::new();
    for _ in 0..3 {
        let deleted_notification: ThreadDeletedNotification = timeout(
            DEFAULT_READ_TIMEOUT,
            mcp.read_notification("thread/deleted"),
        )
        .await??;
        deleted_ids.push(deleted_notification.thread_id);
    }
    assert_eq!(deleted_ids, vec![grandchild_id, child_id, parent_id]);

    for thread_id in [parent_thread_id, child_thread_id, grandchild_thread_id] {
        let rollout_path = find_thread_path_by_id_str(
            codex_home.path(),
            &thread_id.to_string(),
            /*state_db_ctx*/ None,
        )
        .await?;
        assert!(
            rollout_path.is_none(),
            "expected active rollout for {thread_id} to be deleted"
        );
    }
    assert_eq!(
        state_db
            .list_thread_spawn_descendants(parent_thread_id)
            .await?,
        Vec::<ThreadId>::new()
    );
    Ok(())
}

#[tokio::test]
async fn thread_delete_fresh_process_retries_from_durable_completed_operation() -> Result<()> {
    let codex_home = TempDir::new()?;
    let parent_id =
        create_delete_test_rollout(codex_home.path(), /*minute*/ 0, "parent retry")?;
    let child_id = create_delete_test_rollout(codex_home.path(), /*minute*/ 1, "child retry")?;
    let parent_thread_id = ThreadId::from_string(&parent_id)?;
    let child_thread_id = ThreadId::from_string(&child_id)?;
    let state_db = StateRuntime::init(
        SqliteConfig::new_for_testing(codex_home.path().abs()),
        "mock_provider".into(),
    )
    .await?;
    state_db
        .upsert_thread_spawn_edge(
            parent_thread_id,
            child_thread_id,
            DirectionalThreadSpawnEdgeStatus::Closed,
        )
        .await?;

    let mut first = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;
    let _: ThreadDeleteResponse = first
        .request(|request_id| ClientRequest::ThreadDelete {
            request_id,
            params: ThreadDeleteParams {
                thread_id: parent_id.clone(),
            },
        })
        .await?;
    timeout(DEFAULT_READ_TIMEOUT, first.shutdown_gracefully()).await??;

    // This fresh app-server has no in-memory removal authority, AgentGraph rows, StateDb thread
    // rows, or thread-store rollouts. It models a client losing the first successful response and
    // retrying after process restart; queue.sqlite's durable operation journal is the sole closure
    // authority.
    let mut retry = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;
    let _: ThreadDeleteResponse = retry
        .request(|request_id| ClientRequest::ThreadDelete {
            request_id,
            params: ThreadDeleteParams {
                thread_id: parent_id.clone(),
            },
        })
        .await?;

    assert_eq!(
        state_db
            .thread_queue()
            .thread_deletion_operation_members(parent_thread_id)
            .await?,
        Some(vec![parent_thread_id, child_thread_id])
    );
    for thread_id in [parent_thread_id, child_thread_id] {
        assert!(
            find_thread_path_by_id_str(
                codex_home.path(),
                &thread_id.to_string(),
                /*state_db_ctx*/ None,
            )
            .await?
            .is_none()
        );
        assert!(
            state_db
                .thread_queue()
                .thread_queue_is_sealed_for_deletion(thread_id)
                .await?
        );
    }
    Ok(())
}

#[tokio::test]
async fn thread_delete_preflights_external_fork_references_for_spawned_subtrees() -> Result<()> {
    let codex_home = TempDir::new()?;

    let parent_id = create_delete_test_rollout(codex_home.path(), /*minute*/ 0, "parent")?;
    let child_id = create_delete_test_rollout(codex_home.path(), /*minute*/ 1, "child")?;
    let external_id = create_delete_test_rollout(codex_home.path(), /*minute*/ 2, "external")?;
    let parent_thread_id = ThreadId::from_string(&parent_id)?;
    let child_thread_id = ThreadId::from_string(&child_id)?;
    let external_thread_id = ThreadId::from_string(&external_id)?;
    let parent_path = find_thread_path_by_id_str(
        codex_home.path(),
        &parent_thread_id.to_string(),
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("parent rollout path");
    let external_path = find_thread_path_by_id_str(
        codex_home.path(),
        &external_thread_id.to_string(),
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("external rollout path");
    let mut external_meta: serde_json::Value = serde_json::from_str(
        std::fs::read_to_string(external_path.as_path())?
            .lines()
            .next()
            .expect("external session metadata"),
    )?;
    external_meta["payload"]["history_base"] = serde_json::to_value(HistoryPosition {
        thread_id: parent_thread_id,
        end_ordinal_exclusive: 1,
        end_byte_offset: std::fs::metadata(parent_path.as_path())?.len(),
    })?;
    std::fs::write(external_path.as_path(), format!("{external_meta}\n"))?;

    let state_db = StateRuntime::init(
        SqliteConfig::new_for_testing(codex_home.path().abs()),
        "mock_provider".into(),
    )
    .await?;
    state_db
        .upsert_thread_spawn_edge(
            parent_thread_id,
            child_thread_id,
            DirectionalThreadSpawnEdgeStatus::Closed,
        )
        .await?;

    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;

    let delete_id = mcp
        .send_thread_delete_request(ThreadDeleteParams {
            thread_id: parent_id.clone(),
        })
        .await?;
    let delete_err: JSONRPCError = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(delete_id)),
    )
    .await??;
    assert_eq!(
        delete_err.error.message,
        format!("cannot delete thread {parent_thread_id}: forked history still references it")
    );

    let resume_id = mcp
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: parent_id.clone(),
            ..Default::default()
        })
        .await?;
    let resume_err: JSONRPCError = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(resume_id)),
    )
    .await??;
    assert_eq!(resume_err.error.code, -32600);
    assert_eq!(
        resume_err.error.message,
        format!("thread {parent_thread_id} is sealed for hard deletion and cannot be resumed")
    );

    for thread_id in [parent_thread_id, child_thread_id, external_thread_id] {
        assert!(
            find_thread_path_by_id_str(
                codex_home.path(),
                &thread_id.to_string(),
                /*state_db_ctx*/ None,
            )
            .await?
            .is_some(),
            "expected rollout for {thread_id} to remain"
        );
    }
    assert_eq!(
        state_db
            .list_thread_spawn_descendants(parent_thread_id)
            .await?,
        vec![child_thread_id]
    );

    external_meta["payload"]
        .as_object_mut()
        .expect("session metadata payload")
        .remove("history_base");
    std::fs::write(external_path.as_path(), format!("{external_meta}\n"))?;

    let _: ThreadDeleteResponse = mcp
        .request(|request_id| ClientRequest::ThreadDelete {
            request_id,
            params: ThreadDeleteParams {
                thread_id: parent_id,
            },
        })
        .await?;

    for thread_id in [parent_thread_id, child_thread_id] {
        assert!(
            find_thread_path_by_id_str(
                codex_home.path(),
                &thread_id.to_string(),
                /*state_db_ctx*/ None,
            )
            .await?
            .is_none(),
            "expected retried delete to remove {thread_id}"
        );
    }
    assert!(
        find_thread_path_by_id_str(
            codex_home.path(),
            &external_thread_id.to_string(),
            /*state_db_ctx*/ None,
        )
        .await?
        .is_some(),
        "external thread should remain after removing its history reference"
    );
    assert_eq!(
        state_db
            .list_thread_spawn_descendants(parent_thread_id)
            .await?,
        Vec::<ThreadId>::new()
    );
    Ok(())
}

fn create_delete_test_rollout(codex_home: &Path, minute: u8, preview: &str) -> Result<String> {
    create_fake_rollout(
        codex_home,
        &format!("2025-01-01T00-{minute:02}-00"),
        &format!("2025-01-01T00:{minute:02}:00Z"),
        preview,
        Some("mock_provider"),
        /*git_info*/ None,
    )
}

#[tokio::test]
async fn thread_delete_handles_live_threads_before_rollout_exists() -> Result<()> {
    let codex_home = TempDir::new()?;

    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(std::time::Duration::from_secs(30))
        .await?;

    let persisted_thread = mcp.start_thread(ThreadStartParams::default()).await?.thread;
    let rollout_path = find_thread_path_by_id_str(
        codex_home.path(),
        &persisted_thread.id,
        /*state_db_ctx*/ None,
    )
    .await?;
    assert_eq!(rollout_path, None);

    let _: ThreadDeleteResponse = mcp
        .request(|request_id| ClientRequest::ThreadDelete {
            request_id,
            params: ThreadDeleteParams {
                thread_id: persisted_thread.id,
            },
        })
        .await?;

    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            ephemeral: Some(true),
            ..Default::default()
        })
        .await?;

    let delete_id = mcp
        .send_thread_delete_request(ThreadDeleteParams {
            thread_id: thread.id.clone(),
        })
        .await?;
    let delete_err: JSONRPCError = timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(delete_id)),
    )
    .await??;
    let expected_message = format!(
        "thread is not persisted and cannot be deleted: {}",
        thread.id
    );
    assert_eq!(delete_err.error.message, expected_message);

    let ThreadLoadedListResponse { mut data, .. } = mcp
        .request(|request_id| ClientRequest::ThreadLoadedList {
            request_id,
            params: ThreadLoadedListParams::default(),
        })
        .await?;
    data.sort();
    assert_eq!(data, vec![thread.id]);

    Ok(())
}
