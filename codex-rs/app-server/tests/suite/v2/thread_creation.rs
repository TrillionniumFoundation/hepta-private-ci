//! Cold original-owner fixtures cover each durable creation boundary.
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::*;
use codex_features::Feature;
use codex_protocol::ThreadId;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_state::ThreadCreationReservation;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_absolute_path::test_support::PathExt;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use tempfile::TempDir;

async fn fixture() -> Result<(
    TempDir,
    wiremock::MockServer,
    TestAppServer,
    ThreadStartParams,
    ThreadCreationObserveParams,
)> {
    let home = TempDir::new()?;
    let model = create_mock_responses_server_repeating_assistant(
        "no creation observation sends model input",
    )
    .await;
    MockResponsesConfig::new(&model.uri())
        .enable_feature(Feature::Sqlite)
        .write(home.path())?;
    let mut app = open(&home).await?;
    let cwd = AbsolutePathBuf::from_absolute_path(home.path())?;
    let project: ProjectCreateResponse = app
        .request(|request_id| ClientRequest::ProjectCreate {
            request_id,
            params: ProjectCreateParams {
                name: "protected original creation".into(),
                roots: vec![ProjectRoot { path: cwd.clone() }],
                metadata: None,
                idempotency_key: "original-project".into(),
            },
        })
        .await?;
    let params = ThreadStartParams {
        idempotency_key: Some("original-create".into()),
        cwd: Some(
            home.path()
                .join("unused")
                .join("..")
                .to_string_lossy()
                .into_owned(),
        ),
        runtime_workspace_roots: Some(vec![cwd.clone()]),
        project_id: Some(project.project.id),
        ephemeral: Some(false),
        history_mode: Some(ThreadHistoryMode::Paginated),
        thread_source: Some(ThreadSource::Feature("hepta-ui-chat".into())),
        ..Default::default()
    };
    let observed = ThreadCreationObserveParams {
        idempotency_key: params.idempotency_key.clone().unwrap(),
        expected_parameters_sha256: format!(
            "{:x}",
            Sha256::digest(params.canonical_creation_parameters()?)
        ),
        expected_project_id: params.project_id.clone(),
        expected_cwd: cwd,
        expected_thread_source: params.thread_source.clone(),
    };
    Ok((home, model, app, params, observed))
}
async fn open(home: &TempDir) -> Result<TestAppServer> {
    TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await
}
// Send the exact protected producer parameters. The general test helper's
// per-process auto environment would change the original request after restart.
async fn start(app: &mut TestAppServer, params: ThreadStartParams) -> Result<ThreadStartResponse> {
    app.request(|request_id| ClientRequest::ThreadStart { request_id, params })
        .await
}
async fn observe(
    app: &mut TestAppServer,
    params: ThreadCreationObserveParams,
) -> Result<ThreadCreationObserveResponse> {
    app.request(|request_id| ClientRequest::ThreadCreationObserve { request_id, params })
        .await
}
async fn reconcile(
    app: &mut TestAppServer,
    params: ThreadCreationObserveParams,
) -> Result<ThreadCreationObserveResponse> {
    app.request(|request_id| ClientRequest::ThreadCreationReconcile { request_id, params })
        .await
}
async fn abandon(
    app: &mut TestAppServer,
    params: ThreadCreationObserveParams,
) -> Result<ThreadCreationObserveResponse> {
    app.request(|request_id| ClientRequest::ThreadCreationAbandon { request_id, params })
        .await
}
async fn state_pool(home: &TempDir) -> Result<sqlx::SqlitePool> {
    let sqlite = SqliteConfig::new_for_testing(home.path().abs());
    Ok(sqlite.open_read_write_pool(&sqlite.state_db_path()).await?)
}
async fn unloaded(app: &mut TestAppServer) -> Result<()> {
    let loaded: ThreadLoadedListResponse = app
        .request(|request_id| ClientRequest::ThreadLoadedList {
            request_id,
            params: ThreadLoadedListParams::default(),
        })
        .await?;
    assert_eq!(
        loaded,
        ThreadLoadedListResponse {
            data: vec![],
            next_cursor: None
        }
    );
    Ok(())
}
async fn rejected(app: &mut TestAppServer, method: &str, params: serde_json::Value) -> Result<()> {
    let id = app.send_raw_request(method, Some(params)).await?;
    let _: JSONRPCError = app
        .read_stream_until_error_message(RequestId::Integer(id))
        .await?;
    Ok(())
}

#[tokio::test]
async fn creation_is_durable_before_response_and_cold_replay_returns_only_original_receipt()
-> Result<()> {
    let (home, model, mut app, params, query) = fixture().await?;
    let original = start(&mut app, params.clone()).await?;
    assert!(
        original
            .thread
            .path
            .as_ref()
            .is_some_and(|path| path.exists())
    );
    drop(app);
    let mut app = open(&home).await?;
    unloaded(&mut app).await?;
    let before = model.received_requests().await.unwrap().len();
    let observed = observe(&mut app, query.clone()).await?;
    assert_eq!(
        observed.outcome,
        ThreadCreationObserveOutcome::Created {
            response: Box::new(original.clone())
        }
    );
    assert_eq!(start(&mut app, params.clone()).await?, original);
    let mut normalized = params.clone();
    normalized.cwd = Some(home.path().to_string_lossy().into_owned());
    assert_eq!(start(&mut app, normalized).await?, original);
    unloaded(&mut app).await?;
    let mut changed = params.clone();
    changed.model = Some("another-model".into());
    rejected(&mut app, "thread/start", serde_json::to_value(changed)?).await?;
    let mut wrong = query.clone();
    wrong.expected_cwd = AbsolutePathBuf::from_absolute_path(home.path().join("foreign"))?;
    rejected(
        &mut app,
        "thread/creation/observe",
        serde_json::to_value(wrong)?,
    )
    .await?;
    let mut missing = query;
    missing.idempotency_key = "never-created".into();
    assert_eq!(
        observe(&mut app, missing).await?.outcome,
        ThreadCreationObserveOutcome::Missing
    );
    unloaded(&mut app).await?;
    assert_eq!(model.received_requests().await.unwrap().len(), before);
    Ok(())
}

#[tokio::test]
async fn cold_binding_without_effect_remains_pending_and_never_admits_a_second_id() -> Result<()> {
    let (home, model, app, params, query) = fixture().await?;
    drop(app);
    let state = StateRuntime::init(
        SqliteConfig::new_for_testing(home.path().abs()),
        "mock_provider".into(),
    )
    .await?;
    let original_id = ThreadId::default();
    let reservation = ThreadCreationReservation {
        idempotency_key: query.idempotency_key.clone(),
        parameters_sha256: query.expected_parameters_sha256.clone(),
        thread_id: original_id,
        project_id: query.expected_project_id.clone(),
        cwd: home.path().to_owned(),
        thread_source: serde_json::to_string(
            &query
                .expected_thread_source
                .clone()
                .map(codex_protocol::protocol::ThreadSource::from),
        )?,
    };
    state.reserve_thread_creation(&reservation).await?;
    drop(state);
    let mut app = open(&home).await?;
    let before = model.received_requests().await.unwrap().len();
    assert_eq!(
        observe(&mut app, query.clone()).await?.outcome,
        ThreadCreationObserveOutcome::Pending {
            thread_id: original_id.to_string()
        }
    );
    rejected(&mut app, "thread/start", serde_json::to_value(params)?).await?;
    assert_eq!(
        reconcile(&mut app, query).await?.outcome,
        ThreadCreationObserveOutcome::Pending {
            thread_id: original_id.to_string()
        }
    );
    unloaded(&mut app).await?;
    assert_eq!(model.received_requests().await.unwrap().len(), before);
    Ok(())
}

#[tokio::test]
async fn cold_persist_commit_and_projection_gap_reconciles_only_exact_original_rollout()
-> Result<()> {
    let (home, model, mut app, params, query) = fixture().await?;
    let original = start(&mut app, params.clone()).await?;
    drop(app);
    // The reachable crash state after original persist but before the receipt/index commit.
    // Preserve the actual original response and rollout; remove only derived commit/projection.
    let pool = state_pool(&home).await?;
    sqlx::query(
        "UPDATE thread_creation_operations SET phase = 'pending' WHERE idempotency_key = ?",
    )
    .bind(&query.idempotency_key)
    .execute(&pool)
    .await?;
    sqlx::query("DELETE FROM threads WHERE id = ?")
        .bind(&original.thread.id)
        .execute(&pool)
        .await?;
    pool.close().await;
    let mut app = open(&home).await?;
    let before = model.received_requests().await.unwrap().len();
    assert_eq!(
        observe(&mut app, query.clone()).await?.outcome,
        ThreadCreationObserveOutcome::Materialized {
            thread_id: original.thread.id.clone()
        }
    );
    unloaded(&mut app).await?;
    rejected(&mut app, "thread/start", serde_json::to_value(params)?).await?;
    assert_eq!(
        reconcile(&mut app, query.clone()).await?.outcome,
        ThreadCreationObserveOutcome::Created {
            response: Box::new(original.clone())
        }
    );
    assert_eq!(
        reconcile(&mut app, query).await?.outcome,
        ThreadCreationObserveOutcome::Created {
            response: Box::new(original)
        }
    );
    unloaded(&mut app).await?;
    assert_eq!(model.received_requests().await.unwrap().len(), before);
    Ok(())
}

#[tokio::test]
async fn deletion_keeps_original_key_tombstone_and_never_resurrects_creation() -> Result<()> {
    let (home, model, mut app, params, query) = fixture().await?;
    let original = start(&mut app, params.clone()).await?;
    let _: ThreadDeleteResponse = app
        .request(|request_id| ClientRequest::ThreadDelete {
            request_id,
            params: ThreadDeleteParams {
                thread_id: original.thread.id.clone(),
            },
        })
        .await?;
    drop(app);
    let mut app = open(&home).await?;
    let before = model.received_requests().await.unwrap().len();
    assert_eq!(
        observe(&mut app, query.clone()).await?.outcome,
        ThreadCreationObserveOutcome::Deleted {
            thread_id: original.thread.id.clone()
        }
    );
    assert_eq!(
        reconcile(&mut app, query).await?.outcome,
        ThreadCreationObserveOutcome::Deleted {
            thread_id: original.thread.id
        }
    );
    rejected(&mut app, "thread/start", serde_json::to_value(params)?).await?;
    unloaded(&mut app).await?;
    assert_eq!(model.received_requests().await.unwrap().len(), before);
    Ok(())
}

#[tokio::test]
async fn real_start_failure_before_effect_cold_abandon_and_late_binding_cannot_resurrect()
-> Result<()> {
    let (home, model, mut app, params, query) = fixture().await?;
    let pool = state_pool(&home).await?;
    // Fail the real original lazy-recorder binding, after durable key admission
    // but before it returns a recorder that can materialize any rollout.
    sqlx::query("CREATE TRIGGER fixture_stop_before_creation_effect BEFORE UPDATE OF rollout_path ON thread_creation_operations WHEN NEW.rollout_path IS NOT NULL BEGIN SELECT RAISE(ABORT, 'fixture stop before original creation effect'); END").execute(&pool).await?;
    rejected(
        &mut app,
        "thread/start",
        serde_json::to_value(params.clone())?,
    )
    .await?;
    drop(app);
    sqlx::query("DROP TRIGGER fixture_stop_before_creation_effect")
        .execute(&pool)
        .await?;
    pool.close().await;
    let state = StateRuntime::init(
        SqliteConfig::new_for_testing(home.path().abs()),
        "mock_provider".into(),
    )
    .await?;
    let record = state
        .read_thread_creation(&query.idempotency_key)
        .await?
        .unwrap();
    assert_eq!(record.rollout_path, None);
    assert_eq!(record.receipt_json, None);
    assert_eq!(state.get_thread(record.reservation.thread_id).await?, None);
    let mut app = open(&home).await?;
    let before = model.received_requests().await.unwrap().len();
    assert_eq!(
        observe(&mut app, query.clone()).await?.outcome,
        ThreadCreationObserveOutcome::Pending {
            thread_id: record.reservation.thread_id.to_string()
        }
    );
    let outcome = ThreadCreationObserveOutcome::Abandoned {
        thread_id: record.reservation.thread_id.to_string(),
    };
    assert_eq!(abandon(&mut app, query.clone()).await?.outcome, outcome);
    assert_eq!(abandon(&mut app, query.clone()).await?.outcome, outcome);
    assert!(
        state
            .bind_thread_creation_rollout(
                record.reservation.thread_id,
                home.path(),
                &record.reservation.thread_source,
                &home.path().join("late.jsonl")
            )
            .await
            .is_err()
    );
    assert!(
        state
            .prepare_thread_creation_receipt(&record.reservation, "{}")
            .await
            .is_err()
    );
    rejected(&mut app, "thread/start", serde_json::to_value(params)?).await?;
    let mut wrong = query.clone();
    wrong.expected_cwd = AbsolutePathBuf::from_absolute_path(home.path().join("foreign"))?;
    rejected(
        &mut app,
        "thread/creation/abandon",
        serde_json::to_value(wrong)?,
    )
    .await?;
    assert_eq!(observe(&mut app, query).await?.outcome, outcome);
    unloaded(&mut app).await?;
    assert_eq!(model.received_requests().await.unwrap().len(), before);
    Ok(())
}

#[tokio::test]
async fn real_persist_commit_failure_cold_reconciles_and_refuses_materialized_or_unknown_abandon()
-> Result<()> {
    let (home, model, mut app, params, query) = fixture().await?;
    let pool = state_pool(&home).await?;
    // Exercise real thread/start + original persist/flush, then stop only the
    // final owner receipt commit. No fabricated phase, identity or receipt.
    sqlx::query("CREATE TRIGGER fixture_stop_creation_receipt_commit BEFORE UPDATE OF phase ON thread_creation_operations WHEN NEW.phase = 'created' BEGIN SELECT RAISE(ABORT, 'fixture stop after original creation persist'); END").execute(&pool).await?;
    rejected(
        &mut app,
        "thread/start",
        serde_json::to_value(params.clone())?,
    )
    .await?;
    drop(app);
    sqlx::query("DROP TRIGGER fixture_stop_creation_receipt_commit")
        .execute(&pool)
        .await?;
    let state = StateRuntime::init(
        SqliteConfig::new_for_testing(home.path().abs()),
        "mock_provider".into(),
    )
    .await?;
    let record = state
        .read_thread_creation(&query.idempotency_key)
        .await?
        .unwrap();
    assert_eq!(record.phase, codex_state::ThreadCreationPhase::Pending);
    let original: ThreadStartResponse =
        serde_json::from_str(record.receipt_json.as_deref().unwrap())?;
    let path = record.rollout_path.as_ref().unwrap();
    assert!(path.exists());
    assert_eq!(original.thread.id, record.reservation.thread_id.to_string());
    sqlx::query("DELETE FROM threads WHERE id = ?")
        .bind(&original.thread.id)
        .execute(&pool)
        .await?;
    pool.close().await;
    let mut app = open(&home).await?;
    let before = model.received_requests().await.unwrap().len();
    assert_eq!(
        observe(&mut app, query.clone()).await?.outcome,
        ThreadCreationObserveOutcome::Materialized {
            thread_id: original.thread.id.clone()
        }
    );
    rejected(
        &mut app,
        "thread/start",
        serde_json::to_value(params.clone())?,
    )
    .await?;
    rejected(
        &mut app,
        "thread/creation/abandon",
        serde_json::to_value(query.clone())?,
    )
    .await?;
    let bytes = std::fs::read(path)?;
    std::fs::write(path, b"{invalid original rollout\n")?;
    assert_eq!(
        observe(&mut app, query.clone()).await?.outcome,
        ThreadCreationObserveOutcome::Unknown
    );
    rejected(
        &mut app,
        "thread/creation/abandon",
        serde_json::to_value(query.clone())?,
    )
    .await?;
    assert_eq!(
        state.read_thread_creation(&query.idempotency_key).await?,
        Some(record.clone())
    );
    std::fs::write(path, bytes)?;
    let expected = ThreadCreationObserveOutcome::Created {
        response: Box::new(original),
    };
    assert_eq!(reconcile(&mut app, query.clone()).await?.outcome, expected);
    assert_eq!(reconcile(&mut app, query.clone()).await?.outcome, expected);
    // Created replay is receipt-only; an explicit abandon still cannot cancel it.
    assert_eq!(
        start(&mut app, params).await?.thread.id,
        record.reservation.thread_id.to_string()
    );
    rejected(
        &mut app,
        "thread/creation/abandon",
        serde_json::to_value(query.clone())?,
    )
    .await?;
    let mut missing = query;
    missing.idempotency_key = "never-bound".into();
    rejected(
        &mut app,
        "thread/creation/abandon",
        serde_json::to_value(missing)?,
    )
    .await?;
    unloaded(&mut app).await?;
    assert_eq!(model.received_requests().await.unwrap().len(), before);
    Ok(())
}
