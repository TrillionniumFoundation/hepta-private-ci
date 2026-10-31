use super::*;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStopInput;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;

struct FirstThreadStopGate {
    stopped: AtomicBool,
    entered: Notify,
    release: Notify,
}

impl ThreadLifecycleContributor<Config> for FirstThreadStopGate {
    fn on_thread_stop<'a>(
        &'a self,
        _input: ThreadStopInput<'a>,
    ) -> codex_extension_api::ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if !self.stopped.swap(true, Ordering::AcqRel) {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

#[tokio::test]
async fn delayed_shutdown_preserves_replacement_runtime_and_ownership() -> anyhow::Result<()> {
    let (_home, mut config) = test_config().await;
    config.multi_agent_v2.max_concurrent_threads_per_session = 2;
    let stop = Arc::new(FirstThreadStopGate {
        stopped: AtomicBool::new(false),
        entered: Notify::new(),
        release: Notify::new(),
    });
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(stop.clone());
    let auth = AuthManager::from_auth_for_testing(CodexAuth::from_api_key("dummy"));
    let state_db = init_state_db(&config).await;
    let store = Arc::new(LocalThreadStore::new(
        LocalThreadStoreConfig::from_config(&config),
        state_db,
    ));
    let manager = ThreadManager::new(
        &config,
        Arc::clone(&auth),
        crate::build_models_manager(&config, auth),
        crate::CodexAppsToolsCache::default(),
        SessionSource::Exec,
        Arc::new(codex_exec_server::EnvironmentManager::default_for_tests()),
        Arc::new(extensions.build()),
        Arc::new(crate::test_support::EmptyUserInstructionsProvider),
        /*analytics_events_client*/ None,
        store,
        /*agent_graph_store*/ None,
        "4f8995e8-e9e5-469c-8d48-0df562915926".to_string(),
        /*attestation_provider*/ None,
        /*external_time_provider*/ None,
    );
    let control = manager.agent_control();
    let original = manager
        .start_thread(StartThreadOptions::new(config.clone()))
        .await?;
    let thread_id = original.thread_id;
    original.thread.ensure_rollout_materialized().await;
    original.thread.session.flush_rollout().await?;

    // Poll the real shutdown caller until A is stopping, then keep that caller
    // suspended while another owner finishes A and resumes the stored thread as B.
    // The lifecycle gate is after terminalizer drain, so no watchdog is involved.
    let shutdown = control.shutdown_live_agent(thread_id);
    tokio::pin!(shutdown);
    timeout(Duration::from_secs(5), async {
        tokio::select! {
            result = &mut shutdown => anyhow::bail!("shutdown returned before its stop gate: {result:?}"),
            () = stop.entered.notified() => Ok(()),
        }
    })
    .await??;
    let bounded_shutdown = manager.shutdown_all_threads_bounded(Duration::from_secs(5));
    tokio::pin!(bounded_shutdown);
    assert!(futures::poll!(&mut bounded_shutdown).is_pending());
    stop.release.notify_one();
    timeout(
        Duration::from_secs(5),
        original.thread.wait_until_terminated(),
    )
    .await?;
    let removed = manager
        .remove_thread(&thread_id)
        .await
        .ok_or_else(|| anyhow::anyhow!("original runtime was not registered"))?;
    assert!(Arc::ptr_eq(&removed, &original.thread));

    assert_eq!(
        control
            .resume_agent_from_rollout(config.clone(), thread_id, SessionSource::Exec)
            .await?,
        thread_id
    );
    let replacement = manager.get_thread(thread_id).await?;
    assert!(!Arc::ptr_eq(&replacement, &original.thread));
    let metadata = control
        .state
        .agent_metadata_for_thread(thread_id)
        .ok_or_else(|| anyhow::anyhow!("replacement metadata was not registered"))?;
    let manager_state = control.upgrade()?;
    control
        .reserve_v2_residency_slot(&manager_state, &config, Some(thread_id))
        .await?
        .commit(thread_id);

    assert_eq!(
        timeout(Duration::from_secs(5), bounded_shutdown).await?,
        crate::thread_manager::ThreadShutdownReport {
            completed: vec![thread_id],
            ..Default::default()
        }
    );
    timeout(Duration::from_secs(5), shutdown).await??;
    let stale_submission = manager_state
        .send_op_to_runtime(
            original.thread.as_ref(),
            Op::Interrupt,
            /*parent_turn_id*/ None,
            /*root_turn_id*/ None,
        )
        .await;
    assert_matches!(
        control.handle_thread_request_result(thread_id, &manager_state, &original.thread, stale_submission).await,
        Err(error) if matches!(error.details(), CodexErrorDetails::InternalAgentDied)
    );

    let still_registered = manager.get_thread(thread_id).await?;
    assert!(Arc::ptr_eq(&still_registered, &replacement));
    let still_metadata = control
        .state
        .agent_metadata_for_thread(thread_id)
        .ok_or_else(|| anyhow::anyhow!("stale shutdown removed replacement metadata"))?;
    assert_eq!(
        (
            still_metadata.agent_id,
            still_metadata.agent_path,
            still_metadata.agent_nickname,
            still_metadata.agent_role,
        ),
        (
            metadata.agent_id,
            metadata.agent_path,
            metadata.agent_nickname,
            metadata.agent_role,
        )
    );
    assert!(replacement.wait_until_terminated().now_or_never().is_none());
    assert_matches!(
        control
            .reserve_v2_residency_slot(&manager_state, &config, Some(thread_id))
            .await,
        Err(error) if matches!(error.details(), CodexErrorDetails::AgentLimitReached { max_threads: 1 })
    );
    control.shutdown_live_agent(thread_id).await?;
    Ok(())
}

#[tokio::test]
async fn cold_close_waits_for_cancelled_reload_then_releases_ownership() -> anyhow::Result<()> {
    let (home, mut config) = test_config().await;
    let _ = config.features.enable(Feature::MultiAgentV2);
    let _ = config.features.enable(Feature::Sqlite);
    config.model = Some("gpt-5.6-sol".to_string());
    config.multi_agent_v2.max_concurrent_threads_per_session = 2;
    let harness = AgentControlHarness::new_with_config(home, config).await;
    let root = harness
        .manager
        .start_thread(StartThreadOptions {
            history_mode: Some(ThreadHistoryMode::Paginated),
            ..StartThreadOptions::new(harness.config.clone())
        })
        .await?;
    let control = root.thread.session.services.agent_control.clone();
    let spawned =
        spawn_v2_reload_test_child(&control, harness.config.clone(), &root.thread, "worker").await;
    let child_id = spawned.thread_id;
    let child_path = spawned
        .metadata
        .agent_path
        .ok_or_else(|| anyhow::anyhow!("child path was not registered"))?;
    let child = harness.manager.get_thread(child_id).await?;
    child
        .inject_response_items(vec![assistant_message(
            "persisted cold child",
            Some(MessagePhase::FinalAnswer),
        )])
        .await?;
    child.shutdown_and_wait().await?;
    assert!(
        harness
            .manager
            .remove_thread_if_matches(&child_id, &child)
            .await
            .is_some()
    );
    control.forget_v2_residency(child_id);
    assert_eq!(control.state.live_agents().len(), 1);

    let delivery = harness.manager.pause_next_startup_before_delivery();
    let reload_control = control.clone();
    let reload_config = harness.config.clone();
    let reload = tokio::spawn(async move {
        reload_control
            .ensure_v2_agent_loaded(reload_config, child_id, /*parent*/ None)
            .await
    });
    timeout(Duration::from_secs(5), delivery.wait_until_entered()).await?;
    reload.abort();
    assert!(matches!(reload.await, Err(error) if error.is_cancelled()));
    // The requesting future is gone. Its detached delivery/cleanup owner must
    // still fence cold retirement, including the gap before startup admission.
    assert!(control.transitions.try_lock(child_id).is_none());
    let close = control.close_agent(child_id);
    tokio::pin!(close);
    assert!(futures::poll!(&mut close).is_pending());
    assert!(control.state.agent_metadata_for_thread(child_id).is_some());
    delivery.release();
    timeout(Duration::from_secs(5), close).await??;

    assert!(harness.manager.get_thread(child_id).await.is_err());
    assert!(control.state.agent_metadata_for_thread(child_id).is_none());
    assert_eq!(control.state.agent_id_for_path(&child_path), None);
    assert!(control.state.live_agents().is_empty());
    drop(control.state.reserve_spawn_slot(Some(1))?);
    let manager_state = control.upgrade()?;
    drop(
        control
            .reserve_v2_residency_slot(
                &manager_state,
                &harness.config,
                /*protected_thread_id*/ None,
            )
            .await?,
    );
    let graph = manager_state
        .agent_graph_store()
        .ok_or_else(|| anyhow::anyhow!("fixture requires its real agent graph store"))?;
    assert_eq!(
        graph
            .list_thread_spawn_children(
                root.thread_id,
                Some(codex_agent_graph_store::ThreadSpawnEdgeStatus::Closed)
            )
            .await?,
        vec![child_id]
    );
    control
        .restore_v2_agent_metadata(&harness.config, root.thread_id)
        .await;
    assert!(control.state.live_agents().is_empty());
    assert_matches!(
        control.ensure_v2_agent_loaded(harness.config.clone(), child_id, /*parent*/ None).await,
        Err(error) if matches!(error.details(), CodexErrorDetails::ThreadNotFound(id) if *id == child_id)
    );
    root.thread.shutdown_and_wait().await?;
    Ok(())
}
