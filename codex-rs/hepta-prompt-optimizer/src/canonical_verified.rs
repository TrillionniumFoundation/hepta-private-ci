use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::ops::Deref;

use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::digest;
use super::raw;

#[path = "canonical_pricing_math.rs"]
mod pricing_math;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalPromptError {
    EmptyDigest(&'static str),
    InvalidTime,
    CandidateLimit,
    CandidateIntegrity(&'static str),
    CandidateCompleteness(String),
    CandidateCompletenessBinding,
    Evidence(String),
    EvidenceContextMismatch,
    EvidenceIndependence,
    EvidenceExpired,
    InvalidPricingPolicy,
    InvalidPricingEvidence(String),
    DuplicatePricingEvidence,
    UnknownFactor(String),
    SelectionLimit,
    TokenBudgetLimit,
    KnowledgeGraph(String),
    GraphSourceMismatch,
    GenerationVectorMismatch,
    InteractionProjectionIncomplete(u32),
    RequiredFactorUnavailable(String),
    DuplicateInteraction,
    UnexpectedPairEvidence,
    InvalidPairEvidence,
    MissingPairEvidence(String, String),
    DuplicatePairEvidence,
    PrerequisiteCycle(String),
    UnsatisfiableConstraintGraph(String),
    PortfolioIntegrity(&'static str),
    PolicyMismatch,
    TrustDrift,
    GraphDrift,
    Corrupt(&'static str),
    Unavailable(&'static str),
    Indeterminate(&'static str),
    Quarantined(&'static str),
    Arithmetic,
    Raw(String),
}

impl fmt::Display for CanonicalPromptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalPromptError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptEnumerationRequestV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub evidence_scope_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub required_factor_ids: Vec<StableId>,
    pub maximum_candidates: u32,
    pub selection_grammar_digest: Digest32,
    pub generator_code_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnumeratedPromptCandidatesV1 {
    pub(super) inner: raw::EnumeratedPromptCandidatesV1,
    pub(super) evidence_scope_digest: Digest32,
    pub(super) generator_code_digest: Digest32,
    pub(super) hard_filter_digest: Digest32,
    pub(super) truncation_digest: Digest32,
    verification_digest: Digest32,
}

impl EnumeratedPromptCandidatesV1 {
    #[must_use]
    pub fn as_raw(&self) -> &raw::EnumeratedPromptCandidatesV1 {
        &self.inner
    }

    #[must_use]
    pub fn into_raw(self) -> raw::EnumeratedPromptCandidatesV1 {
        self.inner
    }

    #[must_use]
    pub const fn evidence_scope_digest(&self) -> Digest32 {
        self.evidence_scope_digest
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    pub(super) fn verify_internal(&self) -> Result<(), CanonicalPromptError> {
        validate_enumerated_inner(&self.inner)?;
        if self.evidence_scope_digest.is_zero()
            || self.generator_code_digest.is_zero()
            || self.hard_filter_digest.is_zero()
            || self.truncation_digest.is_zero()
            || self.verification_digest != enumerated_verification_digest(self)
        {
            return Err(CanonicalPromptError::CandidateIntegrity(
                "verified enumeration metadata",
            ));
        }
        Ok(())
    }
}

impl Deref for EnumeratedPromptCandidatesV1 {
    type Target = raw::EnumeratedPromptCandidatesV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn enumerate_factors_v1(
    registry: &PromptRegistry,
    request: PromptEnumerationRequestV1,
) -> Result<EnumeratedPromptCandidatesV1, CanonicalPromptError> {
    for (name, value) in [
        ("objective", request.objective_digest),
        ("state", request.state_digest),
        ("evidence_scope", request.evidence_scope_digest),
        ("generation_vector", request.generation_vector_digest),
        ("selection_grammar", request.selection_grammar_digest),
        ("generator_code", request.generator_code_digest),
        ("hard_filter", request.hard_filter_digest),
        ("truncation", request.truncation_digest),
    ] {
        ensure_digest(name, value)?;
    }
    if request.now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    request
        .model_tuple
        .validate()
        .map_err(|error| CanonicalPromptError::Raw(format!("{error:?}")))?;

    let inner = raw::enumerate_factors_v1(
        registry,
        raw::PromptEnumerationRequestV1 {
            set_id: request.set_id,
            objective_digest: request.objective_digest,
            state_digest: request.state_digest,
            generation_vector_digest: request.generation_vector_digest,
            model_tuple: request.model_tuple,
            now_unix_ms: request.now_unix_ms,
            required_factor_ids: request.required_factor_ids,
            maximum_candidates: request.maximum_candidates,
            selection_grammar_digest: request.selection_grammar_digest,
        },
    )
    .map_err(|error| CanonicalPromptError::Raw(format!("{error:?}")))?;
    validate_enumerated_inner(&inner)?;
    let mut result = EnumeratedPromptCandidatesV1 {
        inner,
        evidence_scope_digest: request.evidence_scope_digest,
        generator_code_digest: request.generator_code_digest,
        hard_filter_digest: request.hard_filter_digest,
        truncation_digest: request.truncation_digest,
        verification_digest: Digest32::ZERO,
    };
    result.verification_digest = enumerated_verification_digest(&result);
    result.verify_internal()?;
    Ok(result)
}

fn validate_enumerated_inner(
    inner: &raw::EnumeratedPromptCandidatesV1,
) -> Result<(), CanonicalPromptError> {
    inner
        .registry_snapshot
        .validate()
        .map_err(|error| CanonicalPromptError::Raw(format!("{error:?}")))?;
    inner
        .model_tuple
        .validate()
        .map_err(|error| CanonicalPromptError::Raw(format!("{error:?}")))?;
    if inner.receipt.authority.grants_any()
        || inner.registry_snapshot.authority.grants_any()
        || inner.candidates.len() > raw::MAX_CANONICAL_PROMPT_FACTORS
        || inner.registry_snapshot.generation_vector_digest != inner.generation_vector_digest
        || inner.registry_snapshot.model_tuple_digest != inner.model_tuple.digest()
        || inner.receipt.registry_digest != inner.registry_snapshot.registry_digest
    {
        return Err(CanonicalPromptError::CandidateIntegrity("enumeration envelope"));
    }
    let mut factor_ids = Vec::with_capacity(inner.candidates.len());
    for (index, candidate) in inner.candidates.iter().enumerate() {
        candidate
            .realization
            .validate()
            .map_err(|error| CanonicalPromptError::Raw(format!("{error:?}")))?;
        if candidate.factor_id != candidate.realization.factor_id
            || candidate.binding_digest != candidate.realization.digest()
            || !binding_matches_tuple(&candidate.realization, &inner.model_tuple)
            || index > 0 && inner.candidates[index - 1].factor_id >= candidate.factor_id
        {
            return Err(CanonicalPromptError::CandidateIntegrity("candidate binding"));
        }
        factor_ids.push(candidate.factor_id.clone());
    }
    let candidates_digest = digest::digest_candidates(&inner.candidates);
    let order_digest = digest::digest_candidate_order(&inner.candidates);
    let receipt_digest = digest::digest_candidate_receipt(
        &inner.receipt.set_id,
        inner.receipt.objective_digest,
        inner.receipt.state_digest,
        inner.receipt.registry_digest,
        inner.registry_snapshot.snapshot_digest,
        inner.model_tuple.digest(),
        inner.receipt.selection_grammar_digest,
        &factor_ids,
        candidates_digest,
        order_digest,
        inner.omitted_count,
    );
    if inner.candidates_digest != candidates_digest
        || inner.canonical_order_digest != order_digest
        || inner.receipt.candidate_factor_ids != factor_ids
        || inner.receipt.receipt_digest != receipt_digest
    {
        return Err(CanonicalPromptError::CandidateIntegrity("candidate digest"));
    }
    Ok(())
}

fn enumerated_verification_digest(value: &EnumeratedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-enumeration.v1".to_vec();
    for item in [
        value.inner.receipt.receipt_digest,
        value.evidence_scope_digest,
        value.generator_code_digest,
        value.hard_filter_digest,
        value.truncation_digest,
    ] {
        digest::push_digest(&mut bytes, item);
    }
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingEvidenceV1 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub objective_digest: Digest32,
    pub evidence_scope_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub realization_binding_digest: Digest32,
    pub pricing_policy_digest: Digest32,
    pub state_digest: Digest32,
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
    pub support_audit_digest: Digest32,
    pub evidence: SignedLearningEvidenceV1,
}

pub fn pricing_evidence_signing_payload_v1(evidence: &PromptPricingEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.bound.v1".to_vec();
    digest::push_id(&mut bytes, &evidence.factor_id);
    digest::push_id(&mut bytes, &evidence.realization_id);
    for value in [
        evidence.objective_digest,
        evidence.evidence_scope_digest,
        evidence.candidate_set_digest,
        evidence.registry_snapshot_digest,
        evidence.generation_vector_digest,
        evidence.model_tuple_digest,
        evidence.realization_binding_digest,
        evidence.pricing_policy_digest,
        evidence.state_digest,
        evidence.support_audit_digest,
    ] {
        digest::push_digest(&mut bytes, value);
    }
    for value in [
        evidence.expected_incremental_utility_q32,
        evidence.downside_q32,
        evidence.confidence_lower_q32,
        evidence.confidence_upper_q32,
        evidence.context_crowding_cost_q32,
        evidence.privacy_cost_q32,
        evidence.instability_cost_q32,
        evidence.future_context_option_cost_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&evidence.support_count.to_be_bytes());
    bytes.extend_from_slice(&evidence.latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&evidence.interference_ppm.to_be_bytes());
    bytes
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPricingUnavailableReasonV1 {
    MissingEvidence,
    EvidenceExpired,
    EvidenceRevoked,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptUnavailablePricingV1 {
    pub factor_id: StableId,
    pub reason: PromptPricingUnavailableReasonV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PricedPromptCandidatesV1 {
    pub(super) inner: raw::PricedPromptCandidatesV1,
    pub(super) unavailable: Vec<PromptUnavailablePricingV1>,
    pub(super) generator_evidence: VerifiedLearningEvidenceV1,
    pub(super) trust_digest: Digest32,
    pub(super) evidence_scope_digest: Digest32,
    pub(super) objective_digest: Digest32,
    pub(super) authority_epoch: u64,
    pub(super) minimum_evidence_valid_until_unix_ms: u64,
    verification_digest: Digest32,
}

impl PricedPromptCandidatesV1 {
    #[must_use]
    pub fn as_raw(&self) -> &raw::PricedPromptCandidatesV1 {
        &self.inner
    }

    #[must_use]
    pub fn unavailable(&self) -> &[PromptUnavailablePricingV1] {
        &self.unavailable
    }

    #[must_use]
    pub const fn minimum_evidence_valid_until_unix_ms(&self) -> u64 {
        self.minimum_evidence_valid_until_unix_ms
    }

    #[must_use]
    pub const fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }

    pub(super) fn verify_internal(&self) -> Result<(), CanonicalPromptError> {
        validate_enumerated_inner(&self.inner.candidates)?;
        if self.inner.authority.grants_any()
            || self.inner.pricing_policy_digest.is_zero()
            || self.inner.completeness_digest.is_zero()
            || self.inner.pricing_set_digest
                != digest::digest_pricing_set(
                    &self.inner.rows,
                    self.inner.pricing_policy_digest,
                )
            || self.trust_digest.is_zero()
            || self.evidence_scope_digest.is_zero()
            || self.objective_digest != self.inner.candidates.receipt.objective_digest
            || self.authority_epoch == 0
            || self.minimum_evidence_valid_until_unix_ms == 0
            || self.verification_digest != priced_verification_digest(self)
        {
            return Err(CanonicalPromptError::CandidateIntegrity("verified pricing"));
        }
        let mut previous: Option<&StableId> = None;
        for row in &self.inner.rows {
            if previous.is_some_and(|value| value >= &row.binding.factor_id)
                || row.binding.factor_id != row.pricing.factor_id
                || row.binding.binding_digest != row.binding.realization.digest()
                || row.pricing.state_digest != self.inner.candidates.receipt.state_digest
                || row.pricing.authority.grants_any()
                || row.net_utility_q32 != row.pricing.expected_utility_q32
                || row.pricing.token_cost != row.binding.realization.token_cost
                || row.pricing.confidence_interval.lower_q32 > row.net_utility_q32
                || row.net_utility_q32 > row.pricing.confidence_interval.upper_q32
                || row.pricing.receipt_digest
                    != digest::digest_pricing_receipt(
                        &row.pricing.factor_id,
                        row.pricing.state_digest,
                        row.pricing.expected_utility_q32,
                        row.pricing.downside_q32,
                        row.pricing.token_cost,
                        row.pricing.latency_cost_micros,
                        row.pricing.interference_ppm,
                        &row.pricing.confidence_interval,
                        self.inner.pricing_policy_digest,
                        row.binding.binding_digest,
                    )
            {
                return Err(CanonicalPromptError::CandidateIntegrity("pricing row"));
            }
            previous = Some(&row.binding.factor_id);
        }
        Ok(())
    }
}

impl Deref for PricedPromptCandidatesV1 {
    type Target = raw::PricedPromptCandidatesV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn price_factors_v1(
    candidates: EnumeratedPromptCandidatesV1,
    completeness: &CandidateSetCompletenessReceiptV1,
    completeness_evidence: &SignedLearningEvidenceV1,
    pricing_evidence: Vec<PromptPricingEvidenceV1>,
    verifier: &LearningEvidenceVerifierV1,
    policy: &raw::PromptPricingPolicyV1,
    now_unix_ms: u64,
) -> Result<PricedPromptCandidatesV1, CanonicalPromptError> {
    candidates.verify_internal()?;
    if now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    if verifier.objective_digest() != candidates.inner.receipt.objective_digest
        || verifier.scope_digest() != candidates.evidence_scope_digest
    {
        return Err(CanonicalPromptError::EvidenceContextMismatch);
    }
    validate_candidate_completeness(&candidates, completeness)?;
    let completeness_payload = raw::candidate_completeness_signing_payload_v1(completeness)
        .map_err(|error| CanonicalPromptError::CandidateCompleteness(format!("{error:?}")))?;
    let generator_evidence = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            completeness_evidence,
            &completeness_payload,
            now_unix_ms,
        )
        .map_err(evidence_error)?;
    let pricing_policy_digest = policy
        .digest()
        .map_err(|_| CanonicalPromptError::InvalidPricingPolicy)?;

    let by_factor = candidates
        .inner
        .candidates
        .iter()
        .map(|candidate| (candidate.factor_id.clone(), candidate))
        .collect::<BTreeMap<_, _>>();
    let mut evidence_rows = BTreeMap::new();
    for evidence in pricing_evidence {
        if !by_factor.contains_key(&evidence.factor_id) {
            return Err(CanonicalPromptError::UnknownFactor(
                evidence.factor_id.to_string(),
            ));
        }
        if evidence_rows
            .insert(evidence.factor_id.clone(), evidence)
            .is_some()
        {
            return Err(CanonicalPromptError::DuplicatePricingEvidence);
        }
    }

    let mut rows = Vec::new();
    let mut unavailable = Vec::new();
    let mut minimum_valid_until = completeness_evidence.expires_at;
    for candidate in &candidates.inner.candidates {
        let Some(evidence) = evidence_rows.remove(&candidate.factor_id) else {
            unavailable.push(PromptUnavailablePricingV1 {
                factor_id: candidate.factor_id.clone(),
                reason: PromptPricingUnavailableReasonV1::MissingEvidence,
            });
            continue;
        };
        validate_pricing_evidence(
            &candidates,
            candidate,
            &evidence,
            pricing_policy_digest,
            policy,
        )?;
        let payload = pricing_evidence_signing_payload_v1(&evidence);
        let evaluator = match verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &evidence.evidence,
            &payload,
            now_unix_ms,
        ) {
            Ok(value) => value,
            Err(SignedEvidenceError::ValidityWindow) => {
                unavailable.push(PromptUnavailablePricingV1 {
                    factor_id: candidate.factor_id.clone(),
                    reason: PromptPricingUnavailableReasonV1::EvidenceExpired,
                });
                continue;
            }
            Err(SignedEvidenceError::Revoked) => {
                unavailable.push(PromptUnavailablePricingV1 {
                    factor_id: candidate.factor_id.clone(),
                    reason: PromptPricingUnavailableReasonV1::EvidenceRevoked,
                });
                continue;
            }
            Err(error) => return Err(evidence_error(error)),
        };
        verify_signed_independent_roles_v1(&generator_evidence, &evaluator, now_unix_ms)
            .map_err(|_| CanonicalPromptError::EvidenceIndependence)?;
        minimum_valid_until = minimum_valid_until.min(evidence.evidence.expires_at);

        let token_cost = candidate.realization.token_cost;
        let downside_penalty = policy
            .downside_weight_q32
            .checked_mul(evidence.downside_q32)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        let net_interval = pricing_math::net_interval(
            evidence.expected_incremental_utility_q32,
            evidence.confidence_lower_q32,
            evidence.confidence_upper_q32,
            [
                downside_penalty,
                scale_rate(policy.token_cost_per_token_q32, u64::from(token_cost))?,
                scale_rate(
                    policy.latency_cost_per_micro_q32,
                    evidence.latency_cost_micros,
                )?,
                scale_rate(
                    policy.interference_cost_per_ppm_q32,
                    u64::from(evidence.interference_ppm),
                )?,
                evidence.context_crowding_cost_q32,
                evidence.privacy_cost_q32,
                evidence.instability_cost_q32,
                evidence.future_context_option_cost_q32,
            ],
        )?;
        let net = net_interval.mean;
        let confidence_interval = raw::PromptConfidenceIntervalV1 {
            lower_q32: net_interval.lower,
            upper_q32: net_interval.upper,
            support_count: evidence.support_count,
            support_audit_digest: evidence.support_audit_digest,
        };
        let receipt_digest = digest::digest_pricing_receipt(
            &candidate.factor_id,
            candidates.inner.receipt.state_digest,
            net,
            evidence.downside_q32,
            token_cost,
            evidence.latency_cost_micros,
            evidence.interference_ppm,
            &confidence_interval,
            pricing_policy_digest,
            candidate.binding_digest,
        );
        rows.push(raw::PricedPromptCandidateV1 {
            binding: candidate.clone(),
            pricing: raw::PromptPricingReceiptV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.inner.receipt.state_digest,
                expected_utility_q32: net,
                downside_q32: evidence.downside_q32,
                token_cost,
                latency_cost_micros: evidence.latency_cost_micros,
                interference_ppm: evidence.interference_ppm,
                confidence_interval,
                receipt_digest,
                authority: AuthorityPosture::DENY_ALL,
            },
            net_utility_q32: net,
        });
    }
    if let Some(unused) = evidence_rows.keys().next() {
        return Err(CanonicalPromptError::UnknownFactor(unused.to_string()));
    }
    let completeness_digest = validate_candidate_set_completeness(completeness)
        .map_err(|error| CanonicalPromptError::CandidateCompleteness(format!("{error:?}")))?;
    let pricing_set_digest = digest::digest_pricing_set(&rows, pricing_policy_digest);
    let inner = raw::PricedPromptCandidatesV1 {
        candidates: candidates.inner,
        completeness_digest,
        pricing_policy_digest,
        rows,
        pricing_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    let mut result = PricedPromptCandidatesV1 {
        inner,
        unavailable,
        generator_evidence,
        trust_digest: verifier.trust_digest(),
        evidence_scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        minimum_evidence_valid_until_unix_ms: minimum_valid_until,
        verification_digest: Digest32::ZERO,
    };
    result.verification_digest = priced_verification_digest(&result);
    result.verify_internal()?;
    Ok(result)
}

fn validate_candidate_completeness(
    candidates: &EnumeratedPromptCandidatesV1,
    completeness: &CandidateSetCompletenessReceiptV1,
) -> Result<(), CanonicalPromptError> {
    let candidate_count = u32::try_from(candidates.inner.candidates.len())
        .map_err(|_| CanonicalPromptError::CandidateLimit)?;
    validate_candidate_set_completeness(completeness)
        .map_err(|error| CanonicalPromptError::CandidateCompleteness(format!("{error:?}")))?;
    if completeness.set_id != candidates.inner.receipt.set_id
        || completeness.state_digest != candidates.inner.receipt.state_digest
        || completeness.generator_id.as_str() != "prompt.optimizer"
        || completeness.generator_code_digest != candidates.generator_code_digest
        || completeness.grammar_digest != candidates.inner.receipt.selection_grammar_digest
        || completeness.hard_filter_digest != candidates.hard_filter_digest
        || completeness.truncation_digest != candidates.truncation_digest
        || completeness.candidates_digest != candidates.inner.candidates_digest
        || completeness.canonical_order_digest != candidates.inner.canonical_order_digest
        || completeness.candidate_count != candidate_count
        || completeness.omitted_count_bound < candidates.inner.omitted_count
    {
        return Err(CanonicalPromptError::CandidateCompletenessBinding);
    }
    Ok(())
}

fn validate_pricing_evidence(
    candidates: &EnumeratedPromptCandidatesV1,
    candidate: &raw::PromptCandidateBindingV1,
    evidence: &PromptPricingEvidenceV1,
    pricing_policy_digest: Digest32,
    policy: &raw::PromptPricingPolicyV1,
) -> Result<(), CanonicalPromptError> {
    if evidence.factor_id != candidate.factor_id
        || evidence.realization_id != candidate.realization.realization_id
        || evidence.objective_digest != candidates.inner.receipt.objective_digest
        || evidence.evidence_scope_digest != candidates.evidence_scope_digest
        || evidence.candidate_set_digest != candidates.inner.candidates_digest
        || evidence.registry_snapshot_digest != candidates.inner.registry_snapshot.snapshot_digest
        || evidence.generation_vector_digest != candidates.inner.generation_vector_digest
        || evidence.model_tuple_digest != candidates.inner.model_tuple.digest()
        || evidence.realization_binding_digest != candidate.binding_digest
        || evidence.pricing_policy_digest != pricing_policy_digest
        || evidence.state_digest != candidates.inner.receipt.state_digest
        || evidence.support_audit_digest.is_zero()
        || evidence.support_count < policy.minimum_support_count
        || evidence.interference_ppm > policy.maximum_interference_ppm
        || evidence.downside_q32 < FixedQ32::ZERO
        || evidence.context_crowding_cost_q32 < FixedQ32::ZERO
        || evidence.privacy_cost_q32 < FixedQ32::ZERO
        || evidence.instability_cost_q32 < FixedQ32::ZERO
        || evidence.future_context_option_cost_q32 < FixedQ32::ZERO
        || evidence.confidence_lower_q32 > evidence.expected_incremental_utility_q32
        || evidence.expected_incremental_utility_q32 > evidence.confidence_upper_q32
    {
        return Err(CanonicalPromptError::InvalidPricingEvidence(
            evidence.factor_id.to_string(),
        ));
    }
    Ok(())
}

fn priced_verification_digest(value: &PricedPromptCandidatesV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.verified-pricing.v1".to_vec();
    for item in [
        value.inner.candidates.receipt.receipt_digest,
        value.inner.completeness_digest,
        value.inner.pricing_policy_digest,
        value.inner.pricing_set_digest,
        value.trust_digest,
        value.evidence_scope_digest,
        value.objective_digest,
    ] {
        digest::push_digest(&mut bytes, item);
    }
    bytes.extend_from_slice(&value.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&value.minimum_evidence_valid_until_unix_ms.to_be_bytes());
    digest::push_len(&mut bytes, value.unavailable.len());
    for row in &value.unavailable {
        digest::push_id(&mut bytes, &row.factor_id);
        bytes.push(match row.reason {
            PromptPricingUnavailableReasonV1::MissingEvidence => 0,
            PromptPricingUnavailableReasonV1::EvidenceExpired => 1,
            PromptPricingUnavailableReasonV1::EvidenceRevoked => 2,
        });
    }
    Digest32::of_bytes(&bytes)
}

fn binding_matches_tuple(
    binding: &codex_hepta_prompt_registry::PromptRealizationBindingV2,
    tuple: &PromptModelTupleV2,
) -> bool {
    binding.model_id == tuple.model_id
        && binding.model_version == tuple.model_version
        && binding.model_digest == tuple.model_digest
        && binding.tokenizer_digest == tuple.tokenizer_digest
        && binding.template_digest == tuple.template_digest
        && binding.tool_schema_digest == tuple.tool_schema_digest
        && binding.context_profile_digest == tuple.context_profile_digest
        && binding.locale_id == tuple.locale_id
}

fn scale_rate(rate: FixedQ32, units: u64) -> Result<FixedQ32, CanonicalPromptError> {
    if rate < FixedQ32::ZERO {
        return Err(CanonicalPromptError::InvalidPricingPolicy);
    }
    let product = i128::from(rate.raw())
        .checked_mul(i128::from(units))
        .ok_or(CanonicalPromptError::Arithmetic)?;
    let raw = i64::try_from(product).map_err(|_| CanonicalPromptError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

fn ensure_digest(name: &'static str, value: Digest32) -> Result<(), CanonicalPromptError> {
    if value.is_zero() {
        return Err(CanonicalPromptError::EmptyDigest(name));
    }
    Ok(())
}

fn evidence_error(error: SignedEvidenceError) -> CanonicalPromptError {
    match error {
        SignedEvidenceError::ValidityWindow => CanonicalPromptError::EvidenceExpired,
        value => CanonicalPromptError::Evidence(format!("{value:?}")),
    }
}