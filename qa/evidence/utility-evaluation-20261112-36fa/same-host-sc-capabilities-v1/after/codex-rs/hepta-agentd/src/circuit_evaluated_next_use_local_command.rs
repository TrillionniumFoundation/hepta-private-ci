//! Concrete same-host C adapter. No arbitrary source callback, raw selector
//! evidence, socket or new predecessor authority is accepted by this branch.

use super::*;

pub(super) enum OriginalSelector {
    Remote(LearningIterationEvidenceClientV1),
    Local(crate::OriginalCircuitSelectionLocalReadbackV1),
}

impl OriginalSelector {
    pub(super) fn remote(
        &self,
    ) -> Result<&LearningIterationEvidenceClientV1, OriginalCircuitNextUseReceiptErrorV1> {
        match self {
            Self::Remote(value) => Ok(value),
            Self::Local(_) => Err(
                LearningOriginalOwnerErrorV1::Binding("original remote Selector purpose").into(),
            ),
        }
    }
}

impl<W: AnchorWitnessStore + Send + 'static> OriginalCircuitNextUseCommandOwnerV1<W> {
    pub(crate) fn from_original_evaluated_local_shared_receipt_owner(
        owner: OriginalCircuitNextUseReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        shared: crate::OriginalCircuitPublishedEvidenceReadbackV1,
        selector: crate::OriginalCircuitSelectionLocalReadbackV1,
    ) -> Result<Self, Error> {
        let original = OriginalCircuitNextUseReceiptOwnerV1::original_evaluated_command_selection(
            &owner,
        ).ok_or(Error::Binding("original evaluated local Observer custody"))?;
        OriginalCircuitLearningReadClientV1::require_original_local_evaluated_next_use(
            &live,
            original,
        ).map_err(OriginalCircuitNextUseReceiptErrorV1::from)?;
        crate::OriginalCircuitPublishedEvidenceReadbackV1::require_original_context(
            &shared,
            original.original_context(),
        ).map_err(OriginalCircuitNextUseReceiptErrorV1::from)?;
        crate::OriginalCircuitSelectionLocalReadbackV1::require_original_selection(
            &selector,
            original,
        ).map_err(|error| OriginalCircuitNextUseReceiptErrorV1::LocalSelection(Box::new(error)))?;
        crate::OriginalCircuitSelectionLocalReadbackV1::require_original_shared_predecessors(
            &selector,
            &shared,
        ).map_err(|error| OriginalCircuitNextUseReceiptErrorV1::LocalSelection(Box::new(error)))?;
        let context = OriginalCircuitNextUseCommandContextV1::from_evaluated_selection(original)?;
        let (_, readback_only) =
            OriginalCircuitNextUseReceiptOwnerV1::original_command_profile(&owner);
        let initial = context.initial()?;
        let binding = context.binding(now()?)?;
        Ok(Self {
            owner: Mutex::new(owner),
            live,
            predecessors: OriginalPredecessors::SharedLocalEvaluated(shared),
            selector: OriginalSelector::Local(selector),
            context,
            initial_head: initial.head_digest,
            binding,
            execution_requested: AtomicBool::new(readback_only),
            runtime: Handle::try_current().map_err(|_| Error::Unavailable)?,
            connections: Arc::new(Semaphore::new(4)),
        })
    }

    pub(super) fn observe_original_local(
        &self,
        owner: &mut OriginalCircuitNextUseReceiptOwnerV1<W>,
        action: wire::Action,
        shared: &crate::OriginalCircuitPublishedEvidenceReadbackV1,
    ) -> Result<
        (
            codex_hepta_learning_artifacts::LearningIterationReceiptV1,
            codex_hepta_learning_ledger::SignedLearningEvidenceV1,
        ),
        OriginalCircuitNextUseReceiptErrorV1,
    > {
        let selection = self.context.evaluated.as_ref().ok_or(
            LearningOriginalOwnerErrorV1::Binding("original local evaluated Observer profile"),
        )?;
        let OriginalSelector::Local(selector) = &self.selector else {
            return Err(
                LearningOriginalOwnerErrorV1::Binding("original local Selector capability").into(),
            );
        };
        let source =
            crate::circuit_next_use_receipt_owner::OriginalCircuitEvaluatedNextUseLocalSourcesV1 {
                snapshot: &self.context.selection,
                selection,
                live: &self.live,
                shared,
                selector,
            };
        let completed = match action {
            wire::Action::Execute => self.runtime.block_on(
                OriginalCircuitNextUseReceiptOwnerV1::attest_original_evaluated_local_completion(
                    owner,
                    source,
                ),
            ),
            wire::Action::Readback => self.runtime.block_on(
                OriginalCircuitNextUseReceiptOwnerV1::readback_evaluated_local_completion(
                    owner,
                    source,
                ),
            ),
        }?;
        Ok((completed.receipt().clone(), completed.attestation().clone()))
    }
}
