//! Opaque, independently selected NDU admission for a Cell Split canary.
//!
//! A positive evaluator outcome alone cannot dispatch a child.  The selector
//! must already have verified a frozen no-change baseline, a longitudinal
//! future window, signed generator/evaluator/observer evidence, and an
//! authoritative dataset ledger through the existing SelfEvolution selector.
//! This module binds that opaque selector token to the *same* split and
//! evaluated evidence. It confers no external-effect authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, CellSplitV1, Digest32, StableId};

use crate::CellSplitLongHorizonEvaluationReceiptV1;
use crate::VerifiedSelfEvolutionSelectionV1;
use crate::cell_split_evaluation::disposition_allows_canary;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitSelectorErrorV1 {
    SplitPlan,
    Evaluation,
    SelectionBinding,
    RoleCollision,
}

impl fmt::Display for CellSplitSelectorErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for CellSplitSelectorErrorV1 {}

/// Only `admit_verified_cell_split_selector_v1` can mint a production token.
/// No digest-only or asserted selector decision constructor is public.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitSelectorAdmissionV1 {
    split_id: StableId,
    evaluator_receipt_digest: Digest32,
    subject_digest: Digest32,
    selector_id: StableId,
    execution_owner_id: StableId,
    frozen_baseline_digest: Digest32,
    child_artifact_set_digest: Digest32,
    selection_digest: Digest32,
    admission_digest: Digest32,
    authority: AuthorityPosture,
}

impl CellSplitSelectorAdmissionV1 {
    pub fn selector_id(&self) -> &StableId {
        &self.selector_id
    }

    pub fn admission_digest(&self) -> Digest32 {
        self.admission_digest
    }

    /// The execution owner must recheck the candidate, evaluator and its
    /// own identity at the final-use boundary, *after* reading the ledger.
    pub fn verify_for_canary(
        &self,
        split: &CellSplitV1,
        evaluation: &CellSplitLongHorizonEvaluationReceiptV1,
        execution_owner_id: &StableId,
    ) -> Result<(), CellSplitSelectorErrorV1> {
        split.validate_plan().map_err(|_| CellSplitSelectorErrorV1::SplitPlan)?;
        evaluation.verify_contract(split).map_err(|_| CellSplitSelectorErrorV1::Evaluation)?;
        if !disposition_allows_canary(evaluation)
            || self.split_id != split.split_id
            || self.evaluator_receipt_digest != evaluation.binding().evaluation_receipt_digest
            || self.subject_digest != evaluation.subject_digest()
            || &self.execution_owner_id != execution_owner_id
            || self.selection_digest.is_zero()
            || self.child_artifact_set_digest.is_zero()
            || self.frozen_baseline_digest.is_zero()
            || self.authority != AuthorityPosture::DENY_ALL
            || self.selector_id == split.proposer_id
            || self.selector_id == split.evaluator_id
            || self.selector_id == *execution_owner_id
            || self.admission_digest != self.compute_digest()
        {
            return Err(CellSplitSelectorErrorV1::SelectionBinding);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell-split.ndu-independent-selector-admission.v1".to_vec();
        for id in [
            &self.split_id,
            &self.selector_id,
            &self.execution_owner_id,
        ] {
            bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
            bytes.extend_from_slice(id.as_str().as_bytes());
        }
        for digest in [
            self.evaluator_receipt_digest,
            self.subject_digest,
            self.frozen_baseline_digest,
            self.child_artifact_set_digest,
            self.selection_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Bind an *already independently admitted*, opaque selector certificate to
/// the signed NDU evaluation and a real CAS-owned child artifact-set anchor.
/// Callers cannot supply bare selection digests instead of the verified token.
pub fn admit_verified_cell_split_selector_v1(
    split: &CellSplitV1,
    evaluation: &CellSplitLongHorizonEvaluationReceiptV1,
    selection: &VerifiedSelfEvolutionSelectionV1,
    child_artifact_set_digest: Digest32,
    execution_owner_id: &StableId,
) -> Result<CellSplitSelectorAdmissionV1, CellSplitSelectorErrorV1> {
    split.validate_plan().map_err(|_| CellSplitSelectorErrorV1::SplitPlan)?;
    evaluation.verify_contract(split).map_err(|_| CellSplitSelectorErrorV1::Evaluation)?;
    if !disposition_allows_canary(evaluation) {
        return Err(CellSplitSelectorErrorV1::Evaluation);
    }
    let receipt = selection.receipt();
    if receipt.candidate_id != split.split_id
        || receipt.candidate_generation != split.successor_generation
        || receipt.predecessor_id != split.parent_cell_id
        || receipt.predecessor_generation != split.predecessor_generation
        || receipt.predecessor_artifact_digest != split.parent_bundle_digest
        || receipt.candidate_artifact_digest != child_artifact_set_digest
        || receipt.no_change_baseline_id != split.evaluation.no_change_baseline_id
        || receipt.no_change_baseline_digest.is_zero()
        || receipt.frozen_plan_digest.is_zero()
        || receipt.evaluation_evidence_digest
            != evaluation.decision().decision.evidence_digest
        || receipt.evaluation_authentication_digest
            != evaluation.decision().authentication_digest
        || receipt.evaluation_trust_digest != evaluation.decision().trust_digest
        || receipt.minimum_dataset_records == 0
        || receipt.minimum_future_window_micros == 0
        || child_artifact_set_digest.is_zero()
        || selection.selection_digest().is_zero()
    {
        return Err(CellSplitSelectorErrorV1::SelectionBinding);
    }
    if selection.selector_id() == &split.proposer_id
        || selection.selector_id() == &split.evaluator_id
        || selection.selector_id() == execution_owner_id
        || execution_owner_id == &split.proposer_id
        || execution_owner_id == &split.evaluator_id
    {
        return Err(CellSplitSelectorErrorV1::RoleCollision);
    }
    let mut result = CellSplitSelectorAdmissionV1 {
        split_id: split.split_id.clone(),
        evaluator_receipt_digest: evaluation.binding().evaluation_receipt_digest,
        subject_digest: evaluation.subject_digest(),
        selector_id: selection.selector_id().clone(),
        execution_owner_id: execution_owner_id.clone(),
        frozen_baseline_digest: receipt.no_change_baseline_digest,
        child_artifact_set_digest,
        selection_digest: selection.selection_digest(),
        admission_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.admission_digest = result.compute_digest();
    result.verify_for_canary(split, evaluation, execution_owner_id)?;
    Ok(result)
}

#[cfg(test)]
pub(crate) fn test_selection_admission_for_lifecycle_v1(
    split: &CellSplitV1,
    evaluation: &CellSplitLongHorizonEvaluationReceiptV1,
    executor_id: &StableId,
) -> CellSplitSelectorAdmissionV1 {
    // Test-only fixture: the product constructor accepts only the opaque
    // VerifiedSelfEvolutionSelectionV1 obtained from signed role separation.
    let mut result = CellSplitSelectorAdmissionV1 {
        split_id: split.split_id.clone(),
        evaluator_receipt_digest: evaluation.binding().evaluation_receipt_digest,
        subject_digest: evaluation.subject_digest(),
        selector_id: StableId::new("test-independent-selector").expect("selector"),
        execution_owner_id: executor_id.clone(),
        frozen_baseline_digest: Digest32::of_bytes(b"test-frozen-no-change-baseline"),
        child_artifact_set_digest: Digest32::of_bytes(b"test-native-child-artifact-set"),
        selection_digest: Digest32::of_bytes(b"test-verified-selector-evidence"),
        admission_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.admission_digest = result.compute_digest();
    result
}
