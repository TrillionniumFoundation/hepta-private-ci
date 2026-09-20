//! Delivery-boundary revalidation for a selected prompt portfolio.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::canonical_v1::CanonicalPromptErrorV1;
use crate::canonical_v1::PromptCandidateSetReceiptV1;
use crate::canonical_v1::PromptCandidateSourceAuthenticatorV1;
use crate::canonical_v1::PromptCandidateSourceV1;
use crate::canonical_v1::push_id;
use crate::canonical_v1::push_len;
use crate::canonical_v1::require_digest;
use crate::portfolio_v1::PromptPortfolioErrorV1;
use crate::portfolio_v1::PromptPortfolioReceiptV1;
use crate::pricing_v1::PromptPricingReceiptV1;
use crate::relations_v1::PromptRelationSourceV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseBoundaryV1 {
    RequestAccepted,
    ObjectiveCompiled,
    BeforePlanning,
    BeforeCandidateGeneration,
    BeforeModelOrToolDispatch,
    AfterObservation,
    AfterFailureOrUncertaintySpike,
    BeforeIrreversibleMutation,
    BeforeVerification,
    BeforeFinalResponse,
    BeforeCompactOrHandoff,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseRequestV1 {
    pub exercise_id: StableId,
    pub boundary: PromptExerciseBoundaryV1,
    pub current_state_digest: Digest32,
    pub now_unix_ms: u64,
    pub current_source: PromptCandidateSourceV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseInvalidationV1 {
    StateDrift,
    ModelProfileDrift,
    SelectedCandidateUnavailable,
    SelectedBindingDrift,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseDispositionV1 {
    ExercisePortfolio,
    NoIntervention,
    Invalidated(PromptExerciseInvalidationV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub exercise_id: StableId,
    pub portfolio_receipt_digest: Digest32,
    pub boundary: PromptExerciseBoundaryV1,
    pub disposition: PromptExerciseDispositionV1,
    pub selected_candidate_ids: Vec<StableId>,
    pub current_state_digest: Digest32,
    pub current_registry_snapshot_digest: Digest32,
    pub current_registry_revision: u64,
    pub current_revocation_frontier: u64,
    pub current_generation_vector_digest: Digest32,
    pub current_model_profile_digest: Digest32,
    pub current_source_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn exercise_portfolio_v1<A: PromptCandidateSourceAuthenticatorV1>(
    candidate_set: &PromptCandidateSetReceiptV1,
    pricing: &PromptPricingReceiptV1,
    relations: &PromptRelationSourceV1,
    portfolio: &PromptPortfolioReceiptV1,
    request: PromptExerciseRequestV1,
    authenticator: &A,
) -> Result<PromptExerciseDecisionV1, PromptExerciseErrorV1> {
    portfolio.validate_for(candidate_set, pricing, relations, request.now_unix_ms)?;
    require_digest(request.current_state_digest, "current state")?;
    request.current_source.validate_at(request.now_unix_ms)?;
    authenticator
        .authenticate_candidate_source(
            &request.current_source,
            portfolio.objective_digest,
            request.now_unix_ms,
        )
        .map_err(|_| PromptExerciseErrorV1::SourceAuthenticationRejected)?;

    let disposition = expected_disposition(candidate_set, portfolio, &request);
    let mut receipt = PromptExerciseDecisionV1 {
        exercise_id: request.exercise_id.clone(),
        portfolio_receipt_digest: portfolio.receipt_digest,
        boundary: request.boundary,
        disposition,
        selected_candidate_ids: portfolio.selected_candidate_ids.clone(),
        current_state_digest: request.current_state_digest,
        current_registry_snapshot_digest: request.current_source.registry_snapshot_digest,
        current_registry_revision: request.current_source.registry_revision,
        current_revocation_frontier: request.current_source.revocation_frontier,
        current_generation_vector_digest: request.current_source.generation_vector_digest,
        current_model_profile_digest: request.current_source.model_profile.digest(),
        current_source_digest: request.current_source.source_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = compute_receipt_digest(&receipt);
    receipt.validate_for(candidate_set, pricing, relations, portfolio, &request)?;
    Ok(receipt)
}

impl PromptExerciseDecisionV1 {
    pub fn validate_for(
        &self,
        candidate_set: &PromptCandidateSetReceiptV1,
        pricing: &PromptPricingReceiptV1,
        relations: &PromptRelationSourceV1,
        portfolio: &PromptPortfolioReceiptV1,
        request: &PromptExerciseRequestV1,
    ) -> Result<(), PromptExerciseErrorV1> {
        portfolio.validate_for(candidate_set, pricing, relations, request.now_unix_ms)?;
        require_digest(request.current_state_digest, "current state")?;
        request.current_source.validate_at(request.now_unix_ms)?;
        if self.authority.grants_any()
            || self.portfolio_receipt_digest != portfolio.receipt_digest
            || self.boundary != request.boundary
            || self.selected_candidate_ids != portfolio.selected_candidate_ids
            || self.current_state_digest != request.current_state_digest
            || self.current_registry_snapshot_digest
                != request.current_source.registry_snapshot_digest
            || self.current_registry_revision != request.current_source.registry_revision
            || self.current_revocation_frontier != request.current_source.revocation_frontier
            || self.current_generation_vector_digest
                != request.current_source.generation_vector_digest
            || self.current_model_profile_digest != request.current_source.model_profile.digest()
            || self.current_source_digest != request.current_source.source_digest
            || self.disposition != expected_disposition(candidate_set, portfolio, request)
        {
            return Err(PromptExerciseErrorV1::InvalidReceipt);
        }
        require_digest(self.receipt_digest, "exercise receipt")?;
        if self.receipt_digest != compute_receipt_digest(self) {
            return Err(PromptExerciseErrorV1::DigestMismatch("exercise receipt"));
        }
        Ok(())
    }
}

fn expected_disposition(
    candidate_set: &PromptCandidateSetReceiptV1,
    portfolio: &PromptPortfolioReceiptV1,
    request: &PromptExerciseRequestV1,
) -> PromptExerciseDispositionV1 {
    if request.current_state_digest != portfolio.state_digest {
        return PromptExerciseDispositionV1::Invalidated(
            PromptExerciseInvalidationV1::StateDrift,
        );
    }
    if request.current_source.model_profile.digest() != portfolio.model_profile_digest {
        return PromptExerciseDispositionV1::Invalidated(
            PromptExerciseInvalidationV1::ModelProfileDrift,
        );
    }
    if portfolio.selected_candidate_ids.is_empty() {
        return PromptExerciseDispositionV1::NoIntervention;
    }
    let original = candidate_set
        .candidates
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate.binding_digest))
        .collect::<BTreeMap<_, _>>();
    let current = request
        .current_source
        .bindings
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate.binding_digest))
        .collect::<BTreeMap<_, _>>();
    for candidate_id in &portfolio.selected_candidate_ids {
        let Some(current_digest) = current.get(candidate_id) else {
            return PromptExerciseDispositionV1::Invalidated(
                PromptExerciseInvalidationV1::SelectedCandidateUnavailable,
            );
        };
        if original.get(candidate_id) != Some(current_digest) {
            return PromptExerciseDispositionV1::Invalidated(
                PromptExerciseInvalidationV1::SelectedBindingDrift,
            );
        }
    }
    PromptExerciseDispositionV1::ExercisePortfolio
}

fn compute_receipt_digest(receipt: &PromptExerciseDecisionV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-receipt.v1".to_vec();
    push_id(&mut bytes, &receipt.exercise_id);
    bytes.extend_from_slice(receipt.portfolio_receipt_digest.as_array());
    bytes.push(boundary_code(receipt.boundary));
    bytes.push(disposition_code(receipt.disposition));
    push_len(&mut bytes, receipt.selected_candidate_ids.len());
    for candidate_id in &receipt.selected_candidate_ids {
        push_id(&mut bytes, candidate_id);
    }
    for digest in [
        receipt.current_state_digest,
        receipt.current_registry_snapshot_digest,
        receipt.current_generation_vector_digest,
        receipt.current_model_profile_digest,
        receipt.current_source_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.current_registry_revision.to_be_bytes());
    bytes.extend_from_slice(&receipt.current_revocation_frontier.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

const fn boundary_code(value: PromptExerciseBoundaryV1) -> u8 {
    match value {
        PromptExerciseBoundaryV1::RequestAccepted => 0,
        PromptExerciseBoundaryV1::ObjectiveCompiled => 1,
        PromptExerciseBoundaryV1::BeforePlanning => 2,
        PromptExerciseBoundaryV1::BeforeCandidateGeneration => 3,
        PromptExerciseBoundaryV1::BeforeModelOrToolDispatch => 4,
        PromptExerciseBoundaryV1::AfterObservation => 5,
        PromptExerciseBoundaryV1::AfterFailureOrUncertaintySpike => 6,
        PromptExerciseBoundaryV1::BeforeIrreversibleMutation => 7,
        PromptExerciseBoundaryV1::BeforeVerification => 8,
        PromptExerciseBoundaryV1::BeforeFinalResponse => 9,
        PromptExerciseBoundaryV1::BeforeCompactOrHandoff => 10,
    }
}

const fn disposition_code(value: PromptExerciseDispositionV1) -> u8 {
    match value {
        PromptExerciseDispositionV1::ExercisePortfolio => 0,
        PromptExerciseDispositionV1::NoIntervention => 1,
        PromptExerciseDispositionV1::Invalidated(reason) => 2 + invalidation_code(reason),
    }
}

const fn invalidation_code(value: PromptExerciseInvalidationV1) -> u8 {
    match value {
        PromptExerciseInvalidationV1::StateDrift => 0,
        PromptExerciseInvalidationV1::ModelProfileDrift => 1,
        PromptExerciseInvalidationV1::SelectedCandidateUnavailable => 2,
        PromptExerciseInvalidationV1::SelectedBindingDrift => 3,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptExerciseErrorV1 {
    Canonical(CanonicalPromptErrorV1),
    Portfolio(PromptPortfolioErrorV1),
    SourceAuthenticationRejected,
    InvalidReceipt,
    DigestMismatch(&'static str),
}

impl From<CanonicalPromptErrorV1> for PromptExerciseErrorV1 {
    fn from(value: CanonicalPromptErrorV1) -> Self {
        Self::Canonical(value)
    }
}

impl From<PromptPortfolioErrorV1> for PromptExerciseErrorV1 {
    fn from(value: PromptPortfolioErrorV1) -> Self {
        Self::Portfolio(value)
    }
}

impl fmt::Display for PromptExerciseErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptExerciseErrorV1 {}

#[cfg(test)]
#[path = "exercise_v1_tests.rs"]
mod tests;
