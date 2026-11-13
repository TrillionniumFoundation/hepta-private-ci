//! Original Selector custody and explicit predecessor clients for each fixed
//! command purpose. No client is cloned, reopened, signed or discovered here.

use super::*;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCircuitEvaluatedSelectionRemoteSourcesV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

pub(super) enum OriginalPredecessors {
    Legacy(LearningIterationEvidenceClientV1),
    SharedEvaluated(crate::OriginalCircuitPublishedEvidenceReadbackV1),
    SharedLocalEvaluated(crate::OriginalCircuitPublishedEvidenceReadbackV1),
    Evaluated {
        trainer: OriginalCellQ24TrainingCommandClientV1,
        evaluator: OriginalCellEvaluationCommandClientV1,
    },
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitSelectionCommandOwnerV1<W> {
    pub(crate) fn from_original_evaluated_receipt_owner(
        owner: OriginalCircuitSelectionReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        trainer: OriginalCellQ24TrainingCommandClientV1,
        evaluator: OriginalCellEvaluationCommandClientV1,
    ) -> Result<Self, Error> {
        let original = owner
            .original_evaluated_command_context()
            .ok_or(Error::Binding("original evaluated Selector custody"))?;
        let context = OriginalCircuitSelectionCommandContextV1::from_evaluated_context(original)?;
        live.require_original_evaluated_selection(original)
            .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let (_, readback_only) = owner.original_command_profile();
        let initial = context.initial()?;
        let binding = context.binding(now()?)?;
        Ok(Self {
            owner: Mutex::new(owner),
            live,
            predecessors: OriginalPredecessors::Evaluated { trainer, evaluator },
            context,
            initial_head: initial.head_digest,
            binding,
            execution_requested: AtomicBool::new(readback_only),
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    pub(crate) fn from_original_evaluated_shared_receipt_owner(
        owner: OriginalCircuitSelectionReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        shared: crate::OriginalCircuitPublishedEvidenceReadbackV1,
    ) -> Result<Self, Error> {
        let original = owner
            .original_evaluated_command_context()
            .ok_or(Error::Binding("original evaluated Selector custody"))?;
        crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(&shared, original)
            .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let context = OriginalCircuitSelectionCommandContextV1::from_evaluated_context(original)?;
        live.require_original_evaluated_selection(original)
            .map_err(OriginalCircuitSelectionReceiptErrorV1::from)?;
        let (_, readback_only) = owner.original_command_profile();
        let initial = context.initial()?;
        let binding = context.binding(now()?)?;
        Ok(Self {
            owner: Mutex::new(owner),
            live,
            predecessors: OriginalPredecessors::SharedEvaluated(shared),
            context,
            initial_head: initial.head_digest,
            binding,
            execution_requested: AtomicBool::new(readback_only),
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    pub(super) fn observe_original(
        &self,
        owner: &mut OriginalCircuitSelectionReceiptOwnerV1<W>,
        action: wire::Action,
    ) -> Result<
        (LearningIterationReceiptV1, SignedLearningEvidenceV1),
        OriginalCircuitSelectionReceiptErrorV1,
    > {
        match &self.predecessors {
            OriginalPredecessors::Legacy(trainer) => {
                let source = OriginalCircuitSelectionRemoteSourcesV1 {
                    snapshot: &self.context.training,
                    live: &self.live,
                    trainer,
                };
                match action {
                    wire::Action::Execute => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::attest_original_remote_selection(
                            owner, source,
                        ),
                    ),
                    wire::Action::Readback => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::readback_remote(owner, source),
                    ),
                }
            }
            OriginalPredecessors::SharedLocalEvaluated(shared) => {
                let context = self.context.evaluated.as_ref().ok_or(
                    crate::learning_owner_journal::LearningOriginalOwnerErrorV1::Binding(
                        "original local evaluated Selector profile",
                    ),
                )?;
                crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(
                    shared, context,
                )?;
                let (trainer, evaluator) =
                    crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(shared);
                let source =
                    crate::circuit_selection_receipt_owner::OriginalCircuitEvaluatedSelectionLocalSourcesV1 {
                        original: OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
                            snapshot: &self.context.training,
                            live: &self.live,
                            trainer,
                            evaluator,
                        },
                        shared,
                    };
                let original = match action {
                    wire::Action::Execute => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::attest_original_evaluated_local_selection(
                            owner, source,
                        ),
                    ),
                    wire::Action::Readback => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_local_selection(
                            owner, source,
                        ),
                    ),
                }?;
                Ok((original.receipt().clone(), original.attestation().clone()))
            }
            OriginalPredecessors::SharedEvaluated(shared) => {
                let context = self.context.evaluated.as_ref().ok_or(
                    crate::learning_owner_journal::LearningOriginalOwnerErrorV1::Binding(
                        "original evaluated Selector command profile",
                    ),
                )?;
                crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(shared, context)?;
                let (trainer, evaluator) = crate::OriginalCircuitPublishedEvidenceReadbackV1::original_clients(shared);
                let source = OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
                    snapshot: &self.context.training,
                    live: &self.live,
                    trainer,
                    evaluator,
                };
                let original = match action {
                    wire::Action::Execute => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::attest_original_evaluated_remote_selection(owner, source)),
                    wire::Action::Readback => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_remote_selection(owner, source)),
                }?;
                Ok((original.receipt().clone(), original.attestation().clone()))
            }
            OriginalPredecessors::Evaluated { trainer, evaluator } => {
                self.context.evaluated.as_ref().ok_or(
                    crate::learning_owner_journal::LearningOriginalOwnerErrorV1::Binding(
                        "original evaluated Selector command profile",
                    ),
                )?;
                let source = OriginalCircuitEvaluatedSelectionRemoteSourcesV1 {
                    snapshot: &self.context.training,
                    live: &self.live,
                    trainer,
                    evaluator,
                };
                let original = match action {
                    wire::Action::Execute => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::attest_original_evaluated_remote_selection(owner, source)),
                    wire::Action::Readback => self.runtime.block_on(
                        OriginalCircuitSelectionReceiptOwnerV1::readback_evaluated_remote_selection(owner, source)),
                }?;
                Ok((original.receipt().clone(), original.attestation().clone()))
            }
        }
    }
}
