//! Proposal checksums and structural consistency at the exercise boundary.
//!
//! These checks bind selected realizations to the proposal receipt. They do not
//! authenticate optimization evidence or grant provider execution authority.

use super::*;

impl SelectedPromptPortfolioV1 {
    /// Computes the complete proposal checksum, including the exact selections
    /// and owner source. This grants no authentication or execution authority.
    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.portfolio-receipt.v2".to_vec();
        push_id(&mut bytes, &self.receipt.portfolio_id);
        for digest in [
            self.registry_digest,
            self.receipt.candidate_set_digest,
            self.receipt.interaction_digest,
            self.pricing_set_digest,
            self.graph_generation_digest,
            self.objective_digest,
            self.state_digest,
            self.model_tuple.digest(),
            self.model_tuple_digest,
            self.generation_vector_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_ids(&mut bytes, &self.receipt.factor_ids);
        bytes.extend_from_slice(&self.receipt.expected_utility_q32.raw().to_be_bytes());
        bytes.extend_from_slice(&self.receipt.total_token_upper_bound.to_be_bytes());
        bytes.extend_from_slice(&self.receipt.valid_until_unix_ms.to_be_bytes());
        push_len(&mut bytes, self.selected.len());
        for selected in &self.selected {
            push_id(&mut bytes, &selected.factor_id);
            bytes.extend_from_slice(selected.realization.digest().as_array());
            bytes.extend_from_slice(selected.binding_digest.as_array());
        }
        bytes.push(match self.selection_method {
            PromptSelectionMethodV1::GreedyPrerequisiteBundleV1 => 0,
        });
        bytes.push(match self.optimality {
            PromptOptimalityDisclosureV1::HeuristicNoCertificate => 0,
        });
        Digest32::of_bytes(&bytes)
    }

    pub(super) fn has_consistent_selection(&self) -> bool {
        if self.selected.len() > MAX_CANONICAL_SELECTED_FACTORS
            || self.receipt.factor_ids.len() != self.selected.len()
            || self
                .receipt
                .factor_ids
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
            || self.model_tuple.validate().is_err()
            || self.model_tuple_digest != self.model_tuple.digest()
        {
            return false;
        }
        let mut total_tokens = 0_u32;
        for (factor_id, selected) in self.receipt.factor_ids.iter().zip(&self.selected) {
            if factor_id != &selected.factor_id
                || selected.factor_id != selected.realization.factor_id
                || selected.realization.validate().is_err()
                || selected.binding_digest != selected.realization.digest()
                || selected
                    .realization
                    .expires_unix_ms
                    .is_some_and(|expires| self.receipt.valid_until_unix_ms > expires)
            {
                return false;
            }
            let Some(next_total) = total_tokens.checked_add(selected.realization.token_cost) else {
                return false;
            };
            total_tokens = next_total;
        }
        total_tokens == self.receipt.total_token_upper_bound
            && u64::from(total_tokens) <= MAX_CANONICAL_TOKEN_BUDGET
    }
}
