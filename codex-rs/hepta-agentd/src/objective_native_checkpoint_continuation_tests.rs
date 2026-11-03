//! Real signed Objective/Queue/Core continuation after a technical held result.
//! The first execution stops after the original checkpoint and Queue commit;
//! it neither cancels Core nor fabricates a crash or a terminal result.

use super::*;
use std::sync::OnceLock;
use codex_core::hosted_turn::{HostedAdmittedTurn, HostedCheckpointContinuationInput, HostedFuture,
    HostedPreparationRecoveryInput, HostedTurnExecution, HostedTurnExecutor, HostedTurnInput,
    HostedTurnObservation, HostedTurnOutcome, HostedTurnPlan, HostedTurnRecoveryInput};
use codex_hepta_native_agent::TurnOwner;
use codex_hepta_memory::ProductionEntryCurrentness;
use crate::NativeTurnAdmission;
use codex_thread_store::{QueueStore, StoredNativeCheckpoint};
use pretty_assertions::assert_eq;

#[derive(Clone, Copy)]
enum StopPoint { Pristine, AfterOperationAdmission, RetainOldWorker }

struct CheckpointStop {
    point: StopPoint,
    captured: OnceLock<(NativeTurnAnchorV1, StoredNativeCheckpoint, Option<String>)>,
    ready: tokio::sync::Notify,
    prepares: AtomicUsize,
    continuations: AtomicUsize,
    retained_worker: std::sync::Mutex<Option<crate::native_host::NativePreparedTurn>>,
}

impl CheckpointStop {
    fn new(point: StopPoint) -> Self {
        Self { point, captured: OnceLock::new(), ready: tokio::sync::Notify::new(),
            prepares: AtomicUsize::new(0), continuations: AtomicUsize::new(0), retained_worker: std::sync::Mutex::new(None) }
    }
}

struct StopAtCheckpointExecutor {
    original: Arc<dyn HostedTurnExecutor>,
    native: Arc<AgentdNativeHost>,
    stop: Arc<CheckpointStop>,
}

impl HostedTurnExecutor for StopAtCheckpointExecutor {
    fn executor_id(&self) -> &str { self.original.executor_id() }

    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            self.stop.prepares.fetch_add(1, Ordering::SeqCst);
            // Obtain the actual builtin resolver's plan first. The test only
            // replaces its first execution with the same real native prepare
            // plus an early technical result at the selected durable cut.
            let mut plan = self.original.prepare(input).await?;
            let restored: Result<_> = (|| {
                let run_id = plan.correlation.get("run_id").context("original plan run")?;
                let state = self.native.gate.state()?;
                let run = state.native_run_receipt(run_id)?;
                let prepared = state.load_canonical_prepared(run_id)?.context("original canonical Prepared")?;
                let scope = NativeTurnScope {
                    cell_id: StableId::new(plan.correlation.get("cell_id").context("original cell")?)?,
                    organ_id: StableId::new(plan.correlation.get("organ_id").context("original organ")?)?,
                    final_scope_id: StableId::new(plan.correlation.get("final_scope_id").context("original scope")?)?,
                };
                Ok((run, scope, prepared.context().clone()))
            })();
            let (run, scope, context) = restored.map_err(|error| codex_protocol::error::CodexErr::InvalidRequest(error.to_string()))?;
            plan.execution = Box::new(StopAtCheckpointExecution {
                native: self.native.clone(), stop: self.stop.clone(), run, scope, context,
            });
            Ok(plan)
        })
    }

    fn observe_admission<'a>(&'a self, observation: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(observation)
    }

    fn resume_preparation<'a>(&'a self, input: HostedPreparationRecoveryInput) -> HostedFuture<'a, HostedTurnPlan> {
        self.original.resume_preparation(input)
    }

    fn supports_checkpoint_continuation(&self) -> bool { self.original.supports_checkpoint_continuation() }

    fn prepare_checkpoint_continuation<'a>(&'a self, input: HostedCheckpointContinuationInput)
        -> HostedFuture<'a, Option<HostedTurnPlan>> {
        self.stop.continuations.fetch_add(1, Ordering::SeqCst);
        self.original.prepare_checkpoint_continuation(input)
    }

    fn recover<'a>(&'a self, input: HostedTurnRecoveryInput) -> HostedFuture<'a, HostedTurnOutcome> {
        self.original.recover(input)
    }
}

struct StopAtCheckpointExecution {
    native: Arc<AgentdNativeHost>,
    stop: Arc<CheckpointStop>,
    run: RunReceipt,
    scope: NativeTurnScope,
    context: crate::intelligence_product::NativeContextBindingV1,
}

impl HostedTurnExecution for StopAtCheckpointExecution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            let result: Result<_> = async {
                let original = NativeCheckpointBinding {
                    thread_id: turn.thread_id(), turn_id: turn.turn_id().to_owned(),
                    operation_id: self.run.run_id.clone(), generation: self.run.generation,
                    lease_id: self.native.host.writer().lease_id().to_owned(),
                };
                let anchor = NativeTurnAnchorV1 {
                    checkpoint: original.clone(), recovery: turn.recovery().clone(),
                    queue: Some(NativeQueueBindingV1 {
                        queued_item_id: turn.queue().queued_item_id.clone(),
                        client_id: turn.queue().client_id.clone(), payload_sha256: turn.queue().payload_sha256.clone(),
                    }), run: None, execution: None,
                    rendered_context_sha256: Some(self.context.rendered_context_digest().to_string()),
                };
                let prepared = self.native.prepare_hosted_turn(turn.live_thread().clone(), anchor,
                    self.run.clone(), self.scope.clone(), self.context.clone()).await?;
                prepared.confirm_durable().await?;
                turn.confirm_durable().await?;
                let operation = if matches!(self.stop.point, StopPoint::AfterOperationAdmission) {
                    // The real owner's admission precedes its next checkpoint.
                    // An operation here makes an unchanged revision-1 checkpoint
                    // insufficient to authorize another first request.
                    let body = agent().model_request_body(&prepared.turn)?;
                    ensure!(Digest32::of_bytes(&body).to_string() == turn.recovery().fingerprint_sha256,
                        "first request differs from original Core fingerprint");
                    Some(prepared.owner.admit_model(&prepared.turn.binding, 0, &body).await?.operation_id)
                } else { None };
                let (record, anchor, _) = self.native.read_hosted_checkpoint_record(turn.live_thread(), &original).await?;
                ensure!(record.version.revision == 1, "test cut must be the real first checkpoint");
                ensure!(self.stop.captured.set((anchor, record, operation)).is_ok(), "test cut was reached twice");
                if matches!(self.stop.point, StopPoint::RetainOldWorker) {
                    // An independent non-cooperating worker deliberately keeps
                    // the actual original Dispatched guard after Core is idle.
                    // New continuation must advance that same run revision.
                    *self.stop.retained_worker.lock().map_err(|error| anyhow::anyhow!(error.to_string()))? = Some(prepared);
                } else { drop(prepared); }
                self.stop.ready.notify_one();
                Ok(HostedTurnOutcome::PendingObservation)
            }.await;
            result.map_err(|error| codex_protocol::error::CodexErr::InvalidRequest(format!("original checkpoint fixture: {error:#}")))
        })
    }
}

async fn stopped_fixture(server: &MockServer, point: StopPoint) -> Result<(ObjectiveFixture, Arc<CheckpointStop>)> {
    let stop = Arc::new(CheckpointStop::new(point));
    let captured = stop.clone();
    let fixture = ObjectiveFixture::with_executor_adapter(server, ReplyFault::None, agent(), Arc::new(NoToolCompiler),
        move |original, native| Arc::new(StopAtCheckpointExecutor { original, native, stop: captured })).await?;
    fixture.submit(fixture.request.clone()).await?;
    tokio::time::timeout(Duration::from_secs(10), stop.ready.notified()).await?;
    let held = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::Error(error) => Some(format!("{error:?}")), _ => None,
    }).await;
    ensure!(held.contains("outcome is unknown"), "first execution must be technically held: {held}");
    Ok((fixture, stop))
}

async fn idle_epoch(test: &TestCodex, turn_id: &str) -> Result<u64> {
    Ok(tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Some(epoch) = test.codex.recovery_epoch_if_idle(turn_id).await { return epoch; }
            tokio::task::yield_now().await;
        }
    }).await.context("original Core retained turn did not become idle")?)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_persisted_queue_and_pristine_checkpoint_continue_the_same_turn_once() -> Result<()> {
    let server = provider().await;
    let (fixture, stop) = stopped_fixture(&server, StopPoint::Pristine).await?;
    let (anchor, first, operation) = stop.captured.get().context("actual first checkpoint")?;
    assert!(operation.is_none());
    let turn_id = anchor.checkpoint.turn_id.clone();
    let queue = anchor.queue.as_ref().context("original Queue identity")?;
    let epoch = idle_epoch(&fixture.core, &turn_id).await?;
    assert_eq!(fixture.base.state.native_run_receipt(&anchor.checkpoint.operation_id)?.phase, RunPhase::Indeterminate);
    let persisted = fixture.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
        queue.client_id.clone(), queue.payload_sha256.clone()).await?.context("original Queue persisted binding")?;
    assert_eq!(persisted.turn_id, turn_id);
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (0, 0));
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    let reply = fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest {
        turn_id: turn_id.clone(), expected_epoch: epoch, thread_settings: Default::default(), trace: None,
    }).await?;
    assert_eq!(reply, codex_core::StartIfIdleSubmission::Started { turn_id: turn_id.clone() });
    assert_eq!(completed_turn(&fixture.core).await?, turn_id);
    let replay = fixture.submit(fixture.request.clone()).await?;
    assert!(replay.idempotent, "the same signed input remains the original completed Queue binding");
    assert_eq!(fixture.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
        queue.client_id.clone(), queue.payload_sha256.clone()).await?, Some(persisted));
    assert!(fixture.queue.service()?.list(anchor.checkpoint.thread_id).await?.is_empty());
    assert_eq!((stop.prepares.load(Ordering::SeqCst), stop.continuations.load(Ordering::SeqCst),
        fixture.owners.calls.load(Ordering::SeqCst)), (1, 1, 1));
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 1));
    let requests = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(requests.len(), 1);
    let operation = requests[0].headers.get("idempotency-key").context("same original model operation")?.to_str()?;
    assert_eq!(fixture.base.writer.status(operation).await?, LocalOutcomeState::Committed);
    let session = fixture.core.thread_store.open_native_checkpoint(anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let chain = fixture.core.thread_store.load_native_checkpoint_chain(&session).await?;
    assert_eq!(chain.first(), Some(first), "continuation must not replace the original checkpoint");
    let last = chain.last().context("continued checkpoint")?;
    let (after_anchor, after) = crate::native_turn_checkpoint::decode(&last.state.payload, &anchor.checkpoint)?;
    assert_eq!(after_anchor, *anchor);
    assert_eq!((after.model_calls, after.tool_calls, after.final_answer.as_deref()), (1, 0, Some("native owner complete")));
    let history = fixture.core.thread_store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: fixture.core.session_configured.thread_id, include_archived: false,
    }).await?;
    let inputs = history.items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
            TurnItem::UserMessage(message) if message.client_id.as_deref() == Some(queue.client_id.as_str())))).count();
    let bindings = history.items.iter().filter_map(|item| match item {
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn_id => Some(binding), _ => None,
    }).collect::<Vec<_>>();
    assert_eq!(inputs, 1);
    assert_eq!(bindings.len(), 2);
    assert_eq!(bindings[0], &anchor.recovery);
    assert_eq!(bindings[1].generation, bindings[0].generation + 1);
    assert_eq!(bindings[1].replay_applied_from_generation, Some(bindings[0].generation));
    assert!(!history.items.iter().any(|item| matches!(item, RolloutItem::EventMsg(EventMsg::TurnAborted(_)))));
    assert!(fixture.core.codex.recovery_epoch_if_idle(&turn_id).await.is_none());
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn revision_one_with_an_original_admitted_operation_cannot_restart_the_first_request() -> Result<()> {
    let server = provider().await;
    let (fixture, stop) = stopped_fixture(&server, StopPoint::AfterOperationAdmission).await?;
    let (anchor, first, operation) = stop.captured.get().context("actual admitted-operation cut")?;
    let operation = operation.as_ref().context("actual original admission")?;
    let turn_id = anchor.checkpoint.turn_id.clone();
    let epoch = idle_epoch(&fixture.core, &turn_id).await?;
    assert_eq!(fixture.base.writer.status(operation).await?, LocalOutcomeState::Queued);
    let reply = fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest {
        turn_id: turn_id.clone(), expected_epoch: epoch, thread_settings: Default::default(), trace: None,
    }).await?;
    assert_eq!(reply, codex_core::StartIfIdleSubmission::Started { turn_id: turn_id.clone() });
    let error = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::Error(error) => Some(format!("{error:?}")), _ => None,
    }).await;
    assert!(error.contains("scope already admitted an operation"), "must reject the original writer frontier: {error}");
    idle_epoch(&fixture.core, &turn_id).await?;
    let session = fixture.core.thread_store.open_native_checkpoint(anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    assert_eq!(fixture.core.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(first.clone()));
    assert_eq!(fixture.base.writer.status(operation).await?, LocalOutcomeState::Queued);
    assert_eq!(fixture.base.state.native_run_receipt(&anchor.checkpoint.operation_id)?.phase, RunPhase::Indeterminate);
    assert_eq!((stop.prepares.load(Ordering::SeqCst), fixture.owners.calls.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 1, 0, 0));
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn a_new_core_continuation_invalidates_the_old_dispatched_guard_and_admission() -> Result<()> {
    let server = provider().await;
    let (fixture, stop) = stopped_fixture(&server, StopPoint::RetainOldWorker).await?;
    let (anchor, _, _) = stop.captured.get().context("original checkpoint")?;
    let turn_id = anchor.checkpoint.turn_id.clone();
    let epoch = idle_epoch(&fixture.core, &turn_id).await?;
    let old = stop.retained_worker.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?
        .as_ref().context("retained old worker")?.admission.clone();
    let old_revision = old.fresh_revision.context("old actual dispatched revision")?;
    assert_eq!(fixture.base.state.require_native_effect(&anchor.checkpoint.operation_id)?.revision, old_revision);
    let released = Arc::new(tokio::sync::Notify::new());
    let (release, receiver) = std::sync::mpsc::sync_channel::<()>(1);
    let signal = released.clone();
    let retained = stop.clone();
    let state = fixture.base.state.clone();
    let run_id = anchor.checkpoint.operation_id.clone();
    *fixture.base.issuer.before_grant_return.lock().map_err(|error| anyhow::anyhow!(error.to_string()))? = Some(Box::new(move || {
        let worker = retained.retained_worker.lock().map_err(|error| AgentdError::Invalid(error.to_string()))?.take()
            .ok_or_else(|| AgentdError::Invalid("old worker disappeared".to_owned()))?;
        drop(worker);
        let current = state.require_native_effect(&run_id)?;
        if current.revision <= old_revision {
            return Err(AgentdError::Invalid("new Core task reused its predecessor's dispatch revision".to_owned()));
        }
        signal.notify_one();
        receiver.recv_timeout(Duration::from_secs(10))
            .map_err(|error| AgentdError::Invalid(format!("continuation grant barrier: {error}")))?;
        Ok(())
    }));
    fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest {
        turn_id: turn_id.clone(), expected_epoch: epoch, thread_settings: Default::default(), trace: None,
    }).await?;
    tokio::time::timeout(Duration::from_secs(10), released.notified()).await?;
    let resumed = fixture.base.state.require_native_effect(&anchor.checkpoint.operation_id)?;
    assert!(resumed.revision > old_revision);
    assert_eq!(resumed.phase, RunPhase::Dispatched, "dropping the old guard must not change its successor");
    assert!(fixture.base.state.restore_native_run(anchor.run.clone().context("original checkpoint run")?).is_err(),
        "a late observer must not downgrade the new dispatched owner");
    for phase in [RunPhase::Succeeded, RunPhase::Indeterminate] {
        assert!(fixture.base.state.observe_native_run_at_revision(&anchor.checkpoint.operation_id, old_revision, phase).is_err(),
            "the old worker cannot publish its result over the new dispatch");
    }
    let (_, initial) = crate::native_turn_checkpoint::decode(
        &stop.captured.get().context("first checkpoint")?.1.state.payload, &anchor.checkpoint)?;
    let body = agent().model_request_body(&initial)?;
    let stale_key = old.operation_id("model", "1")?;
    let error = old.admit_model(&initial.binding, 1, &body).await.err().context("old admission revived")?;
    assert!(error.to_string().contains("revision"));
    assert!(fixture.base.writer.resolve_operation_request(&stale_key, fixture.base.native.model.destination_id()).await.is_err(),
        "a stale owner must not append an operation in the successor's original scope");
    let current_key = old.operation_id("model", "0")?;
    let current_request = fixture.base.writer.resolve_operation_request(&current_key, fixture.base.native.model.destination_id()).await?;
    let mut stale_entries = 0;
    assert!(old.enter(&current_request, &mut || { stale_entries += 1; Ok(()) }).is_err(),
        "old revision must fail inside the original final-entry owner locks");
    assert_eq!(stale_entries, 0);
    let restored = fixture.base.state.load_canonical_prepared(&anchor.checkpoint.operation_id)?.context("original Prepared")?;
    let anticipated = fixture.base.native.admission_with_policy(anchor.checkpoint.clone(), old.scope.clone(),
        old.original_policy_generation, &restored.attached_run_receipt())?;
    assert_eq!(anticipated.fresh_revision, Some(old_revision));
    assert!(anticipated.admit_model(&initial.binding, 1, &body).await.is_err(),
        "an original initial plan cannot regain its predicted dispatch revision");
    assert!(anticipated.enter(&current_request, &mut || { stale_entries += 1; Ok(()) }).is_err());
    assert_eq!(stale_entries, 0);
    assert_eq!(fixture.base.state.require_native_effect(&anchor.checkpoint.operation_id)?, resumed);
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 0));
    release.send(())?;
    assert_eq!(completed_turn(&fixture.core).await?, turn_id);
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 1));
    assert_eq!(server.received_requests().await.context("HTTP capture")?.len(), 1);
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn an_old_observer_cannot_write_after_a_new_continuation_returns_to_indeterminate() -> Result<()> {
    let server = provider().await;
    let (fixture, stop) = stopped_fixture(&server, StopPoint::Pristine).await?;
    let (anchor, _, _) = stop.captured.get().context("original checkpoint")?;
    let run_id = anchor.checkpoint.operation_id.clone();
    let turn_id = anchor.checkpoint.turn_id.clone();
    let epoch = idle_epoch(&fixture.core, &turn_id).await?;
    let observed = fixture.base.state.native_run_receipt(&run_id)?;
    assert_eq!(observed.phase, RunPhase::Indeterminate);
    let captured = Arc::new(OnceLock::new());
    let published = captured.clone();
    let state = fixture.base.state.clone();
    let expected = observed.revision;
    let callback_run = run_id.clone();
    *fixture.base.issuer.before_grant_return.lock().map_err(|error| anyhow::anyhow!(error.to_string()))? = Some(Box::new(move || {
        let live = state.require_native_effect(&callback_run)?;
        if live.revision <= expected {
            return Err(AgentdError::Invalid("continuation did not replace its original observer revision".to_owned()));
        }
        // The actual new execution owner publishes a technical unknown result.
        // This exercises its original reducer, not a direct record mutation.
        let held = state.observe_native_run_at_revision(&callback_run, live.revision, RunPhase::Indeterminate)?;
        if held.revision <= expected + 1 || held.phase != RunPhase::Indeterminate {
            return Err(AgentdError::Invalid("new execution did not advance through an unknown disposition".to_owned()));
        }
        published.set(held).map_err(|_| AgentdError::Invalid("technical result was published twice".to_owned()))?;
        Ok(())
    }));
    fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest {
        turn_id: turn_id.clone(), expected_epoch: epoch, thread_settings: Default::default(), trace: None,
    }).await?;
    let error = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::Error(error) => Some(format!("{error:?}")), _ => None,
    }).await;
    assert!(error.contains("revision") || error.contains("cancelled, expired, or stale"),
        "the relinquished original owner must reject physical entry: {error}");
    idle_epoch(&fixture.core, &turn_id).await?;
    let held = captured.get().context("new execution did not publish its unknown disposition")?;
    assert_eq!(fixture.base.state.native_run_receipt(&run_id)?, *held);
    for phase in [RunPhase::Succeeded, RunPhase::Indeterminate] {
        assert!(fixture.base.state.observe_native_recovery(&run_id, expected, phase).is_err(),
            "a stale observer cannot pass the same-phase early idempotence branch: {phase:?}");
        assert_eq!(fixture.base.state.native_run_receipt(&run_id)?, *held);
    }
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 0));
    fixture.shutdown().await
}

#[path = "objective_native_checkpoint_wait_tests.rs"]
mod checkpoint_wait_tests;

#[path = "objective_native_terminal_continuation_tests.rs"]
mod terminal_continuation_tests;
