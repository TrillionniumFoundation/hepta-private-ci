use super::driver_fixture;
use crate::unified_exec::ProcessEntry;
use crate::unified_exec::UnifiedExecProcessManager;
use crate::unified_exec::process::NoopSpawnLifecycle;
use crate::unified_exec::process::UnifiedExecProcess;
use anyhow::Context;
use anyhow::Result;
use codex_sandboxing::SandboxType;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::Instant;

const PROCESS_ID: i32 = 7301;

struct RegisteredFixture {
    manager: Arc<UnifiedExecProcessManager>,
    process: Arc<UnifiedExecProcess>,
    exit_tx: Option<oneshot::Sender<i32>>,
    terminations: Arc<AtomicUsize>,
    _stdout_tx: broadcast::Sender<Vec<u8>>,
    _writer_rx: mpsc::Receiver<Vec<u8>>,
}

impl RegisteredFixture {
    async fn new() -> Result<Self> {
        let fixture = driver_fixture();
        let process = Arc::new(
            UnifiedExecProcess::from_spawned(
                fixture.spawned,
                SandboxType::None,
                Box::new(NoopSpawnLifecycle),
            )
            .await?,
        );
        let manager = Arc::new(UnifiedExecProcessManager::default());
        {
            let mut store = manager.process_store.lock().await;
            store.reserved_process_ids.insert(PROCESS_ID);
            store.processes.insert(
                PROCESS_ID,
                ProcessEntry {
                    process: Arc::clone(&process),
                    plugin_metrics_sidecar: None,
                    call_id: "deadline-observation".to_string(),
                    process_id: PROCESS_ID,
                    cwd: PathUri::parse("file:///tmp")?,
                    initial_exec_command_active: Arc::new(AtomicBool::new(false)),
                    hook_command: "original-driver".to_string(),
                    tty: false,
                    network_approval: None,
                    session: Weak::new(),
                    last_used: Instant::now(),
                },
            );
        }
        Ok(Self {
            manager,
            process,
            exit_tx: Some(fixture.exit_tx),
            terminations: fixture.terminations,
            _stdout_tx: fixture.stdout_tx,
            _writer_rx: fixture.writer_rx,
        })
    }

    fn native_exit(&mut self, code: i32) -> Result<()> {
        self.exit_tx
            .take()
            .context("original driver result already consumed")?
            .send(code)
            .map_err(|_| anyhow::anyhow!("original driver exit receiver closed"))
    }

    async fn wait_for_exit(&self) -> Result<()> {
        let mut state = self.process.state_rx.clone();
        tokio::time::timeout(
            Duration::from_secs(2),
            state.wait_for(|value| value.has_exited),
        )
        .await??;
        Ok(())
    }

    async fn original_entry_is_retained(&self) -> bool {
        let store = self.manager.process_store.lock().await;
        store.reserved_process_ids.contains(&PROCESS_ID)
            && store
                .processes
                .get(&PROCESS_ID)
                .is_some_and(|entry| Arc::ptr_eq(&entry.process, &self.process))
    }
}

#[tokio::test]
async fn explicit_deadline_waits_for_original_result_before_removing_entry() -> Result<()> {
    let mut fixture = RegisteredFixture::new().await?;
    let manager = Arc::clone(&fixture.manager);
    let mut operation = Box::pin(
        manager.terminate_process_until(PROCESS_ID, Instant::now() + Duration::from_secs(2)),
    );
    assert!(futures::poll!(operation.as_mut()).is_pending());
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 1);
    assert!(fixture.original_entry_is_retained().await);
    assert!(!fixture.process.has_exited());
    fixture.native_exit(71)?;
    assert!(operation.await);
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), Some(71));
    assert!(!fixture.original_entry_is_retained().await);
    Ok(())
}

#[tokio::test]
async fn expired_deadline_never_requests_termination_or_releases_entry() -> Result<()> {
    let mut fixture = RegisteredFixture::new().await?;
    assert!(
        !fixture
            .manager
            .terminate_process_until(PROCESS_ID, Instant::now())
            .await
    );
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.process.failure_message(), None);
    assert!(fixture.original_entry_is_retained().await);
    fixture.native_exit(73)?;
    fixture.wait_for_exit().await?;
    Ok(())
}

#[tokio::test]
async fn deadline_waiter_loss_retains_original_entry_without_fake_exit() -> Result<()> {
    let mut fixture = RegisteredFixture::new().await?;
    let manager = Arc::clone(&fixture.manager);
    let mut operation = Box::pin(
        manager.terminate_process_until(PROCESS_ID, Instant::now() + Duration::from_secs(2)),
    );
    assert!(futures::poll!(operation.as_mut()).is_pending());
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 1);
    drop(fixture.exit_tx.take());
    assert!(!operation.await);
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    assert!(fixture.process.failure_message().is_some());
    assert!(fixture.original_entry_is_retained().await);
    Ok(())
}

#[tokio::test]
async fn explicit_deadline_also_bounds_store_lock_before_effect() -> Result<()> {
    let mut fixture = RegisteredFixture::new().await?;
    let store = fixture.manager.process_store.lock().await;
    assert!(
        !fixture
            .manager
            .terminate_process_until(PROCESS_ID, Instant::now() + Duration::from_secs(2))
            .await
    );
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 0);
    assert!(store.processes.contains_key(&PROCESS_ID));
    assert!(store.reserved_process_ids.contains(&PROCESS_ID));
    assert_eq!(fixture.process.failure_message(), None);
    drop(store);
    fixture.native_exit(79)?;
    fixture.wait_for_exit().await?;
    Ok(())
}

#[tokio::test]
async fn cancelled_deadline_observation_keeps_owner_and_late_native_fact() -> Result<()> {
    let mut fixture = RegisteredFixture::new().await?;
    let manager = Arc::clone(&fixture.manager);
    let mut operation = Box::pin(
        manager.terminate_process_until(PROCESS_ID, Instant::now() + Duration::from_secs(2)),
    );
    assert!(futures::poll!(operation.as_mut()).is_pending());
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 1);
    drop(operation);
    assert!(!fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), None);
    let failure = fixture
        .process
        .failure_message()
        .context("cancelled observation")?;
    assert!(fixture.original_entry_is_retained().await);
    fixture.native_exit(83)?;
    fixture.wait_for_exit().await?;
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), Some(83));
    assert_eq!(fixture.process.failure_message(), Some(failure));
    assert!(fixture.original_entry_is_retained().await);
    Ok(())
}

#[tokio::test]
async fn post_exit_store_lock_timeout_retains_entry_and_original_result() -> Result<()> {
    let mut fixture = RegisteredFixture::new().await?;
    let manager = Arc::clone(&fixture.manager);
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut operation = Box::pin(manager.terminate_process_until(PROCESS_ID, deadline));
    assert!(futures::poll!(operation.as_mut()).is_pending());
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 1);

    let store = manager.process_store.lock().await;
    fixture.native_exit(89)?;
    let mut observed = fixture.process.state_rx.clone();
    tokio::time::timeout_at(deadline, observed.wait_for(|state| state.has_exited)).await??;
    assert_eq!(fixture.process.exit_code(), Some(89));
    assert!(futures::poll!(operation.as_mut()).is_pending());

    let first_result = operation.await;
    assert!(!first_result);
    assert!(store.reserved_process_ids.contains(&PROCESS_ID));
    assert!(
        store
            .processes
            .get(&PROCESS_ID)
            .is_some_and(|entry| Arc::ptr_eq(&entry.process, &fixture.process))
    );
    assert!(fixture.process.has_exited());
    assert_eq!(fixture.process.exit_code(), Some(89));
    assert_eq!(fixture.process.failure_message(), None);
    drop(store);
    assert!(!first_result);
    assert!(fixture.original_entry_is_retained().await);
    assert_eq!(fixture.terminations.load(Ordering::SeqCst), 1);
    Ok(())
}
