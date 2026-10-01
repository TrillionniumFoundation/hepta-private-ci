use super::*;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn ephemeral_retention_blocks_idle_unload_only_for_original_runtime() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let original = test_codex()
        .with_config(|config| config.ephemeral = true)
        .build(&server)
        .await?;
    let replacement = test_codex()
        .with_config(|config| config.ephemeral = true)
        .build(&server)
        .await?;
    let (_subscribers_tx, subscribers) = watch::channel(false);
    let (_status_tx, status) = watch::channel(ThreadStatus::Idle);
    let (retention, retained) = watch::channel(None);
    // Exercise the real 30-minute policy with an already-idle runtime, without
    // changing the production deadline or waiting for it in this regression.
    assert_eq!(THREAD_UNLOADING_DELAY, Duration::from_secs(1_800));
    let idle_since = Instant::now() - THREAD_UNLOADING_DELAY - Duration::from_secs(1);
    let mut state = UnloadingState {
        delay: THREAD_UNLOADING_DELAY,
        has_subscribers_rx: subscribers,
        has_subscribers: (false, idle_since),
        thread_status_rx: status,
        is_active: (false, idle_since),
        retained_runtime_rx: retained,
        runtime: Arc::downgrade(&original.codex),
    };
    assert!(
        state.should_unload_now(),
        "ordinary idle policy is unchanged"
    );
    retention.send_replace(Some(Arc::downgrade(&original.codex)));
    assert!(!state.should_unload_now());
    assert!(
        tokio::time::timeout(
            Duration::from_millis(25),
            state.wait_for_unloading_trigger()
        )
        .await
        .is_err(),
        "retained uncertain execution must remain loaded beyond ordinary TTL"
    );
    // An unrelated Core Arc, even if a stale ID entry survives, cannot inherit
    // the original retention or prevent unloading this original runtime.
    retention.send_replace(Some(Arc::downgrade(&replacement.codex)));
    assert!(state.should_unload_now());
    retention.send_replace(Some(Arc::downgrade(&original.codex)));
    assert!(!state.should_unload_now());
    retention.send_replace(None);
    assert!(state.wait_for_unloading_trigger().await);
    original.codex.shutdown_and_wait().await?;
    replacement.codex.shutdown_and_wait().await?;
    Ok(())
}
