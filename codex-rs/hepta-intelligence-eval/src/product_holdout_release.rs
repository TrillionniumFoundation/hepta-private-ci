//! A synchronous borrow of the original consumed holdout owner. The public
//! journal receipt remains data: it cannot construct this borrow, authenticate
//! an Evaluator, admit held-out inputs or establish independent data custody.

use codex_hepta_types::Digest32;

use super::FinalHoldoutProviderV1;
use super::ProductEvaluationError;
use super::ProductProviderErrorV1;
use super::TemporalComparisonInputsV1;
use crate::CrossFoldPlanReceiptV1;
use crate::FencedFinalHoldoutOwnerV1;
use crate::FencedHoldoutError;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::HoldoutUseDispositionV1;

/// Type erasure keeps the original mutable owner borrowed through a provider
/// call without exposing its store, writer or a constructor to the provider.
trait OriginalHoldoutReadV1 {
    fn observe_consumption(
        &mut self,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<(Digest32, Option<FinalHoldoutJournalReceiptV1>), FencedHoldoutError>;
}

impl<S: FinalHoldoutCasStoreV1> OriginalHoldoutReadV1 for FencedFinalHoldoutOwnerV1<S> {
    fn observe_consumption(
        &mut self,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<(Digest32, Option<FinalHoldoutJournalReceiptV1>), FencedHoldoutError> {
        FencedFinalHoldoutOwnerV1::read_consumption(self, plan)
    }
}

fn require_recorded(
    original: &mut dyn OriginalHoldoutReadV1,
    namespace: Digest32,
    plan: &CrossFoldPlanReceiptV1,
    receipt: &FinalHoldoutJournalReceiptV1,
) -> Result<(), FencedHoldoutError> {
    let (actual_namespace, actual) = original.observe_consumption(plan)?;
    if namespace != actual_namespace
        || receipt.disposition != HoldoutUseDispositionV1::Recorded
        || actual.as_ref() != Some(receipt)
    {
        return Err(FencedHoldoutError::Binding);
    }
    Ok(())
}

/// Non-cloneable, non-serializable borrow supplied only by the runner after a
/// fresh `Recorded` transition and a full original-owner readback. Its lifetime
/// retains the same mutable owner. It is not a role or independent-data grant.
pub struct OriginalFinalHoldoutConsumptionV1<'a> {
    original: &'a mut dyn OriginalHoldoutReadV1,
    namespace: Digest32,
    plan: &'a CrossFoldPlanReceiptV1,
    receipt: &'a FinalHoldoutJournalReceiptV1,
}

impl OriginalFinalHoldoutConsumptionV1<'_> {
    /// Consume this borrow once. Re-read the original store before releasing
    /// data and after the callback, including when the callback failed. A
    /// provider must still validate its own original signed input admission.
    pub fn with_current_consumption(
        self,
        release: impl FnOnce(
            Digest32,
            &CrossFoldPlanReceiptV1,
            &FinalHoldoutJournalReceiptV1,
        ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1>,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        require_recorded(self.original, self.namespace, self.plan, self.receipt)
            .map_err(|_| ProductProviderErrorV1::Indeterminate)?;
        let released = release(self.namespace, self.plan, self.receipt);
        require_recorded(self.original, self.namespace, self.plan, self.receipt)
            .map_err(|_| ProductProviderErrorV1::Indeterminate)?;
        released
    }
}

pub(super) fn release_original_holdout<S: FinalHoldoutCasStoreV1, P: FinalHoldoutProviderV1>(
    original: &mut FencedFinalHoldoutOwnerV1<S>,
    plan: &CrossFoldPlanReceiptV1,
    receipt: &FinalHoldoutJournalReceiptV1,
    provider: &mut P,
) -> Result<TemporalComparisonInputsV1, ProductEvaluationError> {
    let (namespace, recorded) = FencedFinalHoldoutOwnerV1::read_consumption(original, plan)?;
    if receipt.disposition != HoldoutUseDispositionV1::Recorded
        || recorded.as_ref() != Some(receipt)
    {
        return Err(ProductEvaluationError::Binding(
            "original holdout consumption",
        ));
    }
    let released = provider.release_after_original_consumption(OriginalFinalHoldoutConsumptionV1 {
        original,
        namespace,
        plan,
        receipt,
    });
    // Check even a provider that returned without using its borrow. No inputs
    // reach fitting/OPE if the physical owner changed or became uncertain.
    require_recorded(original, namespace, plan, receipt)?;
    released.map_err(ProductEvaluationError::Provider)
}
