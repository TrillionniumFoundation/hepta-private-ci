use super::*;

pub(super) async fn assert_blocking_snapshot_waits_for_starting_environment() {
    let buffer: &'static std::sync::Mutex<Vec<u8>> =
        Box::leak(Box::new(std::sync::Mutex::new(Vec::new())));
    let subscriber = tracing_subscriber::fmt()
        .with_ansi(false)
        .with_max_level(Level::TRACE)
        .with_span_events(FmtSpan::NEW)
        .with_writer(MockWriter::new(buffer))
        .finish();
    let dispatch = tracing::Dispatch::new(subscriber);
    let snapshot_dispatch = dispatch.clone();
    // Install the collector for every poll, including manager setup and the
    // spawning of resolution work; do not hold a thread-local guard over await.
    async move {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind websocket listener");
        let manager = Arc::new(
            EnvironmentManager::create_for_tests(
                Some(format!(
                    "ws://{}",
                    listener.local_addr().expect("listener address")
                )),
                Some(test_runtime_paths()),
            )
            .await,
        );
        let selection = TurnEnvironmentSelection {
            environment_id: REMOTE_ENVIRONMENT_ID.to_string(),
            cwd: PathUri::from_abs_path(&AbsolutePathBuf::current_dir().expect("cwd")),
            workspace_roots: Vec::new(),
            config: EnvironmentConfigState::FromThread,
        };
        let environments = Arc::new(ThreadEnvironments::new(
            manager,
            crate::shell::default_user_shell(),
            test_environment_config(),
            ShellSnapshot::disabled(),
            TurnEnvironmentSnapshot::default(),
            /*non_blocking_snapshots*/ false,
        ));
        environments
            .update_selections(std::slice::from_ref(&selection), &test_environment_config());
        let snapshot_task = tokio::spawn({
            let environments = Arc::clone(&environments);
            // Bind the exact collector, independent of the worker's ambient dispatch.
            async move { environments.snapshot().await }.with_subscriber(snapshot_dispatch)
        });
        tokio::task::yield_now().await;
        assert!(!snapshot_task.is_finished());

        let server = tokio::spawn(serve_environment_info(listener));
        let snapshot = timeout(Duration::from_secs(5), snapshot_task)
            .await
            .expect("snapshot should finish after the environment starts")
            .expect("snapshot task");

        assert!(snapshot.starting().next().is_none());
        assert_eq!(snapshot.to_selections(), vec![selection]);
        server.await.expect("server task");

        let logs = String::from_utf8(buffer.lock().expect("buffer lock").clone())
            .expect("UTF-8 tracing output");
        assert!(
            logs.contains(
                "environments.snapshot{environment_count=1 non_blocking=false}:environments.wait_until_ready{environment_id=remote}"
            ),
            "blocking snapshot should contain its environment wait span: {logs}"
        );
        assert!(
            logs.contains(
                "environments.resolve{environment_id=remote remote=true configuration_pending=false}:exec_server.environment.wait_until_ready{remote=true}"
            ),
            "environment resolution should contain the executor connection wait span: {logs}"
        );
        assert!(
            logs.contains(
                "environments.resolve{environment_id=remote remote=true configuration_pending=false}:exec_server.environment.info{remote=true}"
            ),
            "environment resolution should contain the remote environment-info span: {logs}"
        );
    }
    .with_subscriber(dispatch)
    .await;
}
