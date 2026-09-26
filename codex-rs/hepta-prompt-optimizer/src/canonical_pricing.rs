use std::collections::BTreeSet;
use std::ops::Deref;

use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::enumeration::VerifiedEnumeratedPromptCandidatesV1;
use super::enumeration::verify_raw_enumerated_v1;
use super::error::CanonicalPromptError;
use super::error::ensure_digest;
use super::error::push_id;
use super::raw;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingEvidenceV1 {
    pub factor_id: StableId,
    pub candidate_set_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub realization_id: StableId,
    pub realization_binding_digest: Digest32,
    pub objective_digest: Digest32,
    pub scope_digest: Digest32,
    pub state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub pricing_policy_digest: Digest32,
    pub expected_incremental_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub support_count: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub context_crowding_cost_q32: FixedQ32,
    pub privacy_cost_q32: FixedQ32,
    pub instability_cost_q32: FixedQ32,
    pub future_context_option_cost_q32: FixedQ32,
    pub source_support_audit_digest: Digest32,
    pub evidence: SignedLearningEvidenceV1,
}

impl PromptPricingEvidenceV1 {
    fn bound_support_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.pricing-context.v2".to_vec();
        push_id(&mut bytes, &self.factor_id);
        push_id(&mut bytes, &self.realization_id);
        for digest in [
            self.candidate_set_digest,
            self.registry_snapshot_digest,
            self.generation_vector_digest,
            self.realization_binding_digest,
            self.objective_digest,
            self.scope_digest,
            self.pricing_policy_digest,
            self.source_support_audit_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    fn to_raw(&self) -> raw::PromptPricingEvidenceV1 {
        raw::PromptPricingEvidenceV1 {
            factor_id: self.factor_id.clone(),
            state_digest: self.state_digest,
            model_tuple_digest: self.model_tuple_digest,
            expected_incremental_utility_q32: self.expected_incremental_utility_q32,
            downside_q32: self.downside_q32,
            confidence_lower_q32: self.confidence_lower_q32,
            confidence_upper_q32: self.confidence_upper_q32,
            support_count: self.support_count,
            latency_cost_micros: self.latency_cost_micros,
            interference_ppm: self.interference_ppm,
            context_crowding_cost_q32: self.context_crowding_cost_q32,
            privacy_cost_q32: self.privacy_cost_q32,
            instability_cost_q32: self.instability_cost_q32,
            future_context_option_cost_q32: self.future_context_option_cost_q32,
            support_audit_digest: self.bound_support_digest(),
            evidence: self.evidence.clone(),
        }
    }
}

pub fn pricing_evidence_signing_payload_v1(evidence: &PromptPricingEvidenceV1) -> Vec<u8> {
    raw::pricing_evidence_signing_payload_v1(&evidence.to_raw())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceProvenanceV1 {
    pub trust_digest: Digest32,
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
    pub generator_principal_id: StableId,
    pub generator_controller_id: StableId,
    pub issued_at_unix_ms: u64,
    pub valid_until_unix_ms: u64,
    pub provenance_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPricedPromptCandidatesV1 {
    raw: raw::PricedPromptCandidatesV1,
    enumeration_verification_digest: Digest32,
    provenance: EvidenceProvenanceV1,
    verification_digest: Digest32,
}

impl Deref for VerifiedPricedPromptCandidatesV1 {
    type Target = raw::PricedPromptCandidatesV1;

    fn deref(&self) -> &Self::Target {
        &self.raw
    }
}

impl VerifiedPricedPromptCandidatesV1 {
    pub fn provenance(&self) -> &EvidenceProvenanceV1 {
        &self.provenance
    }

    pub fn enumeration_verification_digest(&self) -> Digest32 {
        self.enumeration_verification_digest
    }

    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    pub(crate) fn as_raw(&self) -> &raw::PricedPromptCandidatesV1 {
        &self.raw
    }
}

#[allow(clippy::too_many_arguments)]
pub fn price_factors_v1(
    candidates: VerifiedEnumeratedPromptCandidatesV1,
    completeness: &CandidateSetCompletenessReceiptV1,
    completeness_evidence: &SignedLearningEvidenceV1,
    pricing_evidence: Vec<PromptPricingEvidenceV1>,
    verifier: &LearningEvidenceVerifierV1,
    policy: &raw::PromptPricingPolicyV1,
    now_unix_ms: u64,
) -> Result<VerifiedPricedPromptCandidatesV1, CanonicalPromptError> {
    if now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    if verifier.objective_digest() != candidates.receipt.objective_digest
        || verifier.scope_digest() != candidates.scope_digest()
    {
        return Err(CanonicalPromptError::EvidenceBinding(
            "verifier objective/scope does not match candidate set".to_owned(),
        ));
    }
    let policy_digest = policy.digest().map_err(CanonicalPromptError::from)?;
    let completeness_payload = raw::candidate_completeness_signing_payload_v1(completeness)
        .map_err(CanonicalPromptError::from)?;
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            completeness_evidence,
            &completeness_payload,
            now_unix_ms,
        )
        .map_err(|error| CanonicalPromptError::Unavailable(error.to_string()))?;

    validate_candidate_set_completeness(completeness)
        .map_err(|error| CanonicalPromptError::EvidenceBinding(error.to_string()))?;
    if completeness.candidates_digest != candidates.candidates_digest
        || completeness.canonical_order_digest != candidates.canonical_order_digest
        || completeness.state_digest != candidates.receipt.state_digest
        || completeness.grammar_digest != candidates.receipt.selection_grammar_digest
        || completeness.candidate_count
            != u32::try_from(candidates.candidates.len()).unwrap_or(u32::MAX)
        || completeness.omitted_count_bound < candidates.omitted_count
    {
        return Err(CanonicalPromptError::EvidenceBinding(
            "candidate completeness does not bind exact enumeration".to_owned(),
        ));
    }

    let by_factor = candidates
        .candidates
        .iter()
        .map(|candidate| (candidate.factor_id.clone(), candidate))
        .collect::<std::collections::BTreeMap<_, _>>();
    let mut seen = BTreeSet::new();
    let mut raw_evidence = Vec::with_capacity(pricing_evidence.len());
    let mut earliest_issued = completeness_evidence.issued_at;
    let mut valid_until = completeness_evidence.expires_at;
    for evidence in &pricing_evidence {
        let candidate = by_factor.get(&evidence.factor_id).ok_or_else(|| {
            CanonicalPromptError::EvidenceBinding(format!(
                "pricing evidence names unknown factor {}",
                evidence.factor_id
            ))
        })?;
        if !seen.insert(evidence.factor_id.clone())
            || evidence.candidate_set_digest != candidates.candidates_digest
            || evidence.registry_snapshot_digest != candidates.registry_snapshot.snapshot_digest
            || evidence.generation_vector_digest != candidates.generation_vector_digest
            || evidence.realization_id != candidate.realization.realization_id
            || evidence.realization_binding_digest != candidate.binding_digest
            || evidence.objective_digest != candidates.receipt.objective_digest
            || evidence.scope_digest != candidates.scope_digest()
            || evidence.state_digest != candidates.receipt.state_digest
            || evidence.model_tuple_digest != candidates.model_tuple.digest()
            || evidence.pricing_policy_digest != policy_digest
            || evidence.source_support_audit_digest.is_zero()
        {
            return Err(CanonicalPromptError::EvidenceBinding(format!(
                "pricing evidence context mismatch for {}",
                evidence.factor_id
            )));
        }
        let raw = evidence.to_raw();
        let payload = raw::pricing_evidence_signing_payload_v1(&raw);
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|error| CanonicalPromptError::Unavailable(error.to_string()))?;
        verify_signed_independent_roles_v1(&generator, &evaluator, now_unix_ms)
            .map_err(|error| CanonicalPromptError::EvidenceIndependence(error.to_string()))?;
        earliest_issued = earliest_issued.min(evidence.evidence.issued_at);
        valid_until = valid_until.min(evidence.evidence.expires_at);
        raw_evidence.push(raw);
    }
    if raw_evidence.len() != candidates.candidates.len() {
        return Err(CanonicalPromptError::Incomplete(
            "every enumerated factor requires authenticated pricing".to_owned(),
        ));
    }

    let enumeration_verification_digest = candidates.verification_digest();
    let raw = raw::price_factors_v1(
        candidates.into_raw(),
        completeness,
        completeness_evidence,
        raw_evidence,
        verifier,
        policy,
        now_unix_ms,
    )?;
    let provenance = EvidenceProvenanceV1 {
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        generator_principal_id: generator.principal().principal_id.clone(),
        generator_controller_id: generator.controller_id().clone(),
        issued_at_unix_ms: earliest_issued,
        valid_until_unix_ms: valid_until,
        provenance_digest: evidence_provenance_digest(
            verifier.trust_digest(),
            verifier.scope_digest(),
            verifier.objective_digest(),
            verifier.authority_epoch(),
            generator.principal().principal_id.clone(),
            generator.controller_id().clone(),
            earliest_issued,
            valid_until,
        ),
    };
    verify_priced(raw, enumeration_verification_digest, provenance)
}

pub(crate) fn verify_raw_priced_v1(
    raw: raw::PricedPromptCandidatesV1,
    enumeration_verification_digest: Digest32,
    provenance: EvidenceProvenanceV1,
) -> Result<VerifiedPricedPromptCandidatesV1, CanonicalPromptError> {
    verify_priced(raw, enumeration_verification_digest, provenance)
}

fn verify_priced(
    raw: raw::PricedPromptCandidatesV1,
    enumeration_verification_digest: Digest32,
    provenance: EvidenceProvenanceV1,
) -> Result<VerifiedPricedPromptCandidatesV1, CanonicalPromptError> {
    ensure_digest("enumeration verification", enumeration_verification_digest)?;
    ensure_digest("provenance", provenance.provenance_digest)?;
    let verified_enumeration =
        verify_raw_enumerated_v1(raw.candidates.clone(), provenance.scope_digest)?;
    if verified_enumeration.verification_digest() != enumeration_verification_digest
        || provenance.provenance_digest
            != evidence_provenance_digest(
                provenance.trust_digest,
                provenance.scope_digest,
                provenance.objective_digest,
                provenance.authority_epoch,
                provenance.generator_principal_id.clone(),
                provenance.generator_controller_id.clone(),
                provenance.issued_at_unix_ms,
                provenance.valid_until_unix_ms,
            )
        || provenance.objective_digest != raw.candidates.receipt.objective_digest
        || provenance.scope_digest != verified_enumeration.scope_digest()
    {
        return Err(CanonicalPromptError::Corrupt(
            "pricing provenance/enumeration binding".to_owned(),
        ));
    }
    if raw.authority.grants_any()
        || raw.rows.len() != raw.candidates.candidates.len()
        || raw.rows.len() > super::MAX_CANONICAL_PROMPT_FACTORS
        || raw.pricing_set_digest.is_zero()
        || raw.pricing_policy_digest.is_zero()
        || raw.completeness_digest.is_zero()
        || provenance.valid_until_unix_ms < provenance.issued_at_unix_ms
    {
        return Err(CanonicalPromptError::Corrupt(
            "priced candidate envelope".to_owned(),
        ));
    }
    let mut previous: Option<&StableId> = None;
    let mut seen = BTreeSet::new();
    for (row, candidate) in raw.rows.iter().zip(&raw.candidates.candidates) {
        if row.binding != *candidate
            || row.pricing.factor_id != row.binding.factor_id
            || row.pricing.state_digest != raw.candidates.receipt.state_digest
            || row.pricing.expected_utility_q32 != row.net_utility_q32
            || row.pricing.authority.grants_any()
            || row.pricing.receipt_digest
                != legacy_pricing_receipt_digest(
                    &row.binding.factor_id,
                    row.pricing.state_digest,
                    row.pricing.expected_utility_q32,
                    row.pricing.downside_q32,
                    row.pricing.token_cost,
                    row.pricing.latency_cost_micros,
                    row.pricing.interference_ppm,
                    &row.pricing.confidence_interval,
                    raw.pricing_policy_digest,
                    row.binding.binding_digest,
                )
            || !seen.insert(row.binding.factor_id.clone())
            || previous.is_some_and(|value| value >= &row.binding.factor_id)
        {
            return Err(CanonicalPromptError::Corrupt(
                "pricing row identity/order/digest".to_owned(),
            ));
        }
        previous = Some(&row.binding.factor_id);
    }
    if raw.pricing_set_digest != legacy_pricing_set_digest(&raw.rows, raw.pricing_policy_digest) {
        return Err(CanonicalPromptError::Corrupt(
            "pricing-set digest mismatch".to_owned(),
        ));
    }
    let verification_digest = priced_verification_digest(
        raw.pricing_set_digest,
        raw.pricing_policy_digest,
        raw.completeness_digest,
        enumeration_verification_digest,
        provenance.provenance_digest,
    );
    Ok(VerifiedPricedPromptCandidatesV1 {
        raw,
        enumeration_verification_digest,
        provenance,
        verification_digest,
    })
}

#[allow(clippy::too_many_arguments)]
fn evidence_provenance_digest(
    trust_digest: Digest32,
    scope_digest: Digest32,
    objective_digest: Digest32,
    authority_epoch: u64,
    generator_principal_id: StableId,
    generator_controller_id: StableId,
    issued_at: u64,
    valid_until: u64,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.evidence-provenance.v1".to_vec();
    for digest in [trust_digest, scope_digest, objective_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&authority_epoch.to_be_bytes());
    push_id(&mut bytes, &generator_principal_id);
    push_id(&mut bytes, &generator_controller_id);
    bytes.extend_from_slice(&issued_at.to_be_bytes());
    bytes.extend_from_slice(&valid_until.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn legacy_pricing_receipt_digest(
    factor_id: &StableId,
    state_digest: Digest32,
    expected_utility: FixedQ32,
    downside: FixedQ32,
    token_cost: u32,
    latency_cost_micros: u64,
    interference_ppm: u32,
    confidence: &raw::PromptConfidenceIntervalV1,
    policy_digest: Digest32,
    binding_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-receipt.v1".to_vec();
    push_id(&mut bytes, factor_id);
    bytes.extend_from_slice(state_digest.as_array());
    bytes.extend_from_slice(&expected_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&downside.raw().to_be_bytes());
    bytes.extend_from_slice(&token_cost.to_be_bytes());
    bytes.extend_from_slice(&latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&interference_ppm.to_be_bytes());
    bytes.extend_from_slice(&confidence.lower_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.upper_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.support_count.to_be_bytes());
    bytes.extend_from_slice(confidence.support_audit_digest.as_array());
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(binding_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn legacy_pricing_set_digest(
    rows: &[raw::PricedPromptCandidateV1],
    policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-set.v1".to_vec();
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(&u64::try_from(rows.len()).unwrap_or(u64::MAX).to_be_bytes());
    for row in rows {
        push_id(&mut bytes, &row.binding.factor_id);
        bytes.extend_from_slice(row.pricing.receipt_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn priced_verification_digest(
    pricing_set_digest: Digest32,
    policy_digest: Digest32,
    completeness_digest: Digest32,
    enumeration_verification_digest: Digest32,
    provenance_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-pricing.v2".to_vec();
    for digest in [
        pricing_set_digest,
        policy_digest,
        completeness_digest,
        enumeration_verification_digest,
        provenance_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}
