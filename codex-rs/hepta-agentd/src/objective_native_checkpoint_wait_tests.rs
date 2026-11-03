//! The original detached checkpoint commit waits on the same writer fence
//! across a real Core continuation. Its old coordinator revision must fail
//! after the read lease is acquired, before SQLite can publish a new head.

use super::*;
use pretty_assertions::assert_eq;

struct WaitingCheckpoint {
    started: tokio::sync::Notify,
    result: std::sync::Mutex<Option<tokio::task::JoinHandle<Result<()>>>>,
    payload: OnceLock<Vec<u8>>,
}

struct FenceExecutor {
    original: Arc<dyn HostedTurnExecutor>,
    stop: Arc<CheckpointStop>,
    attempt: Arc<WaitingCheckpoint>,
}

impl HostedTurnExecutor for FenceExecutor {
    fn executor_id(&self) -> &str { self.original.executor_id() }
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        self.original.prepare(input)
    }
    fn observe_admission<'a>(&'a self, input: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(input)
    }
    fn resume_preparation<'a>(&'a self, input: HostedPreparationRecoveryInput) -> HostedFuture<'a, HostedTurnPlan> {
        self.original.resume_preparation(input)
    }
    fn supports_checkpoint_continuation(&self) -> bool { self.original.supports_checkpoint_continuation() }
    fn prepare_checkpoint_continuation<'a>(&'a self, input: HostedCheckpointContinuationInput)
        -> HostedFuture<'a, Option<HostedTurnPlan>> {
        Box::pin(async move {
            let setup: Result<_> = async {
                let old = self.stop.retained_worker.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?
                    .take().context("original retained worker disappeared")?;
                let live = input.origin.original_live_thread().clone();
                let first = self.stop.captured.get().context("original checkpoint missing")?.1.clone();
                let session = live.open_native_checkpoint(old.owner.anchor().checkpoint.clone(),
                    NativeCheckpointOpenMode::Recover, old.admission.clone()).await?;
                Ok((old, live, first, session))
            }.await;
            let (old, live, first, session) = setup.map_err(|error|
                codex_protocol::error::CodexErr::InvalidRequest(format!("original checkpoint wait setup: {error:#}")))?;
            let plan = self.original.prepare_checkpoint_continuation(input).await?;
            let plan_present = plan.is_some();
            let setup: Result<()> = async {
                ensure!(plan_present, "actual original continuation was not prepared");
                // The actual returned native plan still holds its original
                // exclusive writer frontier after rearming the same run.
                let mut candidate = old.turn.clone();
                candidate.cancelled = true;
                let payload = crate::native_turn_checkpoint::encode(old.owner.anchor(), &candidate)?;
                ensure!(self.attempt.payload.set(payload.clone()).is_ok(),
                    "old checkpoint was prepared twice");
                let signal = self.attempt.clone();
                let mut task = tokio::spawn(async move {
                    signal.started.notify_one();
                    // Call the real detached store commit with the original
                    // admission/currentness owner and the exact old CAS head.
                    // Do not add a cursor readback that could hide its denial
                    // behind the successor's independently advancing head.
                    let result = live.commit_native_checkpoint(&session,
                        codex_thread_store::NativeCheckpointExpected::Version(first.version),
                        codex_thread_store::NativeCheckpointState { binding: first.state.binding, payload }).await;
                    drop(old);
                    result.map(|_| ()).map_err(anyhow::Error::from)
                });
                tokio::time::timeout(Duration::from_secs(2), self.attempt.started.notified()).await?;
                ensure!(tokio::time::timeout(Duration::from_millis(25), &mut task).await.is_err(),
                    "original checkpoint did not remain pending behind the retained writer fence");
                *self.attempt.result.lock().map_err(|error| anyhow::anyhow!(error.to_string()))? = Some(task);
                Ok(())
            }.await;
            setup.map_err(|error| codex_protocol::error::CodexErr::InvalidRequest(format!("original checkpoint wait fixture: {error:#}")))?;
            Ok(plan)
        })
    }
    fn recover<'a>(&'a self, input: HostedTurnRecoveryInput) -> HostedFuture<'a, HostedTurnOutcome> {
        self.original.recover(input)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn an_original_checkpoint_waiting_on_the_writer_fence_cannot_commit_after_rearm() -> Result<()> {
    let server = provider().await;
    let stop = Arc::new(CheckpointStop::new(StopPoint::RetainOldWorker));
    let attempt = Arc::new(WaitingCheckpoint { started: tokio::sync::Notify::new(),
        result: std::sync::Mutex::new(None), payload: OnceLock::new() });
    let captured = stop.clone();
    let pending = attempt.clone();
    let fixture = ObjectiveFixture::with_executor_adapter(&server, ReplyFault::None, agent(), Arc::new(NoToolCompiler),
        move |original, native| {
            let original = Arc::new(StopAtCheckpointExecutor { original, native, stop: captured.clone() });
            Arc::new(FenceExecutor { original, stop: captured, attempt: pending })
        }).await?;
    fixture.submit(fixture.request.clone()).await?;
    tokio::time::timeout(Duration::from_secs(10), stop.ready.notified()).await?;
    let held = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::Error(error) => Some(format!("{error:?}")), _ => None,
    }).await;
    assert!(held.contains("outcome is unknown"));
    let (anchor, first, _) = stop.captured.get().context("original first checkpoint")?;
    let epoch = idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?;
    let original = fixture.base.state.require_native_effect(&anchor.checkpoint.operation_id)?;
    fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest {
        turn_id: anchor.checkpoint.turn_id.clone(), expected_epoch: epoch,
        thread_settings: Default::default(), trace: None,
    }).await?;
    assert_eq!(completed_turn(&fixture.core).await?, anchor.checkpoint.turn_id);
    let task = attempt.result.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?
        .take().context("old checkpoint was not attempted under the writer fence")?;
    let error = tokio::time::timeout(Duration::from_secs(2), task).await??.err()
        .context("old checkpoint unexpectedly committed after rearm")?;
    assert!(format!("{error:#}").contains("checkpoint writer revision was replaced"),
        "the rejection must occur after the original read lease is acquired: {error:#}");
    let session = fixture.core.thread_store.open_native_checkpoint(anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let chain = fixture.core.thread_store.load_native_checkpoint_chain(&session).await?;
    assert_eq!(chain.first(), Some(first));
    let rejected = attempt.payload.get().context("old checkpoint candidate missing")?;
    assert!(chain.iter().all(|checkpoint| &checkpoint.state.payload != rejected),
        "the rejected old CAS must never appear in the actual ThreadStore chain");
    assert!(fixture.base.state.native_run_receipt(&original.run_id)?.revision > original.revision);
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 1));
    assert_eq!(server.received_requests().await.context("HTTP capture")?.len(), 1);
    fixture.shutdown().await
}
