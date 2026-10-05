//! Reconcile durable attempts against existing authoritative owner records.
//!
//! Reconciliation reads the holdout/publication owners and appends only to the
//! independently anchored attempt journal. It never releases observations or
//! re-executes estimators. A missing publication is not permission to retry an
//! unknown write. The explicit decided-only resume path may perform the first
//! publication, but only for the exact decision already bound in the journal.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalV1;
use crate::InMemoryProductEvaluationAttemptJournalV1;
use crate::ProductEvaluationAttemptJournalErrorV1;
use crate::ProductEvaluationAttemptJournalV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductQualificationPublicationStoreV1;
use crate::RecordedProductEvaluationRunnerV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductAttemptRecoveryErrorV1 {
    Journal(ProductEvaluationAttemptJournalErrorV1),
    MissingIntent,
    WrongPhase,
    Unresolved,
    EvidenceMismatch,
}

impl fmt::Display for ProductAttemptRecoveryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductAttemptRecoveryErrorV1 {}
impl From<ProductEvaluationAttemptJournalErrorV1> for ProductAttemptRecoveryErrorV1 {
    fn from(value: ProductEvaluationAttemptJournalErrorV1) -> Self {
        Self::Journal(value)
    }
}

/// Validate the entire phase/identity/digest chain, not merely its last frame.
/// The in-memory reducer is a validator, never the durable owner. The bounded
/// history admits the current artifact phase without admitting repeated durable
/// acknowledgements or skipping the reducer's legal transitions.
pub(crate) fn validated_history<J: ProductEvaluationAttemptJournalV1>(
    journal: &mut J,
    attempt_id: &StableId,
) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductAttemptRecoveryErrorV1> {
    let history = journal.history(attempt_id)?;
    if history.is_empty() {
        return Err(ProductAttemptRecoveryErrorV1::MissingIntent);
    }
    if history.len() > 8 {
        return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
    }
    let mut replay = InMemoryProductEvaluationAttemptJournalV1::default();
    for (index, receipt) in history.iter().enumerate() {
        receipt.validate_integrity()?;
        if &receipt.transition.attempt_id != attempt_id || receipt.sequence != (index as u64) + 1 {
            return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
        }
        let expected = replay
            .append(receipt.transition.clone())
            .map_err(|_| ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
        if expected != *receipt {
            return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
        }
    }
    if journal.latest(attempt_id)?.as_ref() != history.last() {
        return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
    }
    Ok(history)
}

/// Associate an intent with consumption already recorded by the holdout owner.
/// The selected host must authenticate the store and enforce its retained anchor.
pub fn reconcile_product_attempt_holdout_v1<J, S>(
    journal: &mut J,
    store: &mut S,
    attempt_id: &StableId,
) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1>
where
    J: DurableProductEvaluationAttemptJournalV1,
    S: FinalHoldoutCasStoreV1,
{
    let history = validated_history(journal, attempt_id)?;
    let latest = history
        .last()
        .ok_or(ProductAttemptRecoveryErrorV1::MissingIntent)?;
    let intent = &latest.transition;
    if intent.phase != ProductEvaluationAttemptPhaseV1::IntentPersisted {
        return Err(ProductAttemptRecoveryErrorV1::WrongPhase);
    }
    let namespace = intent.holdout_record_digest;
    let current = store
        .load(namespace)
        .map_err(|_| ProductAttemptRecoveryErrorV1::Unresolved)?
        .ok_or(ProductAttemptRecoveryErrorV1::Unresolved)?;
    current
        .validate(namespace)
        .map_err(|_| ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    let recovered =
        FinalHoldoutJournalV1::from_snapshot_with_record_limit(current.journal, 1_000_000)
            .map_err(|_| ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    let consumed = recovered
        .records()
        .iter()
        .find(|record| record.plan.plan_digest == intent.plan_digest)
        .ok_or(ProductAttemptRecoveryErrorV1::Unresolved)?;
    Ok(
        journal.append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
            attempt_id.clone(),
            intent.plan_digest,
            consumed.record_digest,
        ))?,
    )
}

/// Read-verify the exact preregistered publication; never repeat a store write.
/// Even a Published history must still match the actual durable publication.
/// Missing records preserve the historical phase and remain unresolved: the
/// journal is not a substitute for the publication owner's current observation.
pub fn reconcile_product_attempt_publication_v1<J, S>(
    journal: &mut J,
    store: &mut S,
    attempt_id: &StableId,
) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1>
where
    J: DurableProductEvaluationAttemptJournalV1,
    S: ProductQualificationPublicationStoreV1,
{
    use ProductEvaluationAttemptPhaseV1 as Phase;
    let history = validated_history(journal, attempt_id)?;
    let latest = history
        .last()
        .ok_or(ProductAttemptRecoveryErrorV1::MissingIntent)?;
    latest.validate_integrity()?;
    if !matches!(
        latest.transition.phase,
        Phase::QualificationDecided | Phase::PublicationPending | Phase::Published
    ) {
        return Err(ProductAttemptRecoveryErrorV1::WrongPhase);
    }
    let sealed = history
        .iter()
        .find(|receipt| receipt.transition.phase == Phase::ComparisonSealed)
        .ok_or(ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    let decided = history
        .iter()
        .find(|receipt| receipt.transition.phase == Phase::QualificationDecided)
        .ok_or(ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    let execution = sealed.transition.terminal_digest;
    let request_digest = decided.transition.terminal_digest;
    let record = store
        .load(execution)
        .map_err(|_| ProductAttemptRecoveryErrorV1::Unresolved)?
        .ok_or(ProductAttemptRecoveryErrorV1::Unresolved)?;
    record
        .validate()
        .map_err(|_| ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    if record.request.execution_digest != execution
        || record.request.request_digest != request_digest
    {
        return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
    }
    if latest.transition.phase == Phase::Published {
        if latest.transition.terminal_digest != record.publication_digest {
            return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
        }
        return Ok(latest.clone());
    }
    if latest.transition.terminal_digest != request_digest {
        return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
    }
    if latest.transition.phase == Phase::QualificationDecided {
        journal.append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: latest.transition.plan_digest,
            phase: Phase::PublicationPending,
            holdout_record_digest: latest.transition.holdout_record_digest,
            terminal_digest: request_digest,
        })?;
    }
    Ok(journal.append(ProductEvaluationAttemptTransitionV1 {
        attempt_id: attempt_id.clone(),
        plan_digest: latest.transition.plan_digest,
        phase: Phase::Published,
        holdout_record_digest: latest.transition.holdout_record_digest,
        terminal_digest: record.publication_digest,
    })?)
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    /// Inspect one bounded page. Advance past unresolved/failed entries instead
    /// of repeatedly selecting the first blocked attempt. None ends this sweep;
    /// the host may start a subsequent sweep from the beginning. The host must
    /// retain the returned cursor and prevent concurrent live-attempt recovery.
    /// Store reads are bounded by `limit` attempts; no provider is accepted here.
    #[allow(clippy::type_complexity)]
    pub fn reconcile_pending_page<J, H, P>(
        journal: &mut J,
        holdout_store: &mut H,
        publication_store: &mut P,
        after: Option<&StableId>,
        limit: usize,
    ) -> Result<
        (
            Vec<(
                StableId,
                Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1>,
            )>,
            Option<StableId>,
        ),
        ProductAttemptRecoveryErrorV1,
    >
    where
        J: DurableProductEvaluationAttemptJournalV1,
        H: FinalHoldoutCasStoreV1,
        P: ProductQualificationPublicationStoreV1,
    {
        if !(1..=1024).contains(&limit) {
            return Err(ProductEvaluationAttemptJournalErrorV1::Capacity.into());
        }
        let page = journal.pending(after, limit)?;
        if page.len() > limit {
            return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
        }
        let mut previous = after.cloned();
        // Validate inventory before any mutation, including strict cursor order.
        for receipt in &page {
            receipt.validate_integrity()?;
            let id = &receipt.transition.attempt_id;
            if receipt.transition.phase.is_terminal()
                || previous.as_ref().is_some_and(|value| value >= id)
            {
                return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
            }
            previous = Some(id.clone());
        }
        let cursor = if page.len() == limit { previous } else { None };
        let mut results = Vec::with_capacity(page.len());
        for receipt in page {
            let id = receipt.transition.attempt_id;
            let result = match receipt.transition.phase {
                ProductEvaluationAttemptPhaseV1::IntentPersisted => {
                    reconcile_product_attempt_holdout_v1(journal, holdout_store, &id)
                }
                ProductEvaluationAttemptPhaseV1::QualificationDecided
                | ProductEvaluationAttemptPhaseV1::PublicationPending => {
                    reconcile_product_attempt_publication_v1(journal, publication_store, &id)
                }
                // Lost estimator/evidence payloads require authoritative object
                // recovery. Never silently rerun a consumed final holdout.
                _ => Err(ProductAttemptRecoveryErrorV1::Unresolved),
            };
            if matches!(
                result,
                Err(ProductAttemptRecoveryErrorV1::Journal(
                    ProductEvaluationAttemptJournalErrorV1::Indeterminate
                ))
            ) {
                return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate.into());
            }
            results.push((id, result));
        }
        Ok((results, cursor))
    }
}

#[cfg(test)]
#[path = "attempt_publication_integrity_tests.rs"]
mod publication_integrity_tests;
#[cfg(test)]
#[path = "attempt_recovery_tests.rs"]
mod tests;
