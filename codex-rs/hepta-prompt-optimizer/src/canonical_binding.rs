//! Private seals connecting owner-issued candidate cuts and selected outputs.

use codex_hepta_types::Digest32;

use super::CanonicalPromptError;
use super::MAX_CANONICAL_SELECTED_FACTORS;
use super::PromptOptimalityDisclosureV1;
use super::PromptSelectionMethodV1;
use super::SelectedPromptPortfolioV1;
use super::push_id;
use super::push_ids;
use super::push_len;

impl SelectedPromptPortfolioV1 {
    /// Checks that selection, realization content, receipts and graph binding
    /// still match the result sealed by canonical portfolio selection.
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        if self.selected.len() > MAX_CANONICAL_SELECTED_FACTORS
            || self.selected_at_unix_ms == 0
            || self.receipt.factor_ids.len() > MAX_CANONICAL_SELECTED_FACTORS
            || self.receipt.authority.grants_any()
            || self.model_tuple.validate().is_err()
            || self.registry_snapshot.validate().is_err()
            || self
                .selected
                .iter()
                .any(|binding| binding.realization.validate().is_err())
            || self.sealed_output_digest != self.compute_output_digest()
        {
            return Err(CanonicalPromptError::PortfolioBindingMismatch);
        }
        Ok(())
    }

    pub(super) fn compute_output_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.canonical-selected-output.v1".to_vec();
        push_id(&mut bytes, &self.receipt.portfolio_id);
        push_ids(&mut bytes, &self.receipt.factor_ids);
        bytes.extend_from_slice(self.receipt.candidate_set_digest.as_array());
        bytes.extend_from_slice(self.receipt.interaction_digest.as_array());
        bytes.extend_from_slice(&self.receipt.expected_utility_q32.raw().to_be_bytes());
        bytes.extend_from_slice(&self.receipt.total_token_upper_bound.to_be_bytes());
        bytes.extend_from_slice(&self.receipt.valid_until_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.selected_at_unix_ms.to_be_bytes());
        bytes.extend_from_slice(self.receipt.receipt_digest.as_array());
        push_len(&mut bytes, self.selected.len());
        for binding in &self.selected {
            push_id(&mut bytes, &binding.factor_id);
            bytes.extend_from_slice(binding.binding_digest.as_array());
            bytes.extend_from_slice(binding.realization.digest().as_array());
        }
        for digest in [
            self.objective_digest,
            self.state_digest,
            self.model_tuple.digest(),
            self.model_tuple_digest,
            self.generation_vector_digest,
            self.pricing_set_digest,
            self.graph_generation_digest,
            self.registry_snapshot.snapshot_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(match self.selection_method {
            PromptSelectionMethodV1::GreedyPrerequisiteBundleV1 => 0,
        });
        bytes.push(match self.optimality {
            PromptOptimalityDisclosureV1::HeuristicNoCertificate => 0,
        });
        Digest32::of_bytes(&bytes)
    }
}
