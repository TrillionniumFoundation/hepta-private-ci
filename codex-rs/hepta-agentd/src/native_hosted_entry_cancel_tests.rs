//! Adversarial final-entry composition: an already in-flight transport worker
//! deliberately outlives Core cancellation. This isolates the real Core gate;
//! it is not a test of the engine's cooperative cancellation/monitor loop.

use super::*;
use codex_core::hosted_turn::HostedTurnEntry;
use codex_hepta_native_agent::{ModelPort, ModelRequest, TurnOwner};
use pretty_assertions::assert_eq;
use crate::native_ports::{NativeEntryOwner, NativeProductionPorts};

#[derive(Clone)]
struct CapturedCoreEntry {
    entry: Arc<HostedTurnEntry>,
    cancellation: CancellationToken,
    thread_id: ThreadId,
    turn_id: String,
    request: ModelRequest,
}

#[derive(Default)]
pub(super) struct EntryProbe {
    captured: OnceLock<CapturedCoreEntry>,
    child: Mutex<Option<tokio::task::JoinHandle<Result<String>>>>,
}

pub(super) struct EntryProbeExecutor {
    pub(super) original: Arc<dyn HostedTurnExecutor>,
    pub(super) native: Arc<AgentdNativeHost>,
    pub(super) resolver: Arc<OriginalResolver>,
    pub(super) probe: Arc<EntryProbe>,
}

impl HostedTurnExecutor for EntryProbeExecutor {
    fn executor_id(&self) -> &str { self.original.executor_id() }

    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            let original = NativeCheckpointBinding {
                thread_id: input.thread_id, turn_id: input.turn_id.clone(),
                operation_id: self.resolver.run.run_id.clone(), generation: self.resolver.run.generation,
                lease_id: self.native.host.writer().lease_id().to_owned(),
            };
            let queue = input.queue.clone();
            let mut plan = self.original.prepare(input).await?;
            plan.execution = Box::new(EntryProbeExecution {
                native: self.native.clone(), resolver: self.resolver.clone(), probe: self.probe.clone(),
                original, queue, fingerprint: plan.request_fingerprint_sha256.clone(),
                correlation: plan.correlation.clone(), executor_id: self.executor_id().to_owned(),
            });
            Ok(plan)
        })
    }

    fn observe_admission<'a>(&'a self, input: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(input)
    }

    fn recover<'a>(&'a self, input: HostedTurnRecoveryInput) -> HostedFuture<'a, HostedTurnOutcome> {
        self.original.recover(input)
    }
}

struct EntryProbeExecution {
    native: Arc<AgentdNativeHost>,
    resolver: Arc<OriginalResolver>,
    probe: Arc<EntryProbe>,
    original: NativeCheckpointBinding,
    queue: codex_core::hosted_turn::HostedQueueBinding,
    fingerprint: String,
    correlation: BTreeMap<String, String>,
    executor_id: String,
}

fn probe_error(error: impl std::fmt::Display) -> codex_protocol::error::CodexErr {
    codex_protocol::error::CodexErr::InvalidRequest(format!("native Core entry probe: {error}"))
}

impl HostedTurnExecution for EntryProbeExecution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        let Self { native, resolver, probe, original, queue, fingerprint, correlation, executor_id } = *self;
        Box::pin(async move {
            let preparation: Result<_> = async {
                ensure!(turn.thread_id() == original.thread_id && turn.turn_id() == original.turn_id
                    && turn.queue() == &queue && turn.recovery().fingerprint_sha256 == fingerprint,
                    "entry probe changed the actual adapter plan");
                let provenance = codex_core::hosted_turn::HostedTurnProvenance::from_recovery(turn.recovery())?
                    .context("actual Core hosted provenance")?;
                ensure!(provenance.executor_id == executor_id && provenance.correlation == correlation
                    && provenance.queue == queue, "entry probe lost original correlation");
                let anchor = NativeTurnAnchorV1 {
                    checkpoint: original, recovery: turn.recovery().clone(),
                    queue: Some(NativeQueueBindingV1 {
                        queued_item_id: queue.queued_item_id, client_id: queue.client_id, payload_sha256: queue.payload_sha256,
                    }),
                    run: None, execution: None,
                    rendered_context_sha256: Some(resolver.context.rendered_context_digest().to_string()),
                };
                let prepared = native.prepare_hosted_turn(turn.live_thread().clone(), anchor,
                    resolver.run.clone(), resolver.scope.clone(), resolver.context.clone()).await?;
                prepared.confirm_durable().await?;
                Ok(prepared)
            }.await;
            let mut prepared = preparation.map_err(probe_error)?;
            // Same first native checkpoint and original ext/queue commit as
            // the production hosted execution, before any operation admission.
            turn.confirm_durable().await?;
            let admission: Result<ModelRequest> = async {
                ensure!(prepared.turn.model_calls == 0 && prepared.turn.pending_model.is_none(),
                    "entry probe requires the original first model operation");
                let body = agent().model_request_body(&prepared.turn)?;
                ensure!(Digest32::of_bytes(&body).to_string() == fingerprint,
                    "entry probe changed Core's exact first model fingerprint");
                let request = prepared.owner.admit_model(&prepared.turn.binding,
                    prepared.turn.model_calls, &body).await?;
                prepared.turn.pending_model = Some(request.clone());
                prepared.turn.model_calls += 1;
                prepared.owner.checkpoint(&prepared.turn).await?;
                Ok(request)
            }.await;
            let request = admission.map_err(probe_error)?;
            let entry = Arc::clone(turn.entry());
            probe.captured.set(CapturedCoreEntry {
                entry: Arc::clone(&entry), cancellation: turn.cancellation().clone(),
                thread_id: turn.thread_id(), turn_id: turn.turn_id().to_owned(), request: request.clone(),
            }).map_err(|_| probe_error("original Core entry was captured twice"))?;
            let ports = NativeProductionPorts {
                admission: prepared.admission.clone(), model: native.model.clone(), runtime: native.runtime.clone(),
                entry_owner: NativeEntryOwner::Core(entry),
            };
            let state = native.gate.state().map_err(probe_error)?;
            let run_id = resolver.run.run_id.clone();
            let child = tokio::spawn(async move {
                // Keep the actual prepared owner and its original active guard
                // alive. Core abort must not be replaced by Agentd cancellation.
                ensure!(state.require_native_effect(&run_id)?.phase == RunPhase::Dispatched,
                    "original Agentd owner was already fenced");
                let error = ports.open(&request).await.err()
                    .context("cancelled Core turn reached the model transport")?;
                ensure!(state.require_native_effect(&run_id)?.phase == RunPhase::Dispatched,
                    "another owner gate masked the Core entry rejection");
                drop(prepared);
                Ok(format!("{error:#}"))
            });
            {
                let mut slot = probe.child.lock().map_err(probe_error)?;
                if slot.is_some() { return Err(probe_error("entry probe already owns its original worker")); }
                *slot = Some(child);
            }
            // This is the real Core task. Only the deliberately retained
            // transport worker ignores cooperative cancellation; it still
            // carries Core's exact opaque entry handle to the physical gate.
            turn.cancellation().cancelled().await;
            Ok(HostedTurnOutcome::Cancelled)
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_core_abort_after_signed_grant_blocks_the_real_native_model_entry() -> Result<()> {
    let server = provider().await;
    let probe = Arc::new(EntryProbe::default());
    let fixture = HostedFixture::with_delivery(&server, CompletionDelivery::EntryProbe(probe.clone())).await?;
    let signed = Arc::new(Notify::new());
    let (release, held) = std::sync::mpsc::sync_channel::<()>(1);
    let signed_callback = signed.clone();
    let state_callback = fixture.base.state.clone();
    let run_id = fixture.resolver.run.run_id.clone();
    let probe_callback = probe.clone();
    *fixture.base.issuer.before_grant_return.lock().map_err(|error| anyhow::anyhow!(error.to_string()))? =
        Some(Box::new(move || {
            signed_callback.notify_one();
            held.recv_timeout(Duration::from_secs(10))
                .map_err(|error| AgentdError::Invalid(format!("original grant barrier: {error}")))?;
            let captured = probe_callback.captured.get().ok_or_else(|| AgentdError::Invalid(
                "Core entry was not captured before requesting its original grant".to_owned()))?;
            if !captured.cancellation.is_cancelled() {
                return Err(AgentdError::Invalid("original Core task was not cancelled before releasing its grant".to_owned()));
            }
            if state_callback.require_native_effect(&run_id)?.phase != RunPhase::Dispatched {
                return Err(AgentdError::Invalid("Agentd cancellation masked the Core final gate".to_owned()));
            }
            Ok(())
        }));

    let turn_id = fixture.start().await?;
    tokio::time::timeout(Duration::from_secs(10), signed.notified()).await
        .context("original writer never requested its signed grant")?;
    let captured = probe.captured.get().context("original admitted Core entry")?.clone();
    assert_eq!((captured.thread_id, captured.turn_id.as_str()),
        (fixture.test.session_configured.thread_id, turn_id.as_str()));
    assert!(!captured.cancellation.is_cancelled());
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if captured.entry.with_current(captured.thread_id, &turn_id, || ()).is_ok() { break; }
            tokio::task::yield_now().await;
        }
    }).await.context("original queue-confirmed Core entry was never current")?;
    let before = fixture.checkpoint().await?;
    assert_eq!(before.1.model_calls, 1);
    assert_eq!(before.1.pending_model.as_ref().map(|request| (&request.operation_id, &request.body)),
        Some((&captured.request.operation_id, &captured.request.body)));
    let original = fixture.base.writer.resolve_operation_request(&captured.request.operation_id,
        fixture.native.model.destination_id()).await?;
    assert_eq!(original.payload_json.as_bytes(), captured.request.body.as_slice());
    assert_eq!(fixture.base.writer.status(&captured.request.operation_id).await?, LocalOutcomeState::Queued);
    let input = fixture.resolver.captured.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?
        .clone().context("original live history")?;
    let session = input.live.open_native_checkpoint(before.0.checkpoint.clone(), NativeCheckpointOpenMode::Recover,
        Arc::new(ReadOriginalOnly)).await?;
    let stored_before = input.live.load_native_checkpoint(&session).await?;
    assert!(matches!(&stored_before, NativeCheckpointLoad::Present(_)));
    assert!(fixture.service.list(captured.thread_id).await?.is_empty());
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 0));

    fixture.test.codex.submit(codex_protocol::protocol::Op::Interrupt).await?;
    // The Core task does not join the independent transport worker. Its own
    // detach and terminalization can finish while this signed grant is held.
    tokio::time::timeout(Duration::from_secs(10), captured.cancellation.cancelled()).await
        .context("original Core interrupt did not cancel its admitted turn")?;
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            if let Err(error) = captured.entry.with_current(captured.thread_id, &turn_id, || ()) {
                let reason = error.to_string();
                if reason.contains("original hosted Core task is no longer attached")
                    || reason.contains("original hosted Core task ended")
                    || reason.contains("original hosted Core task was replaced or terminalized") {
                    return Ok::<_, anyhow::Error>(());
                }
                ensure!(reason.contains("lifecycle is busy") || reason.contains("admission gate is unavailable"),
                    "unexpected Core detach witness: {reason}");
            }
            tokio::task::yield_now().await;
        }
    }).await.context("original Core task never detached before final entry")??;
    fixture.recovery_epoch(&turn_id).await?;
    assert!(captured.cancellation.is_cancelled());
    assert_eq!(fixture.base.state.require_native_effect(&fixture.resolver.run.run_id)?.phase, RunPhase::Dispatched);
    assert_eq!(fixture.base.final_use.capacity()?.used_nonces, 0);
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    release.send(()).context("original signed-grant worker disappeared")?;

    let child = probe.child.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?
        .take().context("original transport worker")?;
    let error = tokio::time::timeout(Duration::from_secs(10), child).await
        .context("original final-entry worker did not finish")???;
    assert!(error.contains("original Core turn rejected native entry:"), "final rejection: {error}");
    assert!(!error.contains("lifecycle is busy") && !error.contains("admission gate is unavailable"),
        "transient lock contention cannot stand in for cancellation: {error}");
    assert_eq!(fixture.base.state.native_run_receipt(&fixture.resolver.run.run_id)?.phase, RunPhase::Indeterminate);
    assert_eq!(fixture.base.writer.status(&captured.request.operation_id).await?, LocalOutcomeState::Indeterminate);
    assert_eq!(fixture.base.writer.resolve_operation_request(&captured.request.operation_id,
        fixture.native.model.destination_id()).await?, original);
    assert_eq!(input.live.load_native_checkpoint(&session).await?, stored_before);
    let after = fixture.checkpoint().await?;
    assert_eq!(crate::native_turn_checkpoint::encode(&after.0, &after.1)?,
        crate::native_turn_checkpoint::encode(&before.0, &before.1)?);
    assert!(fixture.native.host.begin_native_effect(fixture.native.model.destination_id(),
        &captured.request.operation_id).await.is_err(), "the original dispatch must not be re-authorized");
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 0));
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    assert!(matches!(fixture.terminal().await, EventMsg::TurnAborted(_)));
    let history = fixture.history().await?;
    let inputs = history.items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
            TurnItem::UserMessage(input) if input.client_id.as_deref() == Some("client:hosted-queue")))).count();
    let starts = history.items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnStarted(event)) if event.turn_id == turn_id)).count();
    assert_eq!((inputs, starts, fixture.resolver.calls.load(Ordering::SeqCst)), (1, 1, 1));
    let queued = fixture.service.reconcile(captured.thread_id, fixture.test.codex.rollout_path(),
        fixture.input.clone(), fixture.payload_sha256.clone(), QueueReconcileMode::ReconcileOnly).await?;
    assert_eq!(queued.outcome, QueueReconcileOutcome::Persisted { turn_id });
    assert!(fixture.service.list(captured.thread_id).await?.is_empty());
    fixture.shutdown().await
}
