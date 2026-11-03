//! Real Core/QueueStore/ThreadStore runtime close and reopen before the first
//! host checkpoint. The explicitly synthetic execution owner remains alive
//! outside both runtimes and retains its original preparation/no-effect fact.
//! This is not a native production authority or an OS-process restart test.

use pretty_assertions::assert_eq;

use super::*;
use std::collections::BTreeMap;

use codex_core::hosted_turn::{HostedAdmittedTurn, HostedFuture, HostedPreparationRecoveryInput,
    HostedQueueBinding, HostedTurnExecution, HostedTurnExecutor, HostedTurnInput, HostedTurnMode,
    HostedTurnObservation, HostedTurnOutcome, HostedTurnPlan};
use codex_extension_api::ThreadStartInput;
use codex_history::TurnRecoveryRequestBinding;
use codex_protocol::error::{CodexErr, Result as CodexResult};
use codex_protocol::turn_input::SuspendTurnOutcome;
use codex_thread_store::{NativeCheckpointBinding, NativeCheckpointCurrentness, NativeCheckpointExpected,
    NativeCheckpointLoad, NativeCheckpointOpenMode, NativeCheckpointPermit, NativeCheckpointState,
    NativeHistoryVerification, NativeQueuedInputBinding};
use core_test_support::test_codex::TestCodexBuilder;
use tokio::sync::Notify;

const EXECUTOR: &str = "fixture-retained-preparation-owner";

#[derive(Clone, Copy)]
enum ResumeMode { Original, NoProof, ChangedFingerprint }

struct OriginalPreparation {
    thread_id: ThreadId,
    turn_id: String,
    queue: HostedQueueBinding,
    input: Vec<UserInput>,
    fingerprint: String,
    correlation: BTreeMap<String, String>,
}

#[derive(Default)]
struct ExecutionOwner {
    prepared: AtomicUsize,
    resumed: AtomicUsize,
    effects: AtomicUsize,
    preparation: OnceLock<OriginalPreparation>,
    recovery: OnceLock<TurnRecoveryRequestBinding>,
}

struct RuntimeFixture {
    owner: Arc<ExecutionOwner>,
    mode: ResumeMode,
    entered: Notify,
    checkpointed: Notify,
    allow_confirmation: Notify,
    queue: OnceLock<Arc<dyn QueueStore>>,
}

struct ResumingHost(Arc<RuntimeFixture>);
struct NoProofHost(Arc<RuntimeFixture>);
struct Execution { fixture: Arc<RuntimeFixture>, resumed: bool }
struct InstallMode(Arc<dyn HostedTurnExecutor>);
struct FixtureCurrentness;

impl NativeCheckpointCurrentness for FixtureCurrentness {
    fn acquire<'a>(&'a self, _binding: &'a NativeCheckpointBinding) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        // Explicit synthetic execution-owner fixture; never product authority.
        Box::pin(async { Ok(NativeCheckpointPermit::hold(())) })
    }
}

impl ThreadLifecycleContributor<codex_core::config::Config> for InstallMode {
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, codex_core::config::Config>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move { input.session_store.insert(HostedTurnMode::new(self.0.clone())); })
    }
    fn on_thread_resume<'a>(&'a self, input: ThreadResumeInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move { input.session_store.insert(HostedTurnMode::new(self.0.clone())); })
    }
}

fn storage_error(error: ThreadStoreError) -> CodexErr { CodexErr::Fatal(error.to_string()) }
fn rejected(message: &str) -> CodexErr { CodexErr::Fatal(message.to_owned()) }

fn checkpoint(thread: ThreadId, turn: &str) -> NativeCheckpointBinding {
    NativeCheckpointBinding { thread_id: thread, turn_id: turn.to_owned(),
        operation_id: "fixture-retained-original-run".to_owned(), generation: 7,
        lease_id: "fixture-retained-original-lease".to_owned() }
}

impl RuntimeFixture {
    fn plan(self: &Arc<Self>, fingerprint: String, correlation: BTreeMap<String, String>, resumed: bool) -> HostedTurnPlan {
        HostedTurnPlan { request_fingerprint_sha256: fingerprint, correlation,
            execution: Box::new(Execution { fixture: self.clone(), resumed }) }
    }

    async fn prepare(self: &Arc<Self>, input: HostedTurnInput) -> CodexResult<HostedTurnPlan> {
        input.origin.validate(input.thread_id, &input.turn_id, &input.queue)?;
        input.origin.require_initial()?;
        self.owner.prepared.fetch_add(1, Ordering::SeqCst);
        let fingerprint = input.queue.payload_sha256.clone();
        let correlation = BTreeMap::from([("run".to_owned(), "fixture-retained-original-run".to_owned())]);
        self.owner.preparation.set(OriginalPreparation { thread_id: input.thread_id, turn_id: input.turn_id,
            queue: input.queue, input: input.input, fingerprint: fingerprint.clone(), correlation: correlation.clone() })
            .map_err(|_| rejected("original execution owner was prepared twice"))?;
        Ok(self.plan(fingerprint, correlation, false))
    }

    async fn observe(&self, input: HostedTurnObservation) -> CodexResult<Option<String>> {
        let provenance = input.provenance()?;
        if provenance.executor_id != EXECUTOR { return Err(rejected("another original executor")); }
        let session = input.live_thread.open_native_checkpoint(checkpoint(input.thread_id, &input.turn_id),
            NativeCheckpointOpenMode::Inspect, Arc::new(FixtureCurrentness)).await.map_err(storage_error)?;
        let NativeCheckpointLoad::Present(record) = input.live_thread.load_native_checkpoint(&session)
            .await.map_err(storage_error)? else { return Ok(None); };
        let expected = serde_json::to_vec(&input.recovery).map_err(|error| rejected(&error.to_string()))?;
        if record.state.payload != expected { return Err(rejected("original host checkpoint changed")); }
        input.live_thread.verify_native_history(&session, NativeHistoryVerification {
            recovery_item: RolloutItem::TurnRecoveryRequestBinding(input.recovery),
            queued_input: Some(NativeQueuedInputBinding { client_id: input.queue.client_id, payload_sha256: input.queue.payload_sha256 }),
        }).await.map_err(storage_error)?;
        Ok(Some(input.turn_id))
    }
}

impl HostedTurnExecutor for ResumingHost {
    fn executor_id(&self) -> &str { EXECUTOR }
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move { self.0.prepare(input).await })
    }
    fn observe_admission<'a>(&'a self, input: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        Box::pin(async move { self.0.observe(input).await })
    }
    fn resume_preparation<'a>(&'a self, request: HostedPreparationRecoveryInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            let input = request.input;
            input.origin.validate(input.thread_id, &input.turn_id, &input.queue)?;
            input.origin.require_retained()?;
            self.0.owner.resumed.fetch_add(1, Ordering::SeqCst);
            let original = self.0.owner.preparation.get().ok_or_else(|| rejected("independent preparation proof unavailable"))?;
            // The retained execution owner, not missing host storage, supplies
            // the no-effect evidence in this synthetic Core contract fixture.
            if self.0.owner.prepared.load(Ordering::SeqCst) != 1 || self.0.owner.effects.load(Ordering::SeqCst) != 0
                || self.0.owner.recovery.get() != Some(&request.recovery)
                || input.thread_id != original.thread_id || input.turn_id != original.turn_id
                || input.queue != original.queue || input.input != original.input
                || request.recovery.fingerprint_sha256 != original.fingerprint
            {
                return Err(rejected("independent original preparation or no-effect proof changed"));
            }
            let mut fingerprint = original.fingerprint.clone();
            if matches!(self.0.mode, ResumeMode::ChangedFingerprint) {
                fingerprint = if fingerprint == "f".repeat(64) { "e".repeat(64) } else { "f".repeat(64) };
            }
            Ok(self.0.plan(fingerprint, original.correlation.clone(), true))
        })
    }
}

impl HostedTurnExecutor for NoProofHost {
    fn executor_id(&self) -> &str { EXECUTOR }
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move { self.0.prepare(input).await })
    }
    fn observe_admission<'a>(&'a self, input: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        Box::pin(async move { self.0.observe(input).await })
    }
    // Deliberately retain the default resume_preparation rejection.
}

impl HostedTurnExecution for Execution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            if !self.resumed {
                self.fixture.owner.recovery.set(turn.recovery().clone())
                    .map_err(|_| rejected("initial Core preparation was admitted twice"))?;
                self.fixture.entered.notify_one();
                // Stop after Core's exact input/recovery fsync, before any
                // host checkpoint. Original Core suspension aborts this task.
                return std::future::pending().await;
            }
            if self.fixture.owner.recovery.get() != Some(turn.recovery()) {
                return Err(rejected("resumed execution changed the original turn recovery"));
            }
            let binding = checkpoint(turn.thread_id(), turn.turn_id());
            let session = turn.live_thread().open_native_checkpoint(binding.clone(), NativeCheckpointOpenMode::Create,
                Arc::new(FixtureCurrentness)).await.map_err(storage_error)?;
            turn.live_thread().commit_native_checkpoint(&session, NativeCheckpointExpected::Absent, NativeCheckpointState {
                binding, payload: serde_json::to_vec(turn.recovery()).map_err(|error| rejected(&error.to_string()))?,
            }).await.map_err(storage_error)?;
            turn.live_thread().flush().await.map_err(storage_error)?;
            turn.live_thread().verify_native_history(&session, NativeHistoryVerification {
                recovery_item: RolloutItem::TurnRecoveryRequestBinding(turn.recovery().clone()),
                queued_input: Some(NativeQueuedInputBinding { client_id: turn.queue().client_id.clone(),
                    payload_sha256: turn.queue().payload_sha256.clone() }),
            }).await.map_err(storage_error)?;
            self.fixture.checkpointed.notify_one();
            self.fixture.allow_confirmation.notified().await;
            turn.confirm_durable().await?;
            let queue = self.fixture.queue.get().ok_or_else(|| rejected("original queue is absent"))?;
            if !queue.list_page(turn.thread_id(), 0, 10)
                .await.map_err(storage_error)?.is_empty() {
                return Err(rejected("effect released before the same original queue completed"));
            }
            self.fixture.owner.effects.fetch_add(1, Ordering::SeqCst);
            Ok(HostedTurnOutcome::Completed { final_answer: Some("same original prepared result".to_owned()) })
        })
    }
}

fn builder(owner: Arc<ExecutionOwner>, mode: ResumeMode) -> (TestCodexBuilder, Arc<RuntimeFixture>, Arc<dyn HostedTurnExecutor>) {
    let fixture = Arc::new(RuntimeFixture { owner, mode, entered: Notify::new(), checkpointed: Notify::new(),
        allow_confirmation: Notify::new(), queue: OnceLock::new() });
    let executor: Arc<dyn HostedTurnExecutor> = if matches!(mode, ResumeMode::NoProof) {
        Arc::new(NoProofHost(fixture.clone()))
    } else { Arc::new(ResumingHost(fixture.clone())) };
    let mut extensions = ExtensionRegistryBuilder::new();
    extensions.thread_lifecycle_contributor(Arc::new(InstallMode(executor.clone())));
    let builder = test_codex().with_extensions(Arc::new(extensions.build()))
        .with_history_mode(ThreadHistoryMode::Paginated).with_config(|config| {
            config.include_environment_context = false;
            let _ = config.features.enable(codex_features::Feature::HeptaTurnRecovery);
        });
    (builder, fixture, executor)
}

fn install_queue(test: &TestCodex, fixture: &RuntimeFixture, executor: Arc<dyn HostedTurnExecutor>, short_lease: bool)
    -> anyhow::Result<(Arc<QueuedItemService>, Arc<FailDeleteOnceQueueStore>)> {
    let mut queue = FailDeleteOnceQueueStore::with_short_dispatch_lease(LocalQueueStore::new(
        test.codex.state_db().context("original Core SQLite database")?));
    queue.short_dispatch_lease = short_lease;
    let queue = Arc::new(queue);
    assert!(fixture.queue.set(queue.clone()).is_ok());
    let service = Arc::new(QueuedItemService::new(queue.clone(), Arc::downgrade(&test.thread_manager),
        Arc::new(NoopExtensionEventSink)).with_hosted_turn_executor(Some(executor)));
    Ok((service, queue))
}

async fn history(test: &TestCodex) -> anyhow::Result<Vec<RolloutItem>> {
    let mut lines = open_rollout_line_reader(&test.codex.rollout_path().context("original rollout")?).await?;
    let mut items = Vec::new();
    while let Some(line) = lines.next_line().await? {
        items.push(serde_json::from_str::<RolloutLine>(&line)?.item);
    }
    Ok(items)
}

fn assert_original_history(items: &[RolloutItem], turn: &str, client: &str, terminal: Option<bool>) {
    assert_original_history_with_input_count(items, turn, client, terminal, 1);
}

fn assert_original_history_with_input_count(items: &[RolloutItem], turn: &str, client: &str, terminal: Option<bool>, expected_inputs: usize) {
    let inputs = items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if event.turn_id == turn
            && matches!(&event.item, TurnItem::UserMessage(message) if message.client_id.as_deref() == Some(client)))).count();
    assert_eq!(inputs, expected_inputs, "the exact original typed client input count changed");
    let turn_ids = items.iter().filter_map(|item| match item {
        RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => Some(event.turn_id.as_str()), _ => None,
    }).collect::<HashSet<_>>();
    assert_eq!(turn_ids, HashSet::from([turn]), "resume must keep one logical turn identity");
    let aborted = items.iter().filter(|item| matches!(item, RolloutItem::EventMsg(EventMsg::TurnAborted(_)))).count();
    let completed = items.iter().filter(|item| matches!(item, RolloutItem::EventMsg(EventMsg::TurnComplete(_)))).count();
    assert_eq!((aborted, completed), match terminal { None => (0, 0), Some(true) => (0, 1), Some(false) => (1, 0) });
}

#[path = "hosted_preparation_store_pause.rs"]
mod store_pause;

#[path = "hosted_preparation_resume_tests.rs"]
mod tests;
