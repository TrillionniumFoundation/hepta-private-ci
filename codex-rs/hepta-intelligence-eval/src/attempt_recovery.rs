//! Read-only reconciliation of durable attempt intents against existing owners.
//!
//! No provider release, estimator execution, holdout CAS or publication write is
//! available here. Missing records remain unresolved, never a retry permission.
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::StableId;

use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalV1;
use crate::ProductEvaluationAttemptJournalErrorV1;
use crate::ProductEvaluationAttemptJournalV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductQualificationPublicationStoreV1;

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

/// Associate an intent with a consumption already recorded by the holdout owner.
/// The selected host must authenticate the store and enforce its retained anchor.
pub fn reconcile_product_attempt_holdout_v1<J, S>(
    journal: &mut J,
    store: &mut S,
    attempt_id: &StableId,
) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1>
where
    J: ProductEvaluationAttemptJournalV1,
    S: FinalHoldoutCasStoreV1,
{
    let history = journal.history(attempt_id)?;
    let latest = history.last().ok_or(ProductAttemptRecoveryErrorV1::MissingIntent)?;
    if latest.transition.phase != ProductEvaluationAttemptPhaseV1::IntentPersisted {
        return Err(ProductAttemptRecoveryErrorV1::WrongPhase);
    }
    latest.validate_integrity()?;
    let intent = &latest.transition;
    let namespace = intent.holdout_record_digest;
    let current = store.load(namespace)
        .map_err(|_| ProductAttemptRecoveryErrorV1::Unresolved)?
        .ok_or(ProductAttemptRecoveryErrorV1::Unresolved)?;
    current.validate(namespace)
        .map_err(|_| ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    let recovered = FinalHoldoutJournalV1::from_snapshot_with_record_limit(current.journal, 1_000_000)
        .map_err(|_| ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    let consumed = recovered.records().iter()
        .find(|record| record.plan.plan_digest == intent.plan_digest)
        .ok_or(ProductAttemptRecoveryErrorV1::Unresolved)?;
    Ok(journal.append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
        attempt_id.clone(),
        intent.plan_digest,
        consumed.record_digest,
    ))?)
}

/// Reconcile exactly the preregistered publication request, with no write retry.
pub fn reconcile_product_attempt_publication_v1<J, S>(
    journal: &mut J,
    store: &mut S,
    attempt_id: &StableId,
) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1>
where
    J: ProductEvaluationAttemptJournalV1,
    S: ProductQualificationPublicationStoreV1,
{
    let history = journal.history(attempt_id)?;
    let latest = history.last().ok_or(ProductAttemptRecoveryErrorV1::MissingIntent)?;
    latest.validate_integrity()?;
    if latest.transition.phase == ProductEvaluationAttemptPhaseV1::Published {
        return Ok(latest.clone());
    }
    if latest.transition.phase != ProductEvaluationAttemptPhaseV1::PublicationPending {
        return Err(ProductAttemptRecoveryErrorV1::WrongPhase);
    }
    let sealed = history.iter().find(|receipt| {
        receipt.transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed
    }).ok_or(ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    sealed.validate_integrity()?;
    if sealed.transition.plan_digest != latest.transition.plan_digest
        || sealed.transition.holdout_record_digest != latest.transition.holdout_record_digest
    {
        return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
    }
    let execution = sealed.transition.terminal_digest;
    let record = store.load(execution)
        .map_err(|_| ProductAttemptRecoveryErrorV1::Unresolved)?
        .ok_or(ProductAttemptRecoveryErrorV1::Unresolved)?;
    record.validate().map_err(|_| ProductAttemptRecoveryErrorV1::EvidenceMismatch)?;
    if record.request.execution_digest != execution
        || record.request.request_digest != latest.transition.terminal_digest
    {
        return Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch);
    }
    Ok(journal.append(ProductEvaluationAttemptTransitionV1 {
        attempt_id: attempt_id.clone(),
        plan_digest: latest.transition.plan_digest,
        phase: ProductEvaluationAttemptPhaseV1::Published,
        holdout_record_digest: latest.transition.holdout_record_digest,
        terminal_digest: record.publication_digest,
    })?)
}
