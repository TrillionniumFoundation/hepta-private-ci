use super::*;
use codex_hepta_agent_loop::Error;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::future;
use std::sync::Arc;
use tokio::sync::oneshot;

async fn runtime() -> anyhow::Result<(tempfile::TempDir, Arc<StateRuntime>)> {
    let temp = tempfile::tempdir()?;
    let state = StateRuntime::init(
        SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(temp.path().to_path_buf())?),
        "terminal-shutdown-fixture".into(),
    )
    .await?;
    Ok((temp, state))
}

#[tokio::test]
async fn encoded_notification_without_settlement_cannot_close_real_policy() -> anyhow::Result<()> {
    let (_temp, state) = runtime().await?;
    state.get_backfill_state().await?;
    let shutdown = TerminalShutdown::observe(
        future::pending(),
        future::ready(()),
        Duration::from_millis(20),
    )
    .await;
    assert_eq!(
        (shutdown.writes_settled(), shutdown.encoded_recorded()),
        (false, true)
    );
    shutdown.close_if_settled(&state).await;
    state.get_backfill_state().await?;
    state.close().await;
    Ok(())
}

#[tokio::test]
async fn lost_supervisor_is_not_settlement_even_with_encoded_evidence() -> anyhow::Result<()> {
    let (_temp, state) = runtime().await?;
    let shutdown = TerminalShutdown::observe(
        future::ready(Err(Error::Owner("supervisor unavailable".into()))),
        future::ready(()),
        Duration::from_secs(2),
    )
    .await;
    assert_eq!(
        (shutdown.writes_settled(), shutdown.encoded_recorded()),
        (false, true)
    );
    shutdown.close_if_settled(&state).await;
    state.get_backfill_state().await?;
    state.close().await;
    Ok(())
}

#[tokio::test]
async fn settled_writes_allow_real_close_without_claiming_encoded_success() -> anyhow::Result<()> {
    let (_temp, state) = runtime().await?;
    state.get_backfill_state().await?;
    // Both original futures may resolve even when encoded persistence failed.
    // Readiness permits close; the separate evidence flag remains false.
    let shutdown = TerminalShutdown::observe(
        future::ready(Ok(())),
        future::pending(),
        Duration::from_millis(20),
    )
    .await;
    assert_eq!(
        (shutdown.writes_settled(), shutdown.encoded_recorded()),
        (true, false)
    );
    shutdown.close_if_settled(&state).await;
    assert!(state.get_backfill_state().await.is_err());
    Ok(())
}

#[tokio::test]
async fn cancelling_shutdown_wait_does_not_close_real_policy() -> anyhow::Result<()> {
    let (_temp, state) = runtime().await?;
    let observed_state = state.clone();
    let (started, entered) = oneshot::channel();
    let waiter = tokio::spawn(async move {
        let shutdown = TerminalShutdown::observe(
            async {
                let _ = started.send(());
                future::pending().await
            },
            future::ready(()),
            Duration::from_secs(2),
        )
        .await;
        shutdown.close_if_settled(&observed_state).await;
    });
    tokio::time::timeout(Duration::from_secs(2), entered).await??;
    waiter.abort();
    assert!(waiter.await.expect_err("waiter aborted").is_cancelled());
    state.get_backfill_state().await?;
    state.close().await;
    Ok(())
}

#[tokio::test]
async fn real_policy_stays_open_until_supervisor_settlement_arrives() -> anyhow::Result<()> {
    let (_temp, state) = runtime().await?;
    let observed_state = state.clone();
    let (settle, settled) = oneshot::channel();
    let (started, entered) = oneshot::channel();
    let waiter = tokio::spawn(async move {
        let shutdown = TerminalShutdown::observe(
            async {
                let _ = started.send(());
                settled
                    .await
                    .map_err(|_| Error::Owner("supervisor lost".into()))
            },
            future::ready(()),
            Duration::from_secs(2),
        )
        .await;
        shutdown.close_if_settled(&observed_state).await;
        (shutdown.writes_settled(), shutdown.encoded_recorded())
    });
    tokio::time::timeout(Duration::from_secs(2), entered).await??;
    assert!(!waiter.is_finished());
    state.get_backfill_state().await?;
    settle.send(()).expect("settlement receiver remains pending");
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), waiter).await??,
        (true, true)
    );
    assert!(state.get_backfill_state().await.is_err());
    Ok(())
}
