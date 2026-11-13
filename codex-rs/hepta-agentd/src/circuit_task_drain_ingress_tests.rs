//! A synchronous host callback remains admitted until it actually returns.

use pretty_assertions::assert_eq;
use tokio::sync::Notify;

use super::*;

pub(super) struct Gate {
    entered: Notify,
    release: Mutex<std::sync::mpsc::Receiver<()>>,
}

impl Gate {
    fn new() -> (Arc<Self>, std::sync::mpsc::Sender<()>) {
        let (release, receive) = std::sync::mpsc::channel();
        (
            Arc::new(Self {
                entered: Notify::new(),
                release: Mutex::new(receive),
            }),
            release,
        )
    }

    pub(super) fn wait(&self) -> Result<(), crate::AgentdError> {
        self.entered.notify_one();
        self.release
            .lock()
            .expect("callback release")
            .recv_timeout(Duration::from_secs(10))
            .map_err(|_| crate::AgentdError::Protocol("fixture callback release timed out".into()))
    }
}

#[tokio::test]
async fn unavailable_owner_blocks_drain_even_without_a_circuit_profile() -> anyhow::Result<()> {
    let runtime = runtime_fixture();
    let store = AutomationStore::open(&runtime.identity.layout).await?;
    runtime.state.attach_automation_store(store.clone())?;
    assert!(!runtime.state.circuit_task_enabled());
    runtime.state.mark_draining()?;
    assert_eq!(runtime.state.circuit_task_drain_blockers().await?, 0);

    runtime.state.mark_automation_unavailable()?;
    assert!(matches!(
        runtime.state.circuit_task_drain_blockers().await,
        Err(crate::AgentdError::Protocol(_))
    ));
    assert!(matches!(
        crate::runtime::drain_runtime(Arc::clone(&runtime.state)).await,
        Err(crate::AgentdError::Protocol(_))
    ));
    store.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn closing_admission_counts_blocked_build_then_prevents_model_contact() -> anyhow::Result<()>
{
    let mut f = fixture(/*lose_ack*/ false, /*expire*/ false).await?;
    let (gate, release) = Gate::new();
    *f.invocation.build_gate.lock().expect("install build gate") = Some(Arc::clone(&gate));
    let state = Arc::clone(&f.runtime.state);
    let request = f.request.clone();
    let caller = tokio::spawn(async move {
        state
            .response(1, 1, AgentdMethod::ObjectiveStart { request })
            .await
    });
    timeout(Duration::from_secs(5), gate.entered.notified())
        .await
        .expect("build entered");
    assert_eq!(
        f.runtime
            .state
            .circuit_task
            .get()
            .expect("lane")
            .pending_count(),
        0
    );
    assert_eq!(f.store.bounded_circuit_run(RUN).await?, None);
    f.runtime.state.mark_draining()?;
    assert!(!f.runtime.state.objective_admission_ready()?);
    for _ in 0..2 {
        assert_eq!(
            f.runtime.state.circuit_task_drain_blockers().await?,
            1,
            "build holds admission even before a lane or durable run exists"
        );
        tokio::task::yield_now().await;
    }
    release.send(()).expect("release build");
    assert!(
        timeout(Duration::from_secs(5), caller)
            .await?
            .expect("caller joined")
            .is_err()
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    assert!(f.invocation.receipts.lock().expect("results").is_empty());
    assert_eq!(f.store.bounded_circuit_run(RUN).await?, None);
    assert_eq!(f.runtime.state.circuit_task_pending_count(), 0);
    assert_eq!(f.runtime.state.circuit_task_drain_blockers().await?, 0);
    assert!(
        f.runtime
            .state
            .response(
                2,
                1,
                AgentdMethod::ObjectiveStart {
                    request: f.request.clone(),
                }
            )
            .await
            .is_err()
    );
    assert_eq!(
        f.invocation.records.lock().expect("build attempts").len(),
        1
    );
    f.stop().await;
    f.store.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_circuit_keeps_drain_blocked_until_result_callback_returns() -> anyhow::Result<()>
{
    let mut f = fixture(/*lose_ack*/ false, /*expire*/ false).await?;
    let (gate, release) = Gate::new();
    *f.invocation
        .result_gate
        .lock()
        .expect("install result gate") = Some(Arc::clone(&gate));
    let state = Arc::clone(&f.runtime.state);
    let request = f.request.clone();
    let caller = tokio::spawn(async move {
        state
            .response(1, 1, AgentdMethod::ObjectiveStart { request })
            .await
    });
    timeout(Duration::from_secs(5), gate.entered.notified())
        .await
        .expect("result entered");
    let handle = f.runtime.state.circuit_task.get().expect("lane");
    timeout(Duration::from_secs(5), async {
        while handle.pending_count() != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("native lane completed");
    let committed = f
        .store
        .bounded_circuit_committed_trace(RUN)
        .await?
        .expect("committed Circuit");
    assert_eq!(committed.run().outcome(), Some(CircuitExitV2::Succeeded));
    assert_eq!(f.store.circuit_drain_blockers().await?, 0);
    f.runtime.state.mark_draining()?;
    for _ in 0..2 {
        assert_eq!(f.runtime.state.circuit_task_pending_count(), 1);
        assert_eq!(
            f.runtime.state.circuit_task_drain_blockers().await?,
            1,
            "a terminal Circuit and idle lane do not hide its blocked result sink"
        );
        tokio::task::yield_now().await;
    }
    release.send(()).expect("release result");
    assert!(
        timeout(Duration::from_secs(5), caller)
            .await?
            .expect("caller joined")
            .is_err(),
        "post-publication readiness is revalidated after drain closes admission"
    );
    assert_eq!(f.runtime.state.circuit_task_pending_count(), 0);
    assert_eq!(f.runtime.state.circuit_task_drain_blockers().await?, 0);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    assert_eq!(f.invocation.receipts.lock().expect("results").len(), 1);
    assert_eq!(
        f.store.bounded_circuit_committed_trace(RUN).await?,
        Some(committed)
    );
    f.stop().await;
    f.store.close().await;
    Ok(())
}

#[tokio::test]
async fn late_ready_and_generation_refresh_cannot_reopen_draining_ingress() -> anyhow::Result<()> {
    let mut f = fixture(/*lose_ack*/ false, /*expire*/ false).await?;
    let generation = f.runtime.state.current_generation()?;
    let supervisor = f
        .runtime
        .registry
        .load_agent(&f.runtime.identity.agent_id)?;
    assert_eq!(supervisor.lifecycle.lifecycle, AgentLifecycle::Running);
    assert_eq!(supervisor.lifecycle.generation, generation);
    assert!(f.runtime.state.objective_admission_ready()?);

    f.runtime.state.mark_draining()?;
    f.runtime.state.mark_app_server_ready()?;
    f.runtime.state.refresh_generation()?;
    assert_eq!(f.runtime.state.current_generation()?, generation);
    assert!(!f.runtime.state.objective_admission_ready()?);
    assert!(
        f.runtime
            .state
            .response(
                1,
                1,
                AgentdMethod::ObjectiveStart {
                    request: f.request.clone(),
                }
            )
            .await
            .is_err()
    );
    assert!(!f.runtime.state.objective_admission_ready()?);
    assert_eq!(f.calls.load(Ordering::SeqCst), 0);
    assert!(
        f.invocation
            .records
            .lock()
            .expect("build attempts")
            .is_empty()
    );
    assert!(f.invocation.receipts.lock().expect("results").is_empty());
    assert_eq!(f.store.bounded_circuit_run(RUN).await?, None);
    let supervisor = f
        .runtime
        .registry
        .load_agent(&f.runtime.identity.agent_id)?;
    assert_eq!(supervisor.lifecycle.lifecycle, AgentLifecycle::Running);
    assert_eq!(supervisor.lifecycle.generation, generation);
    f.stop().await;
    f.store.close().await;
    Ok(())
}
