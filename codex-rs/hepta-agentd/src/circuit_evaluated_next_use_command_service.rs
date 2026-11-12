//! The actual original Observer owner retains each fixed command profile and
//! its original T/B/S clients. No cached receipt substitutes for those reads.

use super::*;
use crate::{OriginalCellEvaluationCommandClientV1, OriginalCellQ24TrainingCommandClientV1};
use crate::OriginalCircuitEvaluatedNextUseRemoteSourcesV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

pub(super) enum OriginalPredecessors {
    Legacy(LearningIterationEvidenceClientV1),
    Evaluated {
        trainer: OriginalCellQ24TrainingCommandClientV1,
        evaluator: OriginalCellEvaluationCommandClientV1,
    },
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitNextUseCommandOwnerV1<W> {
    pub(crate) fn from_original_evaluated_receipt_owner(
        owner: OriginalCircuitNextUseReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        trainer: OriginalCellQ24TrainingCommandClientV1,
        evaluator: OriginalCellEvaluationCommandClientV1,
        selector: LearningIterationEvidenceClientV1,
    ) -> Result<Self, Error> {
        let original = owner.original_evaluated_command_selection()
            .ok_or(Error::Binding("original evaluated Observer custody"))?;
        let context = OriginalCircuitNextUseCommandContextV1::from_evaluated_selection(original)?;
        live.require_original_evaluated_next_use(original)
            .map_err(OriginalCircuitNextUseReceiptErrorV1::from)?;
        let (_, readback_only) = owner.original_command_profile();
        let initial = context.initial()?;
        if selector.initial != initial || selector.actor_id != context.selection.owners.selector
            || selector.verifier.trust_digest() != context.verifier.trust_digest()
            || selector.verifier.scope_digest() != context.verifier.scope_digest()
            || selector.verifier.objective_digest() != context.verifier.objective_digest() {
            return Err(Error::Binding("same original evaluated Selector readback client"));
        }
        let binding = context.binding(now()?)?;
        Ok(Self {
            owner: Mutex::new(owner), live,
            predecessors: OriginalPredecessors::Evaluated { trainer, evaluator }, selector,
            context, initial_head: initial.head_digest, binding,
            execution_requested: AtomicBool::new(readback_only),
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    pub(super) fn observe_original(
        &self,
        owner: &mut OriginalCircuitNextUseReceiptOwnerV1<W>,
        action: wire::Action,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), OriginalCircuitNextUseReceiptErrorV1> {
        match &self.predecessors {
            OriginalPredecessors::Legacy(trainer) => {
                let source = OriginalCircuitNextUseRemoteSourcesV1 {
                    snapshot: &self.context.selection, live: &self.live, trainer, selector: &self.selector,
                };
                match action {
                    wire::Action::Execute => self.runtime.block_on(
                        OriginalCircuitNextUseReceiptOwnerV1::attest_original_remote_completion(owner, source)),
                    wire::Action::Readback => self.runtime.block_on(
                        OriginalCircuitNextUseReceiptOwnerV1::readback_remote(owner, source)),
                }
            }
            OriginalPredecessors::Evaluated { trainer, evaluator } => {
                let selection = self.context.evaluated.as_ref().ok_or(
                    crate::learning_owner_journal::LearningOriginalOwnerErrorV1::Binding("original evaluated Observer command profile"))?;
                let source = OriginalCircuitEvaluatedNextUseRemoteSourcesV1 {
                    snapshot: &self.context.selection, selection, live: &self.live, trainer, evaluator, selector: &self.selector,
                };
                let original = match action {
                    wire::Action::Execute => self.runtime.block_on(
                        OriginalCircuitNextUseReceiptOwnerV1::attest_original_evaluated_remote_completion(owner, source)),
                    wire::Action::Readback => self.runtime.block_on(
                        OriginalCircuitNextUseReceiptOwnerV1::readback_evaluated_remote_completion(owner, source)),
                }?;
                Ok((original.receipt().clone(), original.attestation().clone()))
            }
        }
    }
}
