//! Default product ingress accepts the independently anchored journal owner.
//!
//! This marker prevents an accidental in-memory journal at the default API. It
//! does not authenticate an arbitrary implementation of the external anchor
//! authority: that remains a selected-host trust and durability obligation.
use crate::ProductEvaluationAttemptJournalV1;

mod private {
    pub trait Sealed {}
}

/// Journal capability required by the default recorded product facade.
/// The explicit compatibility feature and crate tests permit fault fixtures.
pub trait DurableProductEvaluationAttemptJournalV1:
    ProductEvaluationAttemptJournalV1 + private::Sealed
{
}

#[cfg(not(any(test, feature = "trusted-inprocess-eval")))]
impl<A: crate::ProductEvaluationAttemptAnchorStoreV1> private::Sealed
    for crate::AnchoredProductEvaluationAttemptJournalV1<A>
{
}

#[cfg(not(any(test, feature = "trusted-inprocess-eval")))]
impl<A: crate::ProductEvaluationAttemptAnchorStoreV1> DurableProductEvaluationAttemptJournalV1
    for crate::AnchoredProductEvaluationAttemptJournalV1<A>
{
}

#[cfg(any(test, feature = "trusted-inprocess-eval"))]
impl<J: ProductEvaluationAttemptJournalV1> private::Sealed for J {}

#[cfg(any(test, feature = "trusted-inprocess-eval"))]
impl<J: ProductEvaluationAttemptJournalV1> DurableProductEvaluationAttemptJournalV1 for J {}
