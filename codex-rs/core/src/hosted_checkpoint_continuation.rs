//! Same-task continuation of an original checkpoint after the original queue
//! completed. This capability is distinct from read-only effect recovery.

use std::sync::{Arc, Weak};
use std::sync::atomic::{AtomicBool, Ordering};

use codex_history::TurnRecoveryRequestBinding;
use codex_protocol::error::{CodexErr, Result as CodexResult};
use codex_thread_store::{LiveThread, QueuePersistedBindingObservation, QueueStore, ThreadStoreError};
use tokio_util::sync::CancellationToken;

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;

use super::{HostedAdmittedTurn, HostedQueueBinding, HostedQueueCommitWaiter, HostedTurnEntry,
    HostedTurnExecutor, HostedTurnMode, HostedTurnObservation, HostedTurnOutcome, invalid};

pub struct HostedCheckpointContinuationInput {
    pub observation: HostedTurnObservation,
    pub cancellation: CancellationToken,
    pub origin: HostedCheckpointContinuationOrigin,
}

/// Core alone constructs this after attaching its original recovery task and
/// observing completion through the queue owner installed in this Session.
/// It is not a writer grant and cannot authorize effects. An executor must
/// independently prove that its original checkpoint can continue, then use the
/// admitted turn's final-entry handle for every actual effect.
pub struct HostedCheckpointContinuationOrigin {
    session: Weak<Session>,
    executor: Arc<dyn HostedTurnExecutor>,
    original: TurnRecoveryRequestBinding,
    live_thread: LiveThread,
    queue: HostedQueueBinding,
    completion: Arc<PersistedQueueCompletion>,
    entry: Arc<HostedTurnEntry>,
}

impl HostedCheckpointContinuationOrigin {
    /// Compare public observations with immutable original provenance and the
    /// exact attached task. A copied tuple or a substituted queue is no permit.
    pub fn validate(&self, observation: &HostedTurnObservation) -> CodexResult<()> {
        if observation.thread_id != self.completion.observation.thread_id
            || observation.turn_id != self.original.turn_id
            || observation.recovery != self.original || observation.queue != self.queue
        {
            return Err(invalid("checkpoint continuation changed its original Core provenance"));
        }
        let session = self.session.upgrade()
            .ok_or_else(|| invalid("original checkpoint continuation owner stopped"))?;
        self.completion.require_installed(&session, &self.executor)?;
        self.entry.require_current()
    }

    pub fn original_recovery(&self) -> &TurnRecoveryRequestBinding { &self.original }

    /// Use this original handle for checkpoint/history reads. The public
    /// observation's independently replaceable LiveThread is not an owner proof.
    pub fn original_live_thread(&self) -> &LiveThread { &self.live_thread }
}

pub(crate) enum HostedQueueConfirmation {
    AwaitQueueCommit(HostedQueueCommitWaiter),
    AlreadyPersisted(Arc<PersistedQueueCompletion>),
}

/// Internal evidence is captured from the installed owner; the public SQL DTO
/// never constructs this value. The original queued item id remains in Core's
/// immutable provenance, because completion has cleared it from the SQL row.
pub(crate) struct PersistedQueueCompletion {
    owner: Arc<dyn QueueStore>,
    executor: Arc<dyn HostedTurnExecutor>,
    observation: QueuePersistedBindingObservation,
}

impl PersistedQueueCompletion {
    fn require_installed(&self, session: &Session, executor: &Arc<dyn HostedTurnExecutor>) -> CodexResult<()> {
        let mode = session.services.session_extension_data.get::<HostedTurnMode>()
            .ok_or_else(|| invalid("original hosted checkpoint mode is absent"))?;
        if !Arc::ptr_eq(&mode.executor, executor)
            || !mode.queue_owner.as_ref().is_some_and(|owner| Arc::ptr_eq(owner, &self.owner))
        {
            return Err(invalid("original hosted checkpoint owner changed"));
        }
        Ok(())
    }

    pub(super) async fn confirm(&self, turn: &HostedAdmittedTurn) -> CodexResult<()> {
        self.require_installed(&turn.session, &self.executor)?;
        turn.entry.require_current()?;
        // This read creates no queue row, claim, authorization or completion.
        // Normal hard deletion first shuts this same Core owner down, then
        // seals SQL. A raw cross-manager SQL seal has no Core atomicity claim.
        tokio::select! {
            biased;
            _ = turn.cancellation.cancelled() => return Err(CodexErr::TurnAborted),
            result = self.owner.revalidate_persisted_client_binding(&self.observation) => {
                result.map_err(|error| invalid(&error.to_string()))?;
            }
        }
        self.require_installed(&turn.session, &self.executor)?;
        // Publish confirmation under the same original task/shutdown gates;
        // final effect entry validates them again, without awaiting under locks.
        turn.entry.confirm_queue_completion()
    }
}

pub(crate) async fn try_run(
    session: &Arc<Session>,
    context: &Arc<TurnContext>,
    executor: &Arc<dyn HostedTurnExecutor>,
    observation: &HostedTurnObservation,
    cancellation: &CancellationToken,
) -> CodexResult<Option<HostedTurnOutcome>> {
    if !executor.supports_checkpoint_continuation() { return Ok(None); }
    let mode = session.services.session_extension_data.get::<HostedTurnMode>()
        .ok_or_else(|| invalid("original hosted checkpoint mode is absent"))?;
    if !Arc::ptr_eq(&mode.executor, executor) {
        return Err(invalid("original hosted checkpoint executor changed"));
    }
    let Some(owner) = mode.queue_owner.as_ref() else { return Ok(None); };
    // TurnStarted was appended after the typed successor flush. Make that
    // final Core history durable before the host can retain a writer fence.
    observation.live_thread.flush().await.map_err(|error| invalid(&error.to_string()))?;
    let provenance = observation.provenance()?;
    let persisted = match owner.observe_persisted_client_binding(observation.thread_id,
        observation.queue.client_id.clone(), observation.queue.payload_sha256.clone()).await
    {
        Err(ThreadStoreError::Unsupported { .. }) => return Ok(None),
        Err(error) => return Err(invalid(&error.to_string())),
        Ok(None) => return Err(invalid("original hosted queue completion is absent")),
        Ok(Some(persisted)) => persisted,
    };
    if persisted.thread_id != observation.thread_id || persisted.turn_id != observation.turn_id
        || persisted.client_id != observation.queue.client_id
        || persisted.payload_sha256 != observation.queue.payload_sha256 || persisted.revision < 1
    {
        return Err(invalid("original hosted queue completion conflicts with Core provenance"));
    }
    let completion = Arc::new(PersistedQueueCompletion {
        owner: Arc::clone(owner), executor: Arc::clone(executor), observation: persisted,
    });
    let confirmed = Arc::new(AtomicBool::new(false));
    let entry = HostedTurnEntry::capture(session, context, cancellation.clone(), Arc::clone(&confirmed)).await?;
    let origin = HostedCheckpointContinuationOrigin {
        session: Arc::downgrade(session), executor: Arc::clone(executor),
        original: observation.recovery.clone(), live_thread: observation.live_thread.clone(),
        queue: observation.queue.clone(), completion: Arc::clone(&completion), entry: Arc::clone(&entry),
    };
    origin.validate(observation)?;
    let plan = executor.prepare_checkpoint_continuation(HostedCheckpointContinuationInput {
        observation: HostedTurnObservation {
            live_thread: observation.live_thread.clone(), thread_id: observation.thread_id,
            turn_id: observation.turn_id.clone(), queue: observation.queue.clone(), recovery: observation.recovery.clone(),
        },
        cancellation: cancellation.clone(), origin,
    }).await?;
    completion.require_installed(session, executor)?;
    entry.require_current()?;
    let Some(plan) = plan else { return Ok(None); };
    if plan.request_fingerprint_sha256 != observation.recovery.fingerprint_sha256
        || plan.correlation != provenance.correlation
    {
        return Err(invalid("hosted checkpoint continuation changed its original fingerprint or correlation"));
    }
    // The plan may retain an execution-owner proof. There must be no Core
    // ThreadStore I/O from hook return to execution: the host drops its writer
    // fence before reopening the checkpoint, then confirm_durable rechecks SQL.
    let outcome = plan.execution.run(HostedAdmittedTurn {
        session: Arc::clone(session), thread_id: observation.thread_id, live_thread: observation.live_thread.clone(),
        recovery: observation.recovery.clone(), queue: observation.queue.clone(), cancellation: cancellation.clone(),
        completion: HostedQueueConfirmation::AlreadyPersisted(completion), confirmed: Arc::clone(&confirmed), entry,
    }).await?;
    if matches!(outcome, HostedTurnOutcome::Completed { .. }) && !confirmed.load(Ordering::Acquire) {
        return Err(invalid("hosted checkpoint continuation completed without original queue confirmation"));
    }
    Ok(Some(outcome))
}
