//! Private seals preserving authenticated enumeration and pricing inputs.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use super::CanonicalPromptError;
use super::EnumeratedPromptCandidatesV1;
use super::LearningEvidenceRoleV1;
use super::MAX_CANONICAL_PROMPT_FACTORS;
use super::PricedPromptCandidatesV1;
use super::PromptCandidateBindingV1;
use super::PromptPricingAdmissionProofV1;
use super::digest_candidate_order;
use super::digest_candidate_receipt;
use super::digest_candidates;
use super::digest_pricing_receipt;
use super::digest_pricing_set;
use super::push_id;
use super::push_ids;
use super::push_len;

impl EnumeratedPromptCandidatesV1 {
    /// Verifies the exact owner-issued candidate contents and receipt before
    /// authenticated pricing or selection consumes this enumeration.
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        if self.registry_snapshot != self.issued_registry_snapshot {
            return Err(CanonicalPromptError::CandidateOwnerBindingMismatch);
        }
        if self.candidates.len() > MAX_CANONICAL_PROMPT_FACTORS
            || self.receipt.candidate_factor_ids.len() > MAX_CANONICAL_PROMPT_FACTORS
        {
            return Err(CanonicalPromptError::CandidateLimit);
        }
        if self.receipt.authority.grants_any()
            || self.model_tuple.validate().is_err()
            || self.registry_snapshot.validate().is_err()
            || self.issued_registry_snapshot.validate().is_err()
            || self.receipt.registry_digest != self.registry_snapshot.registry_digest
            || self.generation_vector_digest != self.registry_snapshot.generation_vector_digest
            || self.model_tuple.digest() != self.registry_snapshot.model_tuple_digest
            || self.receipt.candidate_factor_ids.len() != self.candidates.len()
            || self.candidates.windows(2).any(|pair| pair[0].factor_id >= pair[1].factor_id)
            || self.candidates.iter().zip(&self.receipt.candidate_factor_ids).any(|(binding, factor)| {
                &binding.factor_id != factor
                    || binding.factor_id != binding.realization.factor_id
                    || binding.realization.validate().is_err()
                    || binding.realization.digest() != binding.binding_digest
            })
            || self.candidates_digest != digest_candidates(&self.candidates)
            || self.canonical_order_digest != digest_candidate_order(&self.candidates)
            || self.receipt.receipt_digest != digest_candidate_receipt(
                &self.receipt.set_id,
                self.receipt.objective_digest,
                self.receipt.state_digest,
                self.receipt.registry_digest,
                self.registry_snapshot.snapshot_digest,
                self.model_tuple.digest(),
                self.receipt.selection_grammar_digest,
                &self.receipt.candidate_factor_ids,
                self.candidates_digest,
                self.canonical_order_digest,
                self.omitted_count,
            )
            || self.sealed_input_digest != self.compute_input_digest()
        {
            return Err(CanonicalPromptError::CandidateBindingMismatch);
        }
        Ok(())
    }

    pub(super) fn compute_input_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.enumerated-input-seal.v1".to_vec();
        for snapshot in [&self.registry_snapshot, &self.issued_registry_snapshot] {
            bytes.extend_from_slice(snapshot.compute_snapshot_digest().as_array());
            bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
            bytes.push(u8::from(snapshot.authority.grants_any()));
        }
        for digest in [
            self.model_tuple.digest(),
            self.generation_vector_digest,
            self.candidates_digest,
            self.canonical_order_digest,
            self.factor_graph_source_digest,
            self.receipt.objective_digest,
            self.receipt.state_digest,
            self.receipt.registry_digest,
            self.receipt.selection_grammar_digest,
            self.receipt.receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.omitted_count.to_be_bytes());
        push_id(&mut bytes, &self.receipt.set_id);
        push_ids(&mut bytes, &self.receipt.candidate_factor_ids);
        bytes.push(u8::from(self.receipt.authority.grants_any()));
        push_len(&mut bytes, self.candidates.len());
        for binding in &self.candidates {
            write_binding(&mut bytes, binding);
        }
        Digest32::of_bytes(&bytes)
    }
}

impl PricedPromptCandidatesV1 {
    /// Verifies authenticated pricing, accounting, admission proofs and row
    /// order against the exact enumeration before selection consumes them.
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        if self.rows.len() > MAX_CANONICAL_PROMPT_FACTORS
            || self.admission_proofs.len() > MAX_CANONICAL_PROMPT_FACTORS + 1
        {
            return Err(CanonicalPromptError::CandidateLimit);
        }
        self.candidates.validate()?;
        if self.authority.grants_any()
            || self.rows.len() != self.candidates.candidates.len()
            || self.admission_proofs.len() != self.rows.len() + 1
            || self.admission_trust_digest.is_zero()
            || self.admitted_at_unix_ms == 0
            || self.admission_expires_at_unix_ms != self.admission_proofs.iter().map(|proof| proof.evidence.expires_at).min().unwrap_or(0)
            || self.admission_proofs.iter().enumerate().any(|(index, proof)| {
                let expected_role = if index == 0 { LearningEvidenceRoleV1::Generator } else { LearningEvidenceRoleV1::Evaluator };
                proof.role != expected_role
                    || proof.evidence.role != proof.role
                    || proof.evidence.trust_digest != self.admission_trust_digest
                    || proof.evidence.objective_digest != self.candidates.receipt.objective_digest
                    || self.admitted_at_unix_ms < proof.evidence.issued_at
                    || self.admitted_at_unix_ms > proof.evidence.expires_at
                    || Digest32::of_bytes(&proof.payload) != proof.evidence.payload_digest
            })
            || self.rows.iter().zip(&self.candidates.candidates).any(|(row, candidate)| {
                let pricing = &row.pricing;
                row.binding != *candidate
                    || pricing.authority.grants_any()
                    || pricing.factor_id != candidate.factor_id
                    || pricing.state_digest != self.candidates.receipt.state_digest
                    || pricing.token_cost != candidate.realization.token_cost
                    || pricing.expected_utility_q32 != row.net_utility_q32
                    || pricing.downside_q32 < FixedQ32::ZERO
                    || pricing.interference_ppm > 1_000_000
                    || pricing.confidence_interval.lower_q32 > pricing.confidence_interval.upper_q32
                    || pricing.confidence_interval.support_count == 0
                    || pricing.confidence_interval.support_audit_digest.is_zero()
                    || pricing.receipt_digest != digest_pricing_receipt(
                        &pricing.factor_id,
                        pricing.state_digest,
                        pricing.expected_utility_q32,
                        pricing.downside_q32,
                        pricing.token_cost,
                        pricing.latency_cost_micros,
                        pricing.interference_ppm,
                        &pricing.confidence_interval,
                        self.pricing_policy_digest,
                        candidate.binding_digest,
                    )
            })
            || self.pricing_set_digest != digest_pricing_set(&self.rows, self.pricing_policy_digest)
            || self.sealed_input_digest != self.compute_input_digest()
        {
            return Err(CanonicalPromptError::PricingBindingMismatch);
        }
        Ok(())
    }

    pub(super) fn compute_input_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.priced-input-seal.v1".to_vec();
        for digest in [
            self.candidates.compute_input_digest(),
            self.completeness_digest,
            self.pricing_policy_digest,
            self.pricing_set_digest,
            self.admission_trust_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.admitted_at_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.admission_expires_at_unix_ms.to_be_bytes());
        push_len(&mut bytes, self.admission_proofs.len());
        for proof in &self.admission_proofs {
            bytes.push(match proof.role {
                LearningEvidenceRoleV1::Generator => 0,
                LearningEvidenceRoleV1::Observer => 1,
                LearningEvidenceRoleV1::Evaluator => 2,
                LearningEvidenceRoleV1::CreditAllocator => 3,
                LearningEvidenceRoleV1::UnlearningAuthority => 4,
                LearningEvidenceRoleV1::Selector => 5,
            });
            let signing_bytes = proof.evidence.signing_bytes();
            push_len(&mut bytes, signing_bytes.len());
            bytes.extend_from_slice(&signing_bytes);
            bytes.extend_from_slice(&proof.evidence.signature);
            push_len(&mut bytes, proof.payload.len());
            bytes.extend_from_slice(Digest32::of_bytes(&proof.payload).as_array());
        }
        bytes.push(u8::from(self.authority.grants_any()));
        push_len(&mut bytes, self.rows.len());
        for row in &self.rows {
            write_binding(&mut bytes, &row.binding);
            let pricing = &row.pricing;
            push_id(&mut bytes, &pricing.factor_id);
            for digest in [pricing.state_digest, pricing.receipt_digest, pricing.confidence_interval.support_audit_digest] {
                bytes.extend_from_slice(digest.as_array());
            }
            for value in [pricing.expected_utility_q32, pricing.downside_q32, pricing.confidence_interval.lower_q32, pricing.confidence_interval.upper_q32, row.net_utility_q32] {
                bytes.extend_from_slice(&value.raw().to_be_bytes());
            }
            bytes.extend_from_slice(&pricing.token_cost.to_be_bytes());
            bytes.extend_from_slice(&pricing.latency_cost_micros.to_be_bytes());
            bytes.extend_from_slice(&pricing.interference_ppm.to_be_bytes());
            bytes.extend_from_slice(&pricing.confidence_interval.support_count.to_be_bytes());
            bytes.push(u8::from(pricing.authority.grants_any()));
        }
        Digest32::of_bytes(&bytes)
    }
}

fn write_binding(bytes: &mut Vec<u8>, binding: &PromptCandidateBindingV1) {
    push_id(bytes, &binding.factor_id);
    bytes.extend_from_slice(binding.binding_digest.as_array());
    bytes.extend_from_slice(binding.realization.digest().as_array());
}

pub(super) fn verify_pricing_admission(
    proofs: &[PromptPricingAdmissionProofV1],
    verifier: &LearningEvidenceVerifierV1,
    now_unix_ms: u64,
) -> Result<VerifiedLearningEvidenceV1, CanonicalPromptError> {
    let first = proofs.first().ok_or(CanonicalPromptError::PricingBindingMismatch)?;
    let generator = verifier.verify(first.role, &first.evidence, &first.payload, now_unix_ms)
        .map_err(|e| CanonicalPromptError::LearningEvidence(format!("{e:?}")))?;
    for proof in &proofs[1..] {
        let evaluator = verifier.verify(proof.role, &proof.evidence, &proof.payload, now_unix_ms)
            .map_err(|e| CanonicalPromptError::LearningEvidence(format!("{e:?}")))?;
        verify_signed_role_separation(&generator, &evaluator, now_unix_ms)
            .map_err(|e| CanonicalPromptError::LearningEvidence(format!("{e:?}")))?;
    }
    Ok(generator)
}

