//! Optional execution inside Core's existing turn and persistence lifecycle.
//!
//! The embedding supplies execution, never a replacement thread/queue owner.
//! This API carries no grant and cannot turn an uncertain admission into a retry.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use codex_history::TurnRecoveryRequestBinding;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::user_input::UserInput;
use codex_thread_store::LiveThread;
use codex_thread_store::QueueStore;
use serde::Deserialize;
use serde::Serialize;
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

use crate::session::session::Session;

#[path = "hosted_turn_entry.rs"]
mod entry;
pub use entry::HostedTextDelta;
pub use entry::HostedTurnEntry;

#[path = "hosted_checkpoint_continuation.rs"]
pub(crate) mod checkpoint_continuation;
pub use checkpoint_continuation::HostedCheckpointContinuationInput;
pub use checkpoint_continuation::HostedCheckpointContinuationOrigin;
pub(crate) use checkpoint_continuation::HostedQueueConfirmation;

const PROVENANCE_KEY: &str = "codex.hosted-turn.v1";
const MAX_PROVENANCE_BYTES: usize = 8 * 1024;

pub type HostedFuture<'a, T> = Pin<Box<dyn Future<Output = CodexResult<T>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HostedQueueBinding {
    pub queued_item_id: String,
    pub client_id: String,
    pub payload_sha256: String,
}

/// Original-owner correlation recorded in the existing typed recovery item.
/// These identifiers are observations, not execution capabilities.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HostedTurnProvenance {
    pub executor_id: String,
    pub correlation: BTreeMap<String, String>,
    pub queue: HostedQueueBinding,
}

impl HostedTurnProvenance {
    pub fn from_recovery(binding: &TurnRecoveryRequestBinding) -> CodexResult<Option<Self>> {
        let Some(encoded) = binding
            .replay
            .as_ref()
            .and_then(|replay| replay.start.responses_metadata_extra.get(PROVENANCE_KEY))
        else {
            return Ok(None);
        };
        if encoded.len() > MAX_PROVENANCE_BYTES {
            return Err(invalid("hosted turn provenance exceeds its bound"));
        }
        let provenance: Self = serde_json::from_str(encoded)
            .map_err(|error| invalid(&format!("invalid hosted turn provenance: {error}")))?;
        provenance.validate()?;
        Ok(Some(provenance))
    }

    pub(crate) fn metadata(&self) -> CodexResult<BTreeMap<String, String>> {
        self.validate()?;
        let encoded = serde_json::to_string(self)
            .map_err(|error| invalid(&format!("hosted turn provenance: {error}")))?;
        if encoded.len() > MAX_PROVENANCE_BYTES {
            return Err(invalid("hosted turn provenance exceeds its bound"));
        }
        Ok(BTreeMap::from([(PROVENANCE_KEY.to_string(), encoded)]))
    }

    fn validate(&self) -> CodexResult<()> {
        if self.executor_id.is_empty()
            || self.executor_id.len() > 128
            || self.queue.queued_item_id.is_empty()
            || self.queue.client_id.is_empty()
            || !valid_sha256(&self.queue.payload_sha256)
        {
            return Err(invalid("incomplete hosted turn provenance"));
        }
        Ok(())
    }
}

/// Installed by the original queue owner before a session can prewarm.
/// Such sessions accept only explicit hosted queue admission, not regular sampling.
pub struct HostedTurnMode {
    pub(crate) executor: Arc<dyn HostedTurnExecutor>,
    pub(crate) queue_owner: Option<Arc<dyn QueueStore>>,
}

impl HostedTurnMode {
    /// Compatibility installation supports observation and ordinary admission.
    /// Same-turn checkpoint continuation additionally needs the original queue.
    pub fn new(executor: Arc<dyn HostedTurnExecutor>) -> Self {
        Self {
            executor,
            queue_owner: None,
        }
    }

    pub fn with_queue_owner(
        executor: Arc<dyn HostedTurnExecutor>,
        queue_owner: Arc<dyn QueueStore>,
    ) -> Self {
        Self {
            executor,
            queue_owner: Some(queue_owner),
        }
    }
}

pub struct HostedTurnInput {
    pub live_thread: LiveThread,
    pub thread_id: ThreadId,
    pub turn_id: String,
    pub input: Vec<UserInput>,
    pub queue: HostedQueueBinding,
    pub cancellation: CancellationToken,
    pub origin: HostedPreparationOrigin,
}

/// Proof that Core reserved the exact first admission before invoking host
/// preparation. The public correlation fields alone cannot create this value.
/// It conveys no writer authority and cannot authorize an external effect.
pub struct HostedPreparationOrigin {
    thread_id: ThreadId,
    turn_id: String,
    queue: HostedQueueBinding,
    purpose: HostedPreparationPurpose,
}

enum HostedPreparationPurpose {
    InitialAdmission,
    RetainedTurn(Box<TurnRecoveryRequestBinding>),
}

impl HostedPreparationOrigin {
    pub(crate) fn new(thread_id: ThreadId, turn_id: String, queue: HostedQueueBinding) -> Self {
        Self {
            thread_id,
            turn_id,
            queue,
            purpose: HostedPreparationPurpose::InitialAdmission,
        }
    }

    pub(crate) fn retained(
        thread_id: ThreadId,
        turn_id: String,
        queue: HostedQueueBinding,
        recovery: TurnRecoveryRequestBinding,
    ) -> Self {
        Self {
            thread_id,
            turn_id,
            queue,
            purpose: HostedPreparationPurpose::RetainedTurn(Box::new(recovery)),
        }
    }

    /// A retained turn requires the original executor's independent proof
    /// that no operation was admitted; its history alone cannot restore a
    /// fresh context-attached run.
    pub fn require_initial(&self) -> CodexResult<()> {
        match &self.purpose {
            HostedPreparationPurpose::InitialAdmission => Ok(()),
            HostedPreparationPurpose::RetainedTurn(_) => Err(invalid(
                "retained hosted preparation requires original execution-owner evidence",
            )),
        }
    }

    pub fn require_retained(&self) -> CodexResult<()> {
        self.retained_recovery().map(|_| ())
    }

    /// Immutable original history as read by Core under the retained turn's
    /// reservation. Editing a separate DTO cannot change this provenance.
    pub fn retained_recovery(&self) -> CodexResult<&TurnRecoveryRequestBinding> {
        match &self.purpose {
            HostedPreparationPurpose::RetainedTurn(recovery) => Ok(recovery),
            HostedPreparationPurpose::InitialAdmission => Err(invalid(
                "original preparation repair requires a retained Core turn",
            )),
        }
    }

    pub fn validate(
        &self,
        thread_id: ThreadId,
        turn_id: &str,
        queue: &HostedQueueBinding,
    ) -> CodexResult<()> {
        if self.thread_id != thread_id || self.turn_id != turn_id || &self.queue != queue {
            return Err(invalid(
                "hosted preparation changed its original Core reservation",
            ));
        }
        Ok(())
    }
}

pub struct HostedTurnPlan {
    /// Exact first model-request fingerprint, separate from compiled-context receipts.
    pub request_fingerprint_sha256: String,
    pub correlation: BTreeMap<String, String>,
    pub execution: Box<dyn HostedTurnExecution>,
}

/// A trusted embedding compiles a plan and observes its own durable admission.
/// Preparation must not dispatch effects, mint grants, or consume the queue.
pub trait HostedTurnExecutor: Send + Sync {
    fn executor_id(&self) -> &str;
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan>;
    fn observe_admission<'a>(
        &'a self,
        observation: HostedTurnObservation,
    ) -> HostedFuture<'a, Option<String>>;
    /// Complete preparation of the retained original turn only after the
    /// executor proves through its existing durable owner that no operation
    /// was admitted. Missing host state alone is not such proof. This method
    /// must preserve the original fingerprint/correlation and create no effect.
    fn resume_preparation<'a>(
        &'a self,
        _input: HostedPreparationRecoveryInput,
    ) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async {
            Err(invalid(
                "this hosted executor cannot restore original preparation",
            ))
        })
    }
    /// Opt in to the separate, sealed same-task continuation protocol. Legacy
    /// executors retain their existing read-only recovery without queue reads.
    fn supports_checkpoint_continuation(&self) -> bool {
        false
    }

    /// Prove that the original checkpoint can continue without repeating an
    /// admitted operation. `None` means observation only; proof/currentness
    /// conflicts must return an error and must never fall back to execution.
    /// This hook cannot dispatch effects or consume a grant. Any retained
    /// writer proof must be released before execution touches ThreadStore.
    fn prepare_checkpoint_continuation<'a>(
        &'a self,
        _input: HostedCheckpointContinuationInput,
    ) -> HostedFuture<'a, Option<HostedTurnPlan>> {
        Box::pin(async { Ok(None) })
    }

    /// Observe only the original effects while Core owns a recovery task.
    /// No new input, queue claim, grant or effect may be prepared here.
    fn recover<'a>(
        &'a self,
        _input: HostedTurnRecoveryInput,
    ) -> HostedFuture<'a, HostedTurnOutcome> {
        Box::pin(async {
            Err(invalid(
                "this hosted executor has no original-effect recovery route",
            ))
        })
    }
}

/// Runs inside the original Core task. Confirm durable admission before effects.
pub trait HostedTurnExecution: Send {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome>;
}

/// An admitted input is distinct from its task's terminal effect outcome.
#[derive(Debug, Eq, PartialEq)]
pub enum HostedTurnOutcome {
    Completed { final_answer: Option<String> },
    PendingObservation,
    Cancelled,
}

pub struct HostedTurnObservation {
    pub live_thread: LiveThread,
    pub thread_id: ThreadId,
    pub turn_id: String,
    pub queue: HostedQueueBinding,
    pub recovery: TurnRecoveryRequestBinding,
}

pub struct HostedTurnRecoveryInput {
    pub observation: HostedTurnObservation,
    pub cancellation: CancellationToken,
}

pub struct HostedPreparationRecoveryInput {
    pub input: HostedTurnInput,
    pub recovery: TurnRecoveryRequestBinding,
}

impl HostedTurnObservation {
    pub fn provenance(&self) -> CodexResult<HostedTurnProvenance> {
        let provenance = HostedTurnProvenance::from_recovery(&self.recovery)?
            .ok_or_else(|| invalid("original hosted provenance is absent"))?;
        if self.recovery.turn_id != self.turn_id || provenance.queue != self.queue {
            return Err(invalid(
                "hosted observation belongs to another original input",
            ));
        }
        Ok(provenance)
    }
}

/// Core creates this only after the exact input and original recovery binding are
/// durable. The host must first persist its own checkpoint/history, then await
/// `confirm_durable`; that call waits for the original queue's completion CAS.
pub struct HostedAdmittedTurn {
    pub(crate) session: Arc<Session>,
    pub(crate) thread_id: ThreadId,
    pub(crate) live_thread: LiveThread,
    pub(crate) recovery: TurnRecoveryRequestBinding,
    pub(crate) queue: HostedQueueBinding,
    pub(crate) cancellation: CancellationToken,
    pub(crate) completion: HostedQueueConfirmation,
    pub(crate) confirmed: Arc<AtomicBool>,
    pub(crate) entry: Arc<HostedTurnEntry>,
}

impl HostedAdmittedTurn {
    pub fn live_thread(&self) -> &LiveThread {
        &self.live_thread
    }
    pub fn recovery(&self) -> &TurnRecoveryRequestBinding {
        &self.recovery
    }
    pub fn queue(&self) -> &HostedQueueBinding {
        &self.queue
    }
    pub fn thread_id(&self) -> ThreadId {
        self.thread_id
    }
    pub fn turn_id(&self) -> &str {
        &self.recovery.turn_id
    }
    pub fn cancellation(&self) -> &CancellationToken {
        &self.cancellation
    }
    pub fn entry(&self) -> &Arc<HostedTurnEntry> {
        &self.entry
    }

    pub async fn confirm_durable(&self) -> CodexResult<()> {
        match &self.completion {
            HostedQueueConfirmation::AwaitQueueCommit(completion) => {
                if !self.confirmed.load(Ordering::Acquire) {
                    self.session
                        .pending_user_message_admissions
                        .confirm_hosted_persistence(&self.recovery.turn_id);
                }
                completion.wait(&self.cancellation).await?;
                self.confirmed.store(true, Ordering::Release);
                Ok(())
            }
            HostedQueueConfirmation::AlreadyPersisted(completion) => completion.confirm(self).await,
        }
    }
}

struct QueueCompletionState {
    state: AtomicU8,
    changed: Notify,
}

/// Only a notification from the original queue owner; it confers no authority.
/// The owner retains it through uncertain admission/completion reconciliation.
pub struct HostedQueueCompletion {
    shared: Arc<QueueCompletionState>,
}

pub struct HostedQueueCommitWaiter {
    shared: Arc<QueueCompletionState>,
}

impl HostedQueueCompletion {
    pub fn channel() -> (Self, HostedQueueCommitWaiter) {
        let shared = Arc::new(QueueCompletionState {
            state: AtomicU8::new(0),
            changed: Notify::new(),
        });
        (
            Self {
                shared: Arc::clone(&shared),
            },
            HostedQueueCommitWaiter { shared },
        )
    }

    /// Call only after the existing complete-client-dispatch transaction succeeds.
    pub fn committed(&self) {
        self.shared.state.store(1, Ordering::Release);
        self.shared.changed.notify_waiters();
    }
}

impl Drop for HostedQueueCompletion {
    fn drop(&mut self) {
        let _ = self
            .shared
            .state
            .compare_exchange(0, 2, Ordering::AcqRel, Ordering::Acquire);
        self.shared.changed.notify_waiters();
    }
}

impl HostedQueueCommitWaiter {
    async fn wait(&self, cancellation: &CancellationToken) -> CodexResult<()> {
        loop {
            let changed = self.shared.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            match self.shared.state.load(Ordering::Acquire) {
                1 => return Ok(()),
                2 => return Err(invalid("original hosted queue completion is unknown")),
                _ => {}
            }
            tokio::select! {
                _ = cancellation.cancelled() => return Err(CodexErr::TurnAborted),
                _ = changed => {}
            }
        }
    }
}

pub(crate) struct HostedTurnDispatch {
    pub(crate) executor: Arc<dyn HostedTurnExecutor>,
    pub(crate) queue: HostedQueueBinding,
    pub(crate) completion: HostedQueueCommitWaiter,
    pub(crate) recovery: Option<HostedPreparationRequest>,
}

pub(crate) struct HostedPreparationRequest {
    pub(crate) input: Vec<UserInput>,
    pub(crate) original: TurnRecoveryRequestBinding,
}

pub(crate) fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

pub(crate) fn invalid(message: &str) -> CodexErr {
    CodexErr::InvalidRequest(message.to_string())
}

#[cfg(test)]
#[path = "hosted_turn_tests.rs"]
mod tests;
