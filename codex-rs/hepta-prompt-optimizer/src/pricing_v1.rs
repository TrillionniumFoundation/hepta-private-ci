//! Evidence-qualified prompt-factor pricing over an enumerated candidate set.

use std::collections::BTreeMap;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::canonical_v1::CanonicalPromptErrorV1;
use crate::canonical_v1::PromptAuthenticationErrorV1;
use crate::canonical_v1::PromptCandidateBindingV1;
use crate::canonical_v1::PromptCandidateSetReceiptV1;
use crate::canonical_v1::push_id;
use crate::canonical_v1::push_len;
use crate::canonical_v1::require_digest;

/// Authenticates causal/cost evidence used to price a prompt candidate.
///
/// Implementations are expected to bind an independent evaluator or other
/// registered evidence owner to the exact `evidence_digest` and objective.
pub trait PromptPricingEvidenceAuthenticatorV1 {
    fn authenticate_pricing_evidence(
        &self,
        evidence: &PromptPricingEvidenceV1,
        now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PromptCostBreakdownV1 {
    pub tokens: FixedQ32,
    pub latency: FixedQ32,
    pub context_crowding: FixedQ32,
    pub instruction_interference: FixedQ32,
    pub privacy: FixedQ32,
    pub instability: FixedQ32,
    pub future_context_option_value: FixedQ32,
}

impl PromptCostBreakdownV1 {
    pub fn total(self) -> Result<FixedQ32, CanonicalPromptErrorV1> {
        let values = self.values();
        if values.into_iter().any(|value| value < FixedQ32::ZERO) {
            return Err(CanonicalPromptErrorV1::NegativeCost);
        }
        values.into_iter().try_fold(FixedQ32::ZERO, |sum, value| {
            sum.checked_add(value)
                .map_err(|_| CanonicalPromptErrorV1::Arithmetic)
        })
    }

    const fn values(self) -> [FixedQ32; 7] {
        [
            self.tokens,
            self.latency,
            self.context_crowding,
            self.instruction_interference,
            self.privacy,
            self.instability,
            self.future_context_option_value,
        ]
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingEvidenceV1 {
    pub candidate_id: StableId,
    pub candidate_binding_digest: Digest32,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub causal_incremental_utility: FixedQ32,
    pub confidence: FixedQ32,
    pub costs: PromptCostBreakdownV1,
    pub utility_unit_digest: Digest32,
    pub cost_profile_digest: Digest32,
    pub support_digest: Digest32,
    pub valid_until_unix_ms: u64,
    pub evidence_digest: Digest32,
}

impl PromptPricingEvidenceV1 {
    #[must_use]
    pub fn compute_evidence_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.v1".to_vec();
        push_id(&mut bytes, &self.candidate_id);
        for digest in [
            self.candidate_binding_digest,
            self.objective_digest,
            self.state_digest,
            self.model_profile_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.causal_incremental_utility.raw().to_be_bytes());
        bytes.extend_from_slice(&self.confidence.raw().to_be_bytes());
        for cost in self.costs.values() {
            bytes.extend_from_slice(&cost.raw().to_be_bytes());
        }
        bytes.extend_from_slice(self.utility_unit_digest.as_array());
        bytes.extend_from_slice(self.cost_profile_digest.as_array());
        bytes.extend_from_slice(self.support_digest.as_array());
        bytes.extend_from_slice(&self.valid_until_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPriceAvailabilityV1 {
    Available,
    MissingEvidence,
    ExpiredEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPriceV1 {
    pub candidate_id: StableId,
    pub gross_utility: FixedQ32,
    pub total_cost: FixedQ32,
    pub net_utility: FixedQ32,
    pub confidence: FixedQ32,
    pub availability: PromptPriceAvailabilityV1,
    pub evidence_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub candidate_set_receipt_digest: Digest32,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub prices: Vec<PromptPriceV1>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptPricingReceiptV1 {
    pub fn validate_for(
        &self,
        candidate_set: &PromptCandidateSetReceiptV1,
        now_unix_ms: u64,
    ) -> Result<(), CanonicalPromptErrorV1> {
        candidate_set.validate(now_unix_ms)?;
        if self.authority.grants_any()
            || self.candidate_set_receipt_digest != candidate_set.receipt_digest
            || self.objective_digest != candidate_set.objective_digest
            || self.state_digest != candidate_set.state_digest
            || self.model_profile_digest != candidate_set.model_profile_digest
            || self.prices.len() != candidate_set.candidates.len()
        {
            return Err(CanonicalPromptErrorV1::InvalidReceipt);
        }
        let expected_ids = candidate_set
            .candidates
            .iter()
            .map(|candidate| &candidate.candidate_id);
        if self
            .prices
            .iter()
            .map(|price| &price.candidate_id)
            .ne(expected_ids)
        {
            return Err(CanonicalPromptErrorV1::InvalidReceipt);
        }
        for price in &self.prices {
            validate_price(price)?;
        }
        require_digest(self.receipt_digest, "pricing receipt")?;
        if self.receipt_digest != compute_pricing_receipt_digest(self) {
            return Err(CanonicalPromptErrorV1::DigestMismatch("pricing receipt"));
        }
        Ok(())
    }
}

pub fn price_factors_v1<A: PromptPricingEvidenceAuthenticatorV1>(
    candidate_set: &PromptCandidateSetReceiptV1,
    evidence: Vec<PromptPricingEvidenceV1>,
    now_unix_ms: u64,
    authenticator: &A,
) -> Result<PromptPricingReceiptV1, CanonicalPromptErrorV1> {
    candidate_set.validate(now_unix_ms)?;
    let binding_by_id = candidate_set
        .candidates
        .iter()
        .map(|binding| (binding.candidate_id.clone(), binding))
        .collect::<BTreeMap<_, _>>();
    let mut evidence_by_id = BTreeMap::new();
    for item in evidence {
        let Some(binding) = binding_by_id.get(&item.candidate_id) else {
            return Err(CanonicalPromptErrorV1::UnknownCandidate(
                item.candidate_id.to_string(),
            ));
        };
        validate_pricing_evidence(candidate_set, binding, &item)?;
        authenticator
            .authenticate_pricing_evidence(&item, now_unix_ms)
            .map_err(|_| CanonicalPromptErrorV1::PricingAuthenticationRejected)?;
        let item_id = item.candidate_id.clone();
        if evidence_by_id.insert(item_id.clone(), item).is_some() {
            return Err(CanonicalPromptErrorV1::DuplicateEvidence(item_id.to_string()));
        }
    }

    let mut prices = Vec::with_capacity(candidate_set.candidates.len());
    for binding in &candidate_set.candidates {
        let Some(item) = evidence_by_id.get(&binding.candidate_id) else {
            prices.push(unavailable_price(
                binding.candidate_id.clone(),
                PromptPriceAvailabilityV1::MissingEvidence,
                None,
            ));
            continue;
        };
        if now_unix_ms >= item.valid_until_unix_ms {
            prices.push(unavailable_price(
                binding.candidate_id.clone(),
                PromptPriceAvailabilityV1::ExpiredEvidence,
                Some(item.evidence_digest),
            ));
            continue;
        }
        let total_cost = item.costs.total()?;
        let net_utility = item
            .causal_incremental_utility
            .checked_sub(total_cost)
            .map_err(|_| CanonicalPromptErrorV1::Arithmetic)?;
        prices.push(PromptPriceV1 {
            candidate_id: binding.candidate_id.clone(),
            gross_utility: item.causal_incremental_utility,
            total_cost,
            net_utility,
            confidence: item.confidence,
            availability: PromptPriceAvailabilityV1::Available,
            evidence_digest: Some(item.evidence_digest),
        });
    }
    let mut receipt = PromptPricingReceiptV1 {
        candidate_set_receipt_digest: candidate_set.receipt_digest,
        objective_digest: candidate_set.objective_digest,
        state_digest: candidate_set.state_digest,
        model_profile_digest: candidate_set.model_profile_digest,
        prices,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = compute_pricing_receipt_digest(&receipt);
    receipt.validate_for(candidate_set, now_unix_ms)?;
    Ok(receipt)
}

fn validate_pricing_evidence(
    candidate_set: &PromptCandidateSetReceiptV1,
    binding: &PromptCandidateBindingV1,
    evidence: &PromptPricingEvidenceV1,
) -> Result<(), CanonicalPromptErrorV1> {
    for (label, digest) in [
        ("pricing candidate binding", evidence.candidate_binding_digest),
        ("pricing objective", evidence.objective_digest),
        ("pricing state", evidence.state_digest),
        ("pricing model profile", evidence.model_profile_digest),
        ("pricing utility unit", evidence.utility_unit_digest),
        ("pricing cost profile", evidence.cost_profile_digest),
        ("pricing support", evidence.support_digest),
        ("pricing evidence", evidence.evidence_digest),
    ] {
        require_digest(digest, label)?;
    }
    if evidence.candidate_binding_digest != binding.binding_digest
        || evidence.objective_digest != candidate_set.objective_digest
        || evidence.state_digest != candidate_set.state_digest
        || evidence.model_profile_digest != candidate_set.model_profile_digest
    {
        return Err(CanonicalPromptErrorV1::EvidenceContextMismatch(
            binding.candidate_id.to_string(),
        ));
    }
    if evidence.confidence <= FixedQ32::ZERO || evidence.confidence > FixedQ32::ONE {
        return Err(CanonicalPromptErrorV1::InvalidConfidence(
            binding.candidate_id.to_string(),
        ));
    }
    if evidence.valid_until_unix_ms == 0 {
        return Err(CanonicalPromptErrorV1::InvalidEvidenceWindow(
            binding.candidate_id.to_string(),
        ));
    }
    evidence.costs.total()?;
    if evidence.evidence_digest != evidence.compute_evidence_digest() {
        return Err(CanonicalPromptErrorV1::DigestMismatch("pricing evidence"));
    }
    Ok(())
}

fn validate_price(price: &PromptPriceV1) -> Result<(), CanonicalPromptErrorV1> {
    match price.availability {
        PromptPriceAvailabilityV1::Available => {
            let Some(evidence_digest) = price.evidence_digest else {
                return Err(CanonicalPromptErrorV1::InvalidReceipt);
            };
            require_digest(evidence_digest, "pricing evidence reference")?;
            if price.total_cost < FixedQ32::ZERO
                || price.confidence <= FixedQ32::ZERO
                || price.confidence > FixedQ32::ONE
                || price
                    .gross_utility
                    .checked_sub(price.total_cost)
                    .map_err(|_| CanonicalPromptErrorV1::Arithmetic)?
                    != price.net_utility
            {
                return Err(CanonicalPromptErrorV1::InvalidReceipt);
            }
        }
        PromptPriceAvailabilityV1::MissingEvidence => {
            if price.evidence_digest.is_some() || !price_is_zero(price) {
                return Err(CanonicalPromptErrorV1::InvalidReceipt);
            }
        }
        PromptPriceAvailabilityV1::ExpiredEvidence => {
            let Some(evidence_digest) = price.evidence_digest else {
                return Err(CanonicalPromptErrorV1::InvalidReceipt);
            };
            require_digest(evidence_digest, "expired pricing evidence reference")?;
            if !price_is_zero(price) {
                return Err(CanonicalPromptErrorV1::InvalidReceipt);
            }
        }
    }
    Ok(())
}

fn price_is_zero(price: &PromptPriceV1) -> bool {
    price.gross_utility == FixedQ32::ZERO
        && price.total_cost == FixedQ32::ZERO
        && price.net_utility == FixedQ32::ZERO
        && price.confidence == FixedQ32::ZERO
}

fn unavailable_price(
    candidate_id: StableId,
    availability: PromptPriceAvailabilityV1,
    evidence_digest: Option<Digest32>,
) -> PromptPriceV1 {
    PromptPriceV1 {
        candidate_id,
        gross_utility: FixedQ32::ZERO,
        total_cost: FixedQ32::ZERO,
        net_utility: FixedQ32::ZERO,
        confidence: FixedQ32::ZERO,
        availability,
        evidence_digest,
    }
}

fn compute_pricing_receipt_digest(receipt: &PromptPricingReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-receipt.v1".to_vec();
    for digest in [
        receipt.candidate_set_receipt_digest,
        receipt.objective_digest,
        receipt.state_digest,
        receipt.model_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, receipt.prices.len());
    for price in &receipt.prices {
        push_id(&mut bytes, &price.candidate_id);
        for value in [
            price.gross_utility,
            price.total_cost,
            price.net_utility,
            price.confidence,
        ] {
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        bytes.push(match price.availability {
            PromptPriceAvailabilityV1::Available => 0,
            PromptPriceAvailabilityV1::MissingEvidence => 1,
            PromptPriceAvailabilityV1::ExpiredEvidence => 2,
        });
        match price.evidence_digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "pricing_v1_tests.rs"]
mod tests;
