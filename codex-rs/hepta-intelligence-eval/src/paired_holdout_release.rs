//! A synchronous borrow of the original paired consumption. Public receipts
//! remain evidence, not role, data-custody or physical-owner authority. A host
//! must retain its own store and independently admitted, frozen engineering
//! bundle; this adapter does not authenticate a caller-supplied CAS store.

use super::PairedDataV1;
use super::PairedEvaluationError;
use super::PairedFinalHoldoutProviderV1;
use super::ProductProviderErrorV1;
use crate::FencedFinalHoldoutOwnerV1;
use crate::FencedHoldoutError;
use crate::FinalHoldoutCasStoreV1;
use crate::FrozenPairedPlanV1;
use crate::PairedHoldoutJournalReceiptV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

/// Keep the actual mutable owner borrowed without exposing its store or writer.
trait OriginalPairedHoldoutReadV1 {
    fn require_consumption(
        &mut self,
        plan: &FrozenPairedPlanV1,
        receipt: &PairedHoldoutJournalReceiptV1,
    ) -> Result<Digest32, FencedHoldoutError>;
}

impl<S: FinalHoldoutCasStoreV1> OriginalPairedHoldoutReadV1 for FencedFinalHoldoutOwnerV1<S> {
    fn require_consumption(
        &mut self,
        plan: &FrozenPairedPlanV1,
        receipt: &PairedHoldoutJournalReceiptV1,
    ) -> Result<Digest32, FencedHoldoutError> {
        self.require_paired_consumption(plan, receipt)
    }
}

fn require_current(
    original: &mut dyn OriginalPairedHoldoutReadV1,
    namespace: Digest32,
    plan: &FrozenPairedPlanV1,
    receipt: &PairedHoldoutJournalReceiptV1,
) -> Result<(), FencedHoldoutError> {
    if original.require_consumption(plan, receipt)? != namespace {
        return Err(FencedHoldoutError::Binding);
    }
    Ok(())
}

/// Non-cloneable and non-serializable borrow of the original current owner.
/// Exact retries retain the same frozen engineering bundle; they do not grant
/// another experiment, qualification, promotion or independent data custody.
pub struct OriginalPairedFinalHoldoutConsumptionV1<'a> {
    original: &'a mut dyn OriginalPairedHoldoutReadV1,
    namespace: Digest32,
    plan: &'a FrozenPairedPlanV1,
    receipt: &'a PairedHoldoutJournalReceiptV1,
}

impl OriginalPairedFinalHoldoutConsumptionV1<'_> {
    /// Re-read before and after the callback, including a failing callback.
    /// The provider must still enforce its own signed input and custody rules.
    pub fn with_current_consumption(
        self,
        release: impl FnOnce(
            Digest32,
            &FrozenPairedPlanV1,
            &PairedHoldoutJournalReceiptV1,
        )
            -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1>,
    ) -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1> {
        require_current(self.original, self.namespace, self.plan, self.receipt)
            .map_err(|_| ProductProviderErrorV1::Indeterminate)?;
        let released = release(self.namespace, self.plan, self.receipt);
        require_current(self.original, self.namespace, self.plan, self.receipt)
            .map_err(|_| ProductProviderErrorV1::Indeterminate)?;
        released
    }
}

pub(super) fn release_original_frozen_paired_holdout<
    S: FinalHoldoutCasStoreV1,
    P: PairedFinalHoldoutProviderV1,
>(
    original: &mut FencedFinalHoldoutOwnerV1<S>,
    plan: &FrozenPairedPlanV1,
    receipt: &PairedHoldoutJournalReceiptV1,
    provider: &mut P,
) -> Result<(PairedDataV1, SignedLearningEvidenceV1), PairedEvaluationError> {
    let namespace = original
        .require_paired_consumption(plan, receipt)
        .map_err(PairedEvaluationError::Holdout)?;
    let released =
        provider.release_after_original_consumption(OriginalPairedFinalHoldoutConsumptionV1 {
            original,
            namespace,
            plan,
            receipt,
        });
    // A provider may return without consuming its borrow. Check the original
    // owner anyway, before any released rows reach derivation or publication.
    require_current(original, namespace, plan, receipt).map_err(PairedEvaluationError::Holdout)?;
    released.map_err(PairedEvaluationError::Provider)
}
