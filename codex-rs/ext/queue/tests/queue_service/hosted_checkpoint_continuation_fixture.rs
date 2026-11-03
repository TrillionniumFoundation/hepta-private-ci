//! Explicitly synthetic execution evidence with real Core, ThreadStore and
//! original QueueStore owners. No fixture authority is installed in production.

use super::*;
use codex_core::hosted_turn::{HostedAdmittedTurn, HostedCheckpointContinuationInput,
    HostedFuture, HostedTurnEntry, HostedTurnExecution, HostedTurnExecutor, HostedTurnInput,
    HostedTurnMode, HostedTurnObservation, HostedTurnOutcome, HostedTurnPlan, HostedTurnRecoveryInput};
use codex_extension_api::ThreadStartInput;
use codex_history::TurnRecoveryRequestBinding;
use codex_protocol::error::{CodexErr, Result as CodexResult};
use codex_thread_store::{LiveThread, NativeCheckpointBinding, NativeCheckpointCurrentness,
    NativeCheckpointExpected, NativeCheckpointLoad, NativeCheckpointOpenMode, NativeCheckpointPermit,
    NativeCheckpointState, NativeHistoryVerification, NativeQueuedInputBinding};
use std::collections::BTreeMap;
use tokio::sync::Notify;

#[derive(Clone, Copy)]
pub(super) enum Case {
    Continue, ChangedPlan, ChangedObservation, BindingDeleted, Cancel, OptOut,
    AfterObservation(ObservationResult),
}

#[derive(Clone, Copy)]
pub(super) enum ObservationResult {
    Pending, Error, Unavailable, Conflict, Completed, Cancelled, Aborted, TokenCancelled,
}

pub(super) const ORIGINAL_OBSERVATION_ERROR: &str = "original pending effect observed; fresh execution is unavailable";
pub(super) const CONTINUATION_CONFLICT: &str = "post-observation original continuation proof conflicts";

pub(super) struct Fixture {
    pub(super) case: Case,
    pub(super) runtime: Arc<StateRuntime>,
    pub(super) queue: Arc<LocalQueueStore>,
    pub(super) prepared: AtomicUsize,
    pub(super) continued: AtomicUsize,
    pub(super) observed: AtomicUsize,
    pub(super) effects: AtomicUsize,
    pub(super) original: OnceLock<TurnRecoveryRequestBinding>,
    pub(super) origin: OnceLock<HostedCheckpointContinuationInput>,
    pub(super) entry: OnceLock<Arc<HostedTurnEntry>>,
    pub(super) entered: Notify,
}

impl Fixture {
    pub(super) fn new(case: Case, runtime: Arc<StateRuntime>) -> Arc<Self> {
        Arc::new(Self { case, queue: Arc::new(LocalQueueStore::new(runtime.clone())), runtime,
            prepared: AtomicUsize::new(0), continued: AtomicUsize::new(0), observed: AtomicUsize::new(0),
            effects: AtomicUsize::new(0), original: OnceLock::new(), origin: OnceLock::new(),
            entry: OnceLock::new(), entered: Notify::new() })
    }

    fn plan(self: &Arc<Self>, original: &TurnRecoveryRequestBinding) -> HostedTurnPlan {
        HostedTurnPlan { request_fingerprint_sha256: original.fingerprint_sha256.clone(),
            correlation: correlation(), execution: Box::new(Execution { fixture: self.clone(), resumed: true }) }
    }
}

pub(super) struct Host(pub(super) Arc<Fixture>);
struct Execution { fixture: Arc<Fixture>, resumed: bool }
pub(super) struct Install {
    pub(super) executor: Arc<dyn HostedTurnExecutor>,
    pub(super) queue: Arc<dyn QueueStore>,
}

impl ThreadLifecycleContributor<codex_core::config::Config> for Install {
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, codex_core::config::Config>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            input.session_store.insert(HostedTurnMode::with_queue_owner(self.executor.clone(), self.queue.clone()));
        })
    }
}

fn rejected(message: &str) -> CodexErr { CodexErr::InvalidRequest(message.to_owned()) }
fn storage(error: ThreadStoreError) -> CodexErr { rejected(&error.to_string()) }
fn correlation() -> BTreeMap<String, String> {
    BTreeMap::from([("fixture-original-run".to_owned(), "checkpoint-continuation".to_owned())])
}
fn checkpoint(thread_id: ThreadId, turn_id: &str) -> NativeCheckpointBinding {
    NativeCheckpointBinding { thread_id, turn_id: turn_id.to_owned(),
        operation_id: "fixture-original-checkpoint".to_owned(), generation: 1, lease_id: "fixture-original-lease".to_owned() }
}
struct FixtureCurrentness;
impl NativeCheckpointCurrentness for FixtureCurrentness {
    fn acquire<'a>(&'a self, _binding: &'a NativeCheckpointBinding) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        Box::pin(async { Ok(NativeCheckpointPermit::hold(())) })
    }
}

async fn verify(live: &LiveThread, observation: &HostedTurnObservation) -> CodexResult<()> {
    let session = live.open_native_checkpoint(checkpoint(observation.thread_id, &observation.turn_id),
        NativeCheckpointOpenMode::Inspect, Arc::new(FixtureCurrentness)).await.map_err(storage)?;
    let NativeCheckpointLoad::Present(record) = live.load_native_checkpoint(&session).await.map_err(storage)? else {
        return Err(rejected("original checkpoint is absent"));
    };
    let expected = serde_json::to_vec(&observation.recovery).map_err(|error| rejected(&error.to_string()))?;
    if record.state.payload != expected { return Err(rejected("original checkpoint changed")); }
    live.verify_native_history(&session, NativeHistoryVerification {
        recovery_item: RolloutItem::TurnRecoveryRequestBinding(observation.recovery.clone()),
        queued_input: Some(NativeQueuedInputBinding { client_id: observation.queue.client_id.clone(),
            payload_sha256: observation.queue.payload_sha256.clone() }),
    }).await.map_err(storage)
}

impl HostedTurnExecutor for Host {
    fn executor_id(&self) -> &str { "fixture-checkpoint-continuation-owner" }
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            input.origin.validate(input.thread_id, &input.turn_id, &input.queue)?;
            input.origin.require_initial()?;
            self.0.prepared.fetch_add(1, Ordering::SeqCst);
            Ok(HostedTurnPlan { request_fingerprint_sha256: input.queue.payload_sha256,
                correlation: correlation(), execution: Box::new(Execution { fixture: self.0.clone(), resumed: false }) })
        })
    }
    fn observe_admission<'a>(&'a self, observation: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        Box::pin(async move {
            verify(&observation.live_thread, &observation).await?;
            Ok(Some(observation.turn_id))
        })
    }
    fn supports_checkpoint_continuation(&self) -> bool { !matches!(self.0.case, Case::OptOut) }
    fn prepare_checkpoint_continuation<'a>(&'a self, mut input: HostedCheckpointContinuationInput) -> HostedFuture<'a, Option<HostedTurnPlan>> {
        Box::pin(async move {
            self.0.continued.fetch_add(1, Ordering::SeqCst);
            input.origin.validate(&input.observation)?;
            if matches!(self.0.case, Case::ChangedObservation) {
                input.observation.queue.queued_item_id.push_str("-substituted");
                input.origin.validate(&input.observation)?;
                return Err(rejected("substituted observation unexpectedly passed"));
            }
            if self.0.original.get() != Some(input.origin.original_recovery())
                || self.0.prepared.load(Ordering::SeqCst) != 1 || self.0.effects.load(Ordering::SeqCst) != 0
            { return Err(rejected("independent fixture no-effect evidence changed")); }
            verify(input.origin.original_live_thread(), &input.observation).await?;
            if let Case::AfterObservation(result) = self.0.case {
                // The same actual checkpoint is initially observation-only.
                // Only the original observer makes the synthetic owner ready.
                if self.0.observed.load(Ordering::SeqCst) == 0 { return Ok(None); }
                match result {
                    ObservationResult::Pending | ObservationResult::Error => {}
                    ObservationResult::Unavailable => return Ok(None),
                    ObservationResult::Conflict => return Err(rejected(CONTINUATION_CONFLICT)),
                    ObservationResult::Completed | ObservationResult::Cancelled
                    | ObservationResult::Aborted | ObservationResult::TokenCancelled => {
                        return Err(rejected("terminal observation reentered continuation"));
                    }
                }
            }
            let mut plan = self.0.plan(input.origin.original_recovery());
            if matches!(self.0.case, Case::ChangedPlan) {
                plan.correlation.insert("substituted".to_owned(), "not-original".to_owned());
            }
            self.0.origin.set(input).map_err(|_| rejected("continuation origin was minted twice"))?;
            Ok(Some(plan))
        })
    }
    fn recover<'a>(&'a self, input: HostedTurnRecoveryInput) -> HostedFuture<'a, HostedTurnOutcome> {
        Box::pin(async move {
            self.0.observed.fetch_add(1, Ordering::SeqCst);
            verify(&input.observation.live_thread, &input.observation).await?;
            match self.0.case {
                Case::AfterObservation(ObservationResult::Error | ObservationResult::Unavailable | ObservationResult::Conflict) => {
                    Err(rejected(ORIGINAL_OBSERVATION_ERROR))
                }
                Case::AfterObservation(ObservationResult::Completed) => Ok(HostedTurnOutcome::Completed {
                    final_answer: Some("original observed result".to_owned()),
                }),
                Case::AfterObservation(ObservationResult::Cancelled) => Ok(HostedTurnOutcome::Cancelled),
                Case::AfterObservation(ObservationResult::Aborted) => Err(CodexErr::TurnAborted),
                Case::AfterObservation(ObservationResult::TokenCancelled) => {
                    input.cancellation.cancel();
                    Ok(HostedTurnOutcome::PendingObservation)
                }
                Case::Continue | Case::ChangedPlan | Case::ChangedObservation | Case::BindingDeleted
                | Case::Cancel | Case::OptOut | Case::AfterObservation(ObservationResult::Pending) => {
                    Ok(HostedTurnOutcome::PendingObservation)
                }
            }
        })
    }
}

impl HostedTurnExecution for Execution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            if !self.resumed {
                self.fixture.original.set(turn.recovery().clone())
                    .map_err(|_| rejected("the original Core turn was prepared twice"))?;
                let binding = checkpoint(turn.thread_id(), turn.turn_id());
                let session = turn.live_thread().open_native_checkpoint(binding.clone(), NativeCheckpointOpenMode::Create,
                    Arc::new(FixtureCurrentness)).await.map_err(storage)?;
                turn.live_thread().commit_native_checkpoint(&session, NativeCheckpointExpected::Absent,
                    NativeCheckpointState { binding,
                        payload: serde_json::to_vec(turn.recovery()).map_err(|error| rejected(&error.to_string()))? }).await.map_err(storage)?;
                turn.confirm_durable().await?;
                // Preserve a technical hold after the first checkpoint and
                // actual queue completion, before this owner admits any effect.
                return Ok(HostedTurnOutcome::PendingObservation);
            }
            if self.fixture.original.get() != Some(turn.recovery()) {
                return Err(rejected("continuation replaced the original recovery binding"));
            }
            if turn.entry().with_current(turn.thread_id(), turn.turn_id(), || ()).is_ok() {
                return Err(rejected("continuation entered before persisted queue confirmation"));
            }
            self.fixture.entry.set(turn.entry().clone()).map_err(|_| rejected("continuation entered twice"))?;
            if matches!(self.fixture.case, Case::Cancel) {
                self.fixture.entered.notify_one();
                return std::future::pending().await;
            }
            if matches!(self.fixture.case, Case::BindingDeleted) {
                // Exercise loss of the SQL evidence between initial observation
                // and revalidation. Normal app-server deletion shuts Core down
                // first; this direct-store test claims no cross-owner lock.
                self.fixture.runtime.thread_queue().seal_thread_queues_for_deletion(&[turn.thread_id()])
                    .await.map_err(|error| rejected(&error.to_string()))?;
            }
            turn.confirm_durable().await?;
            turn.entry().with_current(turn.thread_id(), turn.turn_id(), || {
                self.fixture.effects.fetch_add(1, Ordering::SeqCst);
            })?;
            Ok(HostedTurnOutcome::Completed { final_answer: Some("same original checkpoint result".to_owned()) })
        })
    }
}
