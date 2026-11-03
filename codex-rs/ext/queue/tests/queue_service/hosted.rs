//! Real Core/queue/storage owners with an explicitly synthetic execution host.

use std::collections::BTreeMap;
use std::sync::{Arc, OnceLock};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::Duration;

use anyhow::Context;
use codex_core::hosted_turn::{HostedAdmittedTurn, HostedFuture, HostedTurnExecution, HostedTurnExecutor, HostedTurnInput, HostedTurnMode, HostedTurnObservation, HostedTurnOutcome, HostedTurnPlan, HostedTurnRecoveryInput};
use codex_core::{StartIfIdleSubmission, TurnInput, TurnInputRequest};
use codex_extension_api::{ExtensionFuture, ExtensionRegistryBuilder, NoopExtensionEventSink, ThreadLifecycleContributor, ThreadStartInput};
use codex_history::{RolloutItem, TurnRecoveryRequestBinding};
use codex_protocol::AgentPath;
use codex_protocol::error::CodexErr;
use codex_protocol::protocol::{EventMsg, InterAgentCommunication, Op, ThreadHistoryMode, TurnRecoveryCandidateEvent, TurnRecoveryCandidateState, TurnStartedEvent};
use codex_protocol::turn_input::{NotSubmittedReason, RecoverTurnRequest};
use codex_protocol::user_input::user_input_payload_sha256;
use codex_queue_extension::{QueueReconcileMode, QueueReconcileOutcome, QueuedItemService};
use codex_thread_store::{NativeCheckpointBinding, NativeCheckpointCurrentness, NativeCheckpointExpected, NativeCheckpointLoad, NativeCheckpointOpenMode, NativeCheckpointPermit, NativeCheckpointState, NativeHistoryVerification, NativeQueuedInputBinding, QueueStore, ThreadStoreFuture};
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::{TestCodex, TestCodexBuilder, test_codex};
use core_test_support::wait_for_event_match;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

struct FixtureCurrentness;
impl NativeCheckpointCurrentness for FixtureCurrentness {
    fn acquire<'a>(&'a self, _binding: &'a NativeCheckpointBinding) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        // Qualification-only fixture, never a production authority.
        Box::pin(async { Ok(NativeCheckpointPermit::hold(())) })
    }
}

#[derive(Default)]
struct FixtureState {
    entered: Notify,
    allow_checkpoint: Notify,
    prepared: AtomicUsize,
    effects: AtomicUsize,
    observed: AtomicUsize,
    recovered: AtomicUsize,
    pending: AtomicBool,
    fail_recovery_once: AtomicBool,
    queue: OnceLock<Arc<dyn QueueStore>>,
    original_recovery: OnceLock<TurnRecoveryRequestBinding>,
}

struct FixtureHost(Arc<FixtureState>);
struct FixtureExecution(Arc<FixtureState>);
struct InstallHostedMode(Arc<dyn HostedTurnExecutor>);

impl ThreadLifecycleContributor<codex_core::config::Config> for InstallHostedMode {
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, codex_core::config::Config>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move { input.session_store.insert(HostedTurnMode::new(Arc::clone(&self.0))); })
    }
}

fn checkpoint_binding(thread_id: codex_protocol::ThreadId, turn_id: &str) -> NativeCheckpointBinding {
    NativeCheckpointBinding { thread_id, turn_id: turn_id.to_string(), operation_id: "fixture-original-run".to_string(), generation: 7, lease_id: "fixture-original-lease".to_string() }
}

fn storage_error(error: codex_thread_store::ThreadStoreError) -> CodexErr { CodexErr::Fatal(error.to_string()) }

impl HostedTurnExecutor for FixtureHost {
    fn executor_id(&self) -> &str { "fixture-original-host" }

    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            self.0.prepared.fetch_add(1, Ordering::SeqCst);
            Ok(HostedTurnPlan {
                request_fingerprint_sha256: input.queue.payload_sha256,
                correlation: BTreeMap::from([("run".to_string(), "fixture-original-run".to_string())]),
                execution: Box::new(FixtureExecution(Arc::clone(&self.0))),
            })
        })
    }

    fn observe_admission<'a>(&'a self, input: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        Box::pin(async move {
            self.0.observed.fetch_add(1, Ordering::SeqCst);
            input.provenance()?;
            let session = input.live_thread.open_native_checkpoint(checkpoint_binding(input.thread_id, &input.turn_id), NativeCheckpointOpenMode::Recover, Arc::new(FixtureCurrentness)).await.map_err(storage_error)?;
            let NativeCheckpointLoad::Present(record) = input.live_thread.load_native_checkpoint(&session).await.map_err(storage_error)? else { return Ok(None); };
            let expected = serde_json::to_vec(&input.recovery).map_err(|error| CodexErr::Fatal(error.to_string()))?;
            if record.state.payload != expected { return Err(CodexErr::Fatal("fixture original recovery changed".to_string())); }
            input.live_thread.verify_native_history(&session, NativeHistoryVerification {
                recovery_item: RolloutItem::TurnRecoveryRequestBinding(input.recovery),
                queued_input: Some(NativeQueuedInputBinding { client_id: input.queue.client_id, payload_sha256: input.queue.payload_sha256 }),
            }).await.map_err(storage_error)?;
            Ok(Some(input.turn_id))
        })
    }

    fn recover<'a>(&'a self, input: HostedTurnRecoveryInput) -> HostedFuture<'a, HostedTurnOutcome> {
        Box::pin(async move {
            self.0.recovered.fetch_add(1, Ordering::SeqCst);
            let turn_id = input.observation.turn_id.clone();
            if self.observe_admission(input.observation).await? != Some(turn_id) { return Ok(HostedTurnOutcome::PendingObservation); }
            if self.0.fail_recovery_once.swap(false, Ordering::SeqCst) {
                return Err(CodexErr::Fatal("fixture transient original observer failure".to_string()));
            }
            Ok(HostedTurnOutcome::Completed { final_answer: Some("original observed result".to_string()) })
        })
    }
}

impl HostedTurnExecution for FixtureExecution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            self.0.entered.notify_one();
            self.0.allow_checkpoint.notified().await;
            self.0.original_recovery.set(turn.recovery().clone()).map_err(|_| CodexErr::Fatal("fixture original recovery was prepared twice".to_string()))?;
            let binding = checkpoint_binding(turn.thread_id(), turn.turn_id());
            let session = turn.live_thread().open_native_checkpoint(binding.clone(), NativeCheckpointOpenMode::Create, Arc::new(FixtureCurrentness)).await.map_err(storage_error)?;
            turn.live_thread().commit_native_checkpoint(&session, NativeCheckpointExpected::Absent, NativeCheckpointState {
                binding, payload: serde_json::to_vec(turn.recovery()).map_err(|error| CodexErr::Fatal(error.to_string()))?,
            }).await.map_err(storage_error)?;
            turn.live_thread().verify_native_history(&session, NativeHistoryVerification {
                recovery_item: RolloutItem::TurnRecoveryRequestBinding(turn.recovery().clone()),
                queued_input: Some(NativeQueuedInputBinding { client_id: turn.queue().client_id.clone(), payload_sha256: turn.queue().payload_sha256.clone() }),
            }).await.map_err(storage_error)?;
            turn.confirm_durable().await?;
            let queue = self.0.queue.get().ok_or_else(|| CodexErr::Fatal("original queue is absent".to_string()))?;
            if !queue.list_page(turn.thread_id(), 0, 10).await.map_err(storage_error)?.is_empty() {
                return Err(CodexErr::Fatal("effect released before original queue completion".to_string()));
            }
            self.0.effects.fetch_add(1, Ordering::SeqCst);
            Ok(if self.0.pending.load(Ordering::SeqCst) { HostedTurnOutcome::PendingObservation } else { HostedTurnOutcome::Completed { final_answer: Some("hosted result".to_string()) } })
        })
    }
}

fn fixture_builder(state: &Arc<FixtureState>) -> (TestCodexBuilder, Arc<dyn HostedTurnExecutor>) {
    let executor: Arc<dyn HostedTurnExecutor> = Arc::new(FixtureHost(Arc::clone(state)));
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(Arc::new(InstallHostedMode(Arc::clone(&executor))));
    let builder = test_codex().with_extensions(Arc::new(extensions.build()))
        .with_history_mode(ThreadHistoryMode::Paginated).with_config(|config| {
            config.include_environment_context = false;
            let _ = config.features.enable(codex_features::Feature::HeptaTurnRecovery);
        });
    (builder, executor)
}

fn install_queue(test: &TestCodex, state: &Arc<FixtureState>, executor: Arc<dyn HostedTurnExecutor>) -> anyhow::Result<Arc<QueuedItemService>> {
    let queue = super::loaded_thread_queue(test)?;
    assert!(state.queue.set(Arc::clone(&queue)).is_ok());
    Ok(Arc::new(QueuedItemService::new(queue, Arc::downgrade(&test.thread_manager), Arc::new(NoopExtensionEventSink))
        .with_hosted_turn_executor(Some(executor))))
}

async fn queue_input(test: &TestCodex, service: &QueuedItemService) -> anyhow::Result<(String, TurnInput, String)> {
    let input = super::structured_user_input("one original hosted message");
    let TurnInput::UserInput { content, .. } = &input else { unreachable!() };
    let digest = user_input_payload_sha256(content)?;
    let admitted = service.reconcile(test.session_configured.thread_id, test.codex.rollout_path(), input.clone(), digest.clone(), QueueReconcileMode::AllowIfAbsent).await?;
    let QueueReconcileOutcome::Queued { item, created: true } = admitted.outcome else {
        anyhow::bail!("the original input was not queued exactly once");
    };
    Ok((item.id, input, digest))
}

async fn idle_recovery_epoch(test: &TestCodex, turn_id: &str) -> anyhow::Result<u64> {
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Some(epoch) = test.codex.recovery_epoch_if_idle(turn_id).await { return epoch; }
            tokio::task::yield_now().await;
        }
    }).await.context("original Core turn did not become recoverable")
}

#[tokio::test]
async fn hosted_effect_waits_for_original_checkpoint_and_queue_completion() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let state = Arc::new(FixtureState::default());
    let (mut builder, executor) = fixture_builder(&state);
    let test = builder.build_with_auto_env(&server).await?;
    let service = install_queue(&test, &state, executor)?;
    let (item_id, input, digest) = queue_input(&test, &service).await?;
    let start = tokio::spawn({
        let service = Arc::clone(&service);
        let thread = Arc::clone(&test.codex);
        async move { service.start(&thread, Some(item_id), /*trace*/ None).await }
    });
    tokio::time::timeout(Duration::from_secs(10), state.entered.notified()).await?;
    assert!(!start.is_finished());
    assert_eq!(state.effects.load(Ordering::SeqCst), 0);
    assert_eq!(service.list(test.session_configured.thread_id).await?.len(), 1);
    assert!(test.codex.start_turn_if_idle(TurnInputRequest::new(super::user_input("bypass"))).await.is_err());

    state.allow_checkpoint.notify_one();
    let StartIfIdleSubmission::Started { turn_id } = start.await?? else {
        anyhow::bail!("hosted Core reservation was not started");
    };
    let completed = wait_for_event_match(&test.codex, |event| match event {
        EventMsg::TurnComplete(event) => Some(event.turn_id.clone()),
        _ => None,
    }).await;
    assert_eq!(completed, turn_id);
    assert_eq!((state.prepared.load(Ordering::SeqCst), state.effects.load(Ordering::SeqCst)), (1, 1));
    assert!(service.list(test.session_configured.thread_id).await?.is_empty());
    assert_eq!(service.reconcile(test.session_configured.thread_id, test.codex.rollout_path(), input, digest, QueueReconcileMode::ReconcileOnly).await?.outcome,
        QueueReconcileOutcome::Persisted { turn_id });
    assert!(server.received_requests().await.context("captured provider requests")?.iter().all(|request| !request.url.path().ends_with("/responses")));
    Ok(())
}

#[tokio::test]
async fn hosted_observer_error_keeps_same_original_turn_recoverable() -> anyhow::Result<()> {
    let server = start_mock_server().await;
    let state = Arc::new(FixtureState::default());
    state.pending.store(true, Ordering::SeqCst);
    state.fail_recovery_once.store(true, Ordering::SeqCst);
    state.allow_checkpoint.notify_one();
    let (mut builder, executor) = fixture_builder(&state);
    let test = builder.build_with_auto_env(&server).await?;
    let service = install_queue(&test, &state, executor)?;
    let (item_id, _, _) = queue_input(&test, &service).await?;
    let StartIfIdleSubmission::Started { turn_id } = service.start(&test.codex, Some(item_id), /*trace*/ None).await? else {
        anyhow::bail!("hosted Core reservation was not started");
    };
    unresolved_tail::held(&test, &turn_id).await?;

    // Automatic mailbox wake and explicit compaction cannot replace this
    // unresolved hosted task with Core sampling. Compact's error also acts as
    // a submission-loop barrier after the trigger message.
    let original_epoch = idle_recovery_epoch(&test, &turn_id).await?;
    test.codex.submit(Op::InterAgentCommunication {
        communication: InterAgentCommunication::new(
            AgentPath::try_from("/root/worker").map_err(anyhow::Error::msg)?, AgentPath::root(), Vec::new(),
            "observe pending original work".to_string(), /*trigger_turn*/ true,
        ),
    }).await?;
    test.codex.submit(Op::Compact).await?;
    wait_for_event_match(&test.codex, |event| match event {
        EventMsg::Error(event) if event.message.contains("unsupported by the selected hosted executor") => Some(()),
        _ => None,
    }).await;
    // The original mailbox owner invalidates an idle epoch before accepting
    // new mail, even though hosted mode leaves that mail pending. This changes
    // the reservation witness, not the original native operation or its tail.
    let current_epoch = idle_recovery_epoch(&test, &turn_id).await?;
    assert!(current_epoch > original_epoch);
    assert_eq!(test.codex.recover_turn_if_idle(RecoverTurnRequest {
        turn_id: turn_id.clone(), expected_epoch: original_epoch, thread_settings: Default::default(), trace: None,
    }).await?, StartIfIdleSubmission::NotSubmitted { reason: NotSubmittedReason::RecoveryStateChanged });
    assert_eq!((state.prepared.load(Ordering::SeqCst), state.effects.load(Ordering::SeqCst), state.recovered.load(Ordering::SeqCst)), (1, 1, 0));

    for expected_terminal in [false, true] {
        let epoch = idle_recovery_epoch(&test, &turn_id).await?;
        assert_eq!(test.codex.recover_turn_if_idle(RecoverTurnRequest {
            turn_id: turn_id.clone(), expected_epoch: epoch, thread_settings: Default::default(), trace: None,
        }).await?, StartIfIdleSubmission::Started { turn_id: turn_id.clone() });
        if expected_terminal {
            let terminal = wait_for_event_match(&test.codex, |event| match event {
                EventMsg::TurnComplete(event) => Some(Some(event.turn_id.clone())),
                EventMsg::TurnAborted(_) | EventMsg::Error(_) => Some(None),
                _ => None,
            }).await;
            assert_eq!(terminal, Some(turn_id.clone()));
        } else {
            unresolved_tail::held(&test, &turn_id).await?;
        }
    }
    assert_eq!((state.prepared.load(Ordering::SeqCst), state.effects.load(Ordering::SeqCst), state.recovered.load(Ordering::SeqCst)), (1, 1, 2));
    assert!(service.list(test.session_configured.thread_id).await?.is_empty());
    assert!(server.received_requests().await.context("captured provider requests")?.iter().all(|request| !request.url.path().ends_with("/responses")));
    Ok(())
}

#[tokio::test]
async fn malformed_hosted_recovery_handoffs_remain_held() -> anyhow::Result<()> {
    #[derive(Clone, Copy, Debug)]
    enum MalformedHistory { OrphanUnready, DuplicateUnready, MissingSuccessorStart, BareRepeatedStart }
    let server = start_mock_server().await;
    for case in [MalformedHistory::OrphanUnready, MalformedHistory::DuplicateUnready, MalformedHistory::MissingSuccessorStart, MalformedHistory::BareRepeatedStart] {
        let state = Arc::new(FixtureState::default());
        state.pending.store(true, Ordering::SeqCst);
        state.allow_checkpoint.notify_one();
        let (mut builder, executor) = fixture_builder(&state);
        let test = builder.build_with_auto_env(&server).await?;
        let service = install_queue(&test, &state, executor)?;
        let (item_id, _, _) = queue_input(&test, &service).await?;
        let StartIfIdleSubmission::Started { turn_id } = service.start(&test.codex, Some(item_id), /*trace*/ None).await? else { anyhow::bail!("expected original hosted start"); };
        unresolved_tail::held(&test, &turn_id).await?;
        idle_recovery_epoch(&test, &turn_id).await?;
        let original = state.original_recovery.get().context("original typed anchor")?.clone();
        let next = original.generation + 1;
        let unready = RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(TurnRecoveryCandidateEvent {
            turn_id: turn_id.clone(), generation: next, state: TurnRecoveryCandidateState::Unready,
        }));
        let malformed = match case {
            MalformedHistory::OrphanUnready => vec![unready],
            MalformedHistory::DuplicateUnready => vec![unready.clone(), unready],
            MalformedHistory::MissingSuccessorStart => {
                let mut successor = original;
                successor.generation = next;
                successor.replay_applied_from_generation = Some(next - 1);
                vec![unready, RolloutItem::TurnRecoveryRequestBinding(successor)]
            }
            MalformedHistory::BareRepeatedStart => vec![RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent {
                turn_id: turn_id.clone(), trace_id: None, started_at: None, model_context_window: None, collaboration_mode_kind: Default::default(),
            }))],
        };
        test.codex.append_rollout_items(&malformed).await?;
        assert_eq!(test.codex.recovery_epoch_if_idle(&turn_id).await, None, "{case:?}");
        assert_eq!((state.prepared.load(Ordering::SeqCst), state.effects.load(Ordering::SeqCst), state.recovered.load(Ordering::SeqCst)), (1, 1, 0));
    }
    assert!(server.received_requests().await.context("captured provider requests")?.iter().all(|request| !request.url.path().ends_with("/responses")));
    Ok(())
}

#[path = "hosted_unresolved_tail.rs"]
mod unresolved_tail;
