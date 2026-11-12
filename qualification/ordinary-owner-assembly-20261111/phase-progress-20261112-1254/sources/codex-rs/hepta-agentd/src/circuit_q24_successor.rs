//! One supervised, original-Root successor installation. A waiting profile is
//! present but cannot execute tasks. No external provider or completed receipt
//! can fill it; the actual Root publication driver is consumed by its worker.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::sync::oneshot;

use crate::AgentdError;
use crate::AgentdGenerationUpdatePredecessorFilesV1;
use crate::CircuitTaskRuntimeBootstrapV1;
use crate::OriginalCellQ24FeatureTargetV1;
use crate::OriginalCellQ24PublicationErrorV1 as Error;
use crate::OriginalCellQ24RootPublicationDriverV1;
use crate::learning_iteration::OriginalQ24SuccessorContext;

#[path = "circuit_q24_successor_invocation.rs"]
mod invocation;
#[path = "circuit_q24_successor_state.rs"]
mod state;
#[path = "circuit_q24_successor_worker.rs"]
mod worker;
#[path = "circuit_q24_successor_same_actor.rs"]
mod same_actor;
pub(crate) use same_actor::OriginalSameActorSuccessorTaskParts;
pub(crate) use same_actor::prepare_original_same_actor_successor;
pub use crate::circuit_q24_task_profile::successor::OriginalQ24InstalledSuccessorV1;
pub use crate::circuit_q24_task_profile::successor::OriginalQ24SuccessorExecutionInputsV1;
pub use crate::circuit_q24_task_profile::successor::OriginalQ24SuccessorFeedbackV1;
pub(crate) use crate::circuit_q24_task_profile::successor::OriginalQ24SuccessorInvocationV1;
use state::CloseOnDrop;
use state::InstallationWork;
pub(crate) use state::SuccessorSlot;
pub(crate) use worker::PendingSuccessorOwner;

/// The original preparation may already be durable. The cause is retained;
/// this never means "not executed" and never authorizes another publication.
#[derive(Debug, thiserror::Error)]
#[error(
    "original successor CURRENT may already be prepared; completion is uncertain, read the original operation: {cause}"
)]
pub struct OriginalQ24SuccessorPreparedUncertain {
    #[source]
    cause: Box<Error>,
}

pub(crate) fn prepared_uncertain(cause: Error) -> Error {
    Error::Owner(AgentdError::Io(std::io::Error::other(
        OriginalQ24SuccessorPreparedUncertain {
            cause: Box::new(cause),
        },
    )))
}

struct Quote {
    binding: FinalUseBinding,
    intent: Digest32,
}
struct Installation {
    driver: OriginalCellQ24RootPublicationDriverV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
    target: OriginalCellQ24FeatureTargetV1,
    execution: OriginalQ24SuccessorExecutionInputsV1,
    quoted: oneshot::Sender<Result<Quote, Error>>,
    grant: oneshot::Receiver<SignedFinalUseGrant>,
    completed: oneshot::Sender<Result<OriginalQ24InstalledSuccessorV1, Error>>,
    _work: InstallationWork,
}

/// Created only alongside the original closed pending Config. Dropping this
/// value or any outstanding handoff future permanently closes that service.
pub struct OriginalQ24SuccessorHandoffV1 {
    context: Arc<OriginalQ24SuccessorContext>,
    slot: Arc<SuccessorSlot>,
    sender: Option<oneshot::Sender<Installation>>,
    close: CloseOnDrop,
}

/// The actual worker has prepared CURRENT and retains the original journals.
/// Only the existing issuer's exact signed grant can finish this one attempt.
pub struct OriginalQ24PreparedSuccessorV1 {
    quote: Quote,
    grant: Option<oneshot::Sender<SignedFinalUseGrant>>,
    completed: oneshot::Receiver<Result<OriginalQ24InstalledSuccessorV1, Error>>,
    close: CloseOnDrop,
}

pub(crate) fn original_pending_successor_invocation(
    slot: Arc<SuccessorSlot>,
) -> Arc<dyn crate::AgentdCircuitTaskInvocationProviderV1> {
    Arc::new(invocation::PendingSuccessorInvocation { slot })
}

pub(crate) fn compose_original_successor_runtime(
    context: Arc<OriginalQ24SuccessorContext>,
    slot: Arc<SuccessorSlot>,
    capacity: usize,
) -> Result<
    (
        CircuitTaskRuntimeBootstrapV1,
        Arc<dyn crate::AgentdCircuitTaskInvocationProviderV1>,
        OriginalQ24SuccessorHandoffV1,
    ),
    AgentdError,
> {
    if !(1..=64).contains(&capacity) {
        return Err(AgentdError::Invalid("successor queue must be 1..64".into()));
    }
    let (sender, receiver) = oneshot::channel();
    let invocation = original_pending_successor_invocation(Arc::clone(&slot));
    let pending =
        PendingSuccessorOwner::new(Arc::clone(&context), Arc::clone(&slot), receiver, capacity);
    let bootstrap = CircuitTaskRuntimeBootstrapV1::from_original_successor_worker(
        context.identity(),
        Arc::clone(&slot),
        pending,
    );
    let handoff = OriginalQ24SuccessorHandoffV1 {
        context,
        slot: Arc::clone(&slot),
        sender: Some(sender),
        close: CloseOnDrop::new(&slot),
    };
    Ok((bootstrap, invocation, handoff))
}

impl OriginalQ24SuccessorHandoffV1 {
    /// This is the exact already-checkpointed prefix. It is signing/readback
    /// context, never a substitute for the original aggregate or Root lane.
    pub async fn decision_snapshot(&self) -> Result<LearningIterationSnapshotV1, Error> {
        let mut cancelled = CloseOnDrop::new(&self.slot);
        let snapshot = self
            .slot
            .decision(self.context.initial().request.envelope.expiry_unix_seconds)
            .await?;
        self.context
            .scope()
            .validate_snapshot(&snapshot)
            .map_err(|_| Error::Binding("successor decision scope"))?;
        cancelled.disarm();
        Ok(snapshot)
    }

    pub(crate) async fn prepare_from_original_root(
        mut self,
        driver: OriginalCellQ24RootPublicationDriverV1,
        predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        target: OriginalCellQ24FeatureTargetV1,
        execution: OriginalQ24SuccessorExecutionInputsV1,
    ) -> Result<OriginalQ24PreparedSuccessorV1, Error> {
        let work = self
            .slot
            .begin_installation()
            .map_err(|_| Error::Binding("successor slot is not pending"))?;
        let (quoted, quote) = oneshot::channel();
        let (grant, receive_grant) = oneshot::channel();
        let (completed, receive_completed) = oneshot::channel();
        self.sender
            .take()
            .ok_or(Error::CommitUncertain)?
            .send(Installation {
                driver,
                predecessor,
                target,
                execution,
                quoted,
                grant: receive_grant,
                completed,
                _work: work,
            })
            .map_err(|_| Error::CommitUncertain)?;
        let quote = quote
            .await
            .map_err(|_| prepared_uncertain(Error::CommitUncertain))??;
        self.slot
            .require_open()
            .map_err(|_| prepared_uncertain(Error::CommitUncertain))?;
        // The same guard changes hands. Neither a lost reply nor cancellation
        // creates a second sender, a fresh nonce or a replacement task owner.
        Ok(OriginalQ24PreparedSuccessorV1 {
            quote,
            grant: Some(grant),
            completed: receive_completed,
            close: self.close,
        })
    }
}

impl OriginalQ24PreparedSuccessorV1 {
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        &self.quote.binding
    }
    pub fn intent_digest(&self) -> Digest32 {
        self.quote.intent
    }

    pub async fn publish(
        mut self,
        signed: SignedFinalUseGrant,
    ) -> Result<OriginalQ24InstalledSuccessorV1, Error> {
        if signed.grant.binding != self.quote.binding {
            return Err(prepared_uncertain(Error::Binding(
                "exact successor FinalUse binding",
            )));
        }
        self.grant
            .take()
            .ok_or_else(|| prepared_uncertain(Error::CommitUncertain))?
            .send(signed)
            .map_err(|_| prepared_uncertain(Error::CommitUncertain))?;
        let installed = (&mut self.completed)
            .await
            .map_err(|_| prepared_uncertain(Error::CommitUncertain))??;
        self.close
            .slot
            .require_open()
            .map_err(|_| prepared_uncertain(Error::CommitUncertain))?;
        self.close.disarm();
        Ok(installed)
    }
}
