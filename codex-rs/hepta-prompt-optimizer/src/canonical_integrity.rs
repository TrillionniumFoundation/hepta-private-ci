//! Retain the complete owner-produced semantics before the next owner consumes
//! a public compatibility DTO. Recomputed public hashes are not provenance.
//!
//! Snapshots are created only by the producing owner and share immutable Arc
//! storage across clones. Validation compares references without allocating or
//! changing any signed or persisted digest grammar. The producer's existing
//! candidate and selection limits bound the retained collections.

use std::sync::Arc;

use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct EnumeratedOriginalV1 {
    pub(super) registry_snapshot: PromptRegistrySnapshotV2,
    pub(super) model_tuple: PromptModelTupleV2,
    pub(super) generation_vector_digest: Digest32,
    pub(super) candidates_digest: Digest32,
    pub(super) canonical_order_digest: Digest32,
    pub(super) omitted_count: u32,
    pub(super) candidates: Vec<PromptCandidateBindingV1>,
    pub(super) receipt: PromptCandidateSetReceiptV1,
}

impl EnumeratedOriginalV1 {
    pub(super) fn admit(self) -> EnumeratedPromptCandidatesV1 {
        EnumeratedPromptCandidatesV1 {
            original: Arc::new(self.clone()),
            registry_snapshot: self.registry_snapshot,
            model_tuple: self.model_tuple,
            generation_vector_digest: self.generation_vector_digest,
            candidates_digest: self.candidates_digest,
            canonical_order_digest: self.canonical_order_digest,
            omitted_count: self.omitted_count,
            candidates: self.candidates,
            receipt: self.receipt,
        }
    }
}

impl EnumeratedPromptCandidatesV1 {
    pub(super) fn validate_original(&self) -> Result<(), CanonicalPromptError> {
        let original = &self.original;
        if self.registry_snapshot != original.registry_snapshot
            || self.model_tuple != original.model_tuple
            || self.generation_vector_digest != original.generation_vector_digest
            || self.candidates_digest != original.candidates_digest
            || self.canonical_order_digest != original.canonical_order_digest
            || self.omitted_count != original.omitted_count
            || self.candidates != original.candidates
            || self.receipt != original.receipt
        {
            return Err(CanonicalPromptError::OwnerOutputDrift("enumerated"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct PricedOriginalV1 {
    pub(super) candidates: EnumeratedPromptCandidatesV1,
    pub(super) completeness_digest: Digest32,
    pub(super) pricing_policy_digest: Digest32,
    pub(super) rows: Vec<PricedPromptCandidateV1>,
    pub(super) pricing_set_digest: Digest32,
    pub(super) authority: AuthorityPosture,
}

impl PricedOriginalV1 {
    pub(super) fn admit(self) -> PricedPromptCandidatesV1 {
        PricedPromptCandidatesV1 {
            original: Arc::new(self.clone()),
            candidates: self.candidates,
            completeness_digest: self.completeness_digest,
            pricing_policy_digest: self.pricing_policy_digest,
            rows: self.rows,
            pricing_set_digest: self.pricing_set_digest,
            authority: self.authority,
        }
    }
}

impl PricedPromptCandidatesV1 {
    pub(super) fn validate_original(&self) -> Result<(), CanonicalPromptError> {
        self.candidates.validate_original()?;
        let original = &self.original;
        if self.candidates != original.candidates
            || self.completeness_digest != original.completeness_digest
            || self.pricing_policy_digest != original.pricing_policy_digest
            || self.rows != original.rows
            || self.pricing_set_digest != original.pricing_set_digest
            || self.authority != original.authority
        {
            return Err(CanonicalPromptError::OwnerOutputDrift("priced"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct SelectedOriginalV1 {
    pub(super) receipt: PromptPortfolioReceiptV1,
    pub(super) selected: Vec<PromptCandidateBindingV1>,
    pub(super) objective_digest: Digest32,
    pub(super) state_digest: Digest32,
    pub(super) model_tuple: PromptModelTupleV2,
    pub(super) model_tuple_digest: Digest32,
    pub(super) generation_vector_digest: Digest32,
    pub(super) pricing_set_digest: Digest32,
    pub(super) graph_generation_digest: Digest32,
    pub(super) selection_method: PromptSelectionMethodV1,
    pub(super) optimality: PromptOptimalityDisclosureV1,
}

impl SelectedOriginalV1 {
    pub(super) fn admit(self) -> SelectedPromptPortfolioV1 {
        SelectedPromptPortfolioV1 {
            original: Arc::new(self.clone()),
            receipt: self.receipt,
            selected: self.selected,
            objective_digest: self.objective_digest,
            state_digest: self.state_digest,
            model_tuple: self.model_tuple,
            model_tuple_digest: self.model_tuple_digest,
            generation_vector_digest: self.generation_vector_digest,
            pricing_set_digest: self.pricing_set_digest,
            graph_generation_digest: self.graph_generation_digest,
            selection_method: self.selection_method,
            optimality: self.optimality,
        }
    }
}

impl SelectedPromptPortfolioV1 {
    pub(super) fn validate_original(&self) -> Result<(), CanonicalPromptError> {
        let original = &self.original;
        if self.receipt != original.receipt
            || self.selected != original.selected
            || self.objective_digest != original.objective_digest
            || self.state_digest != original.state_digest
            || self.model_tuple != original.model_tuple
            || self.model_tuple_digest != original.model_tuple_digest
            || self.generation_vector_digest != original.generation_vector_digest
            || self.pricing_set_digest != original.pricing_set_digest
            || self.graph_generation_digest != original.graph_generation_digest
            || self.selection_method != original.selection_method
            || self.optimality != original.optimality
        {
            return Err(CanonicalPromptError::OwnerOutputDrift("selected"));
        }
        Ok(())
    }
}
