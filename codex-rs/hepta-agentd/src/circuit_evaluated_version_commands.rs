//! Seal actual S/C receipt owners around Version's post-publication T/B pair.
//! No evidence client, signing custody or writable Cell/Source getter escapes.
//! All supplied read clients keep their original channel counters and ends.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::Error;
use super::super::RetainedVersionOriginV1;
use super::super::profile::VersionCut;
use super::super::profile::VersionPurpose;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionHostPhaseV1;
use super::RetainedVersionHostStateV1;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCircuitEvaluatedNextUseCommandOwnerV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitEvaluatedSelectionCommandOwnerV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCircuitSelectionReceiptOwnerV1;

impl OriginalCircuitRetainedVersionHostV1 {
    /// Consume the genuine Selector and its held four-cut task reader. Only
    /// this Version's original post-publication T/B sessions feed the command.
    pub async fn bind_original_evaluated_selection_owner<W: AnchorWitnessStore + Send + 'static>(
        self: Arc<Self>,
        owner: OriginalCircuitSelectionReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
    ) -> Result<OriginalCircuitEvaluatedSelectionCommandOwnerV1<W>, Error> {
        self.require_lifetime()?;
        if self.purpose != VersionPurpose::Evaluated
            || self
                .selection_command_requested
                .swap(true, Ordering::AcqRel)
        {
            return Err(Error::ReadbackRequired);
        }
        let queued = QueuedCommandFactoryFence(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            require_not_cancelled(&cancelled)?;
            self.require_lifetime()?;
            let context =
                OriginalCircuitSelectionReceiptOwnerV1::original_evaluated_command_context(&owner)?;
            let (_, readback_only) =
                OriginalCircuitSelectionReceiptOwnerV1::original_command_profile(&owner);
            if self.origin == RetainedVersionOriginV1::Recovered && !readback_only {
                return Err(Error::ReadbackRequired);
            }
            if !readback_only {
                context.require_new_original_receipt(super::super::now()?)?;
            }
            OriginalCircuitLearningReadClientV1::require_original_evaluated_selection(
                &live, &context,
            )?;
            let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
            self.bind_original_predecessor(&mut state)?;
            self.require_evaluated_command_context(&state, &context)?;
            let before = self.read_original(&state)?;
            require_not_cancelled(&cancelled)?;
            let remote = self
                .runtime
                .block_on(OriginalCircuitLearningReadClientV1::read_current(&live))?;
            // The last original T/B awaits precede the final physical Source,
            // Cell, CURRENT and Artifact reads in read_original.
            let after = self.read_original(&state)?;
            if before != after {
                return Err(Error::Binding(
                    "Version publication changed during Selector binding",
                ));
            }
            remote.require_original_evaluated_version_selection(
                after.publication().ok_or(Error::ReadbackRequired)?,
            )?;
            self.require_evaluated_command_context(&state, &context)?;
            require_not_cancelled(&cancelled)?;
            self.require_lifetime()?;
            let shared = state
                .shared_evaluated
                .as_ref()
                .ok_or(Error::ReadbackRequired)?;
            Ok(owner.into_evaluated_command_owner(
                live,
                Arc::clone(&shared.trainer),
                Arc::clone(&shared.evaluator),
            )?)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }

    /// Consume the actual Observer plus already-held five-cut task and S read
    /// capabilities. This never polls an unresolved C through the C read port.
    pub async fn bind_original_evaluated_next_use_owner<W: AnchorWitnessStore + Send + 'static>(
        self: Arc<Self>,
        owner: OriginalCircuitNextUseReceiptOwnerV1<W>,
        live: OriginalCircuitLearningReadClientV1,
        selector: LearningIterationEvidenceClientV1,
    ) -> Result<OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>, Error> {
        self.require_lifetime()?;
        if self.purpose != VersionPurpose::Evaluated
            || self.next_use_command_requested.swap(true, Ordering::AcqRel)
        {
            return Err(Error::ReadbackRequired);
        }
        let queued = QueuedCommandFactoryFence(Arc::new(AtomicBool::new(false)));
        let cancelled = Arc::clone(&queued.0);
        let result = tokio::task::spawn_blocking(move || {
            require_not_cancelled(&cancelled)?;
            self.require_lifetime()?;
            let selection =
                OriginalCircuitNextUseReceiptOwnerV1::original_evaluated_command_selection(&owner)?;
            let (_, readback_only) =
                OriginalCircuitNextUseReceiptOwnerV1::original_command_profile(&owner);
            if self.origin == RetainedVersionOriginV1::Recovered && !readback_only {
                return Err(Error::ReadbackRequired);
            }
            if !readback_only {
                // A lost Execute acknowledgement or cold S cannot regain a
                // Fresh brand merely because this Version is still Fresh.
                selection
                    .original_context()
                    .require_new_original_receipt(super::super::now()?)?;
            }
            selection.original_receipt_predecessors(super::super::now()?)?;
            OriginalCircuitLearningReadClientV1::require_original_evaluated_next_use(
                &live, &selection,
            )?;
            let mut state = self.state.try_lock().map_err(|_| Error::Busy)?;
            self.bind_original_predecessor(&mut state)?;
            self.require_evaluated_command_context(&state, selection.original_context())?;
            let before = self.read_original(&state)?;
            let original = before.publication().ok_or(Error::ReadbackRequired)?;
            if selection.receipt().observation
                != (LearningIterationObservationV1::Selection {
                    candidate_bundle: original.bundle_digest(),
                    selection_digest: original.selection_digest(),
                })
            {
                return Err(Error::Binding(
                    "same actual Version C and original Selector",
                ));
            }
            require_not_cancelled(&cancelled)?;
            let signature = self
                .runtime
                .block_on(LearningIterationEvidenceClientV1::readback(
                    &selector,
                    selection.snapshot(),
                    selection.receipt(),
                ))?;
            if &signature != selection.attestation() {
                return Err(Error::Binding("same complete original Selector signature"));
            }
            let after = self.read_original(&state)?;
            if before != after {
                return Err(Error::Binding(
                    "Version publication changed during Observer binding",
                ));
            }
            self.require_evaluated_command_context(&state, selection.original_context())?;
            selection.original_receipt_predecessors(super::super::now()?)?;
            require_not_cancelled(&cancelled)?;
            self.require_lifetime()?;
            let shared = state
                .shared_evaluated
                .as_ref()
                .ok_or(Error::ReadbackRequired)?;
            Ok(owner.into_evaluated_command_owner(
                live,
                Arc::clone(&shared.trainer),
                Arc::clone(&shared.evaluator),
                selector,
            )?)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        drop(queued);
        result
    }

    fn require_evaluated_command_context(
        &self,
        state: &RetainedVersionHostStateV1,
        context: &OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<(), Error> {
        if self.purpose != VersionPurpose::Evaluated
            || !matches!(
                state.phase,
                Some(
                    RetainedVersionHostPhaseV1::Installed { .. }
                        | RetainedVersionHostPhaseV1::Recovered(_)
                )
            )
            || state.shared_evaluated.is_none()
        {
            return Err(Error::ReadbackRequired);
        }
        let Some(VersionCut::Evaluated(cut)) = state.cut.as_ref() else {
            return Err(Error::ReadbackRequired);
        };
        context.original_receipt_predecessors(super::super::now()?)?;
        let (scope, verifier, _) = context.receipt_configuration();
        if context.snapshot() != cut.evaluated.snapshot()
            || context.receipt_context_binding() != cut.evaluated.receipt_context_binding()
            || scope != self.material.scope
            || verifier.trust_digest() != self.material.verifier.trust_digest()
            || verifier.scope_digest() != self.material.verifier.scope_digest()
            || verifier.objective_digest() != self.material.verifier.objective_digest()
        {
            return Err(Error::Binding(
                "same original Version four-cut scope and full T/B signatures",
            ));
        }
        Ok(())
    }
}

struct QueuedCommandFactoryFence(Arc<AtomicBool>);
impl Drop for QueuedCommandFactoryFence {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}
fn require_not_cancelled(cancelled: &AtomicBool) -> Result<(), Error> {
    if cancelled.load(Ordering::Acquire) {
        return Err(Error::Cancelled);
    }
    Ok(())
}
