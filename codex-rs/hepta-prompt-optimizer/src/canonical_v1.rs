//! Canonical prompt-selection policy surfaces.
//!
//! This module turns the authority-free optimizer kernel into the typed policy
//! chain registered by `PromptCandidateSetReceiptV1`, `PromptPricingReceiptV1`,
//! `PromptPortfolioReceiptV1` and `PromptExerciseDecisionV1`. It remains
//! read-only: registry ownership, signed evidence admission, context compilation
//! and provider delivery stay with their declared owners.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::CausalV2Error;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::validate_candidate_set_completeness;
use codex_hepta_prompt_registry::CompatibleRealizationSetV2;
use codex_hepta_prompt_registry::MAX_COMPATIBLE_REALIZATIONS_V2;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRegistrySnapshotV2;
use codex_hepta_prompt_registry::PromptRegistryV2Error;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub const MAX_CANONICAL_FACTORS_V1: usize = 128;
pub const MAX_CANONICAL_SELECTED_FACTORS_V1: usize = 16;
pub const MAX_CANONICAL_INTERACTIONS_V1: usize = 512;
pub const MAX_CANONICAL_CONSTRAINTS_V1: usize = 512;
pub const MAX_CANONICAL_TOKEN_BUDGET_V1: u32 = 1_000_000;
const PPM_SCALE: i128 = 1_000_000;
const OPTIMIZER_ID: &str = "prompt.optimizer";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalPromptError {
    Registry(PromptRegistryV2Error),
    Causal(CausalV2Error),
    Json(String),
    InvalidIdentifier(String),
    EmptyDigest(&'static str),
    InvalidTime,
    CandidateLimitExceeded,
    NoCandidates,
    DuplicateFactor(String),
    MissingPricingEvidence(String),
    UnexpectedPricingEvidence(String),
    PricingStateMismatch(String),
    EvidenceRoleMismatch(String),
    EvidencePayloadMismatch(String),
    InvalidPricingValue(String),
    InvalidConfidenceInterval(String),
    PpmOutOfRange(String),
    InteractionLimitExceeded,
    ConstraintLimitExceeded,
    InvalidRelation(String),
    DuplicateInteraction(String, String),
    DuplicateConstraint(String, String, String),
    UnknownFactor(String),
    PrerequisiteCycle(String),
    InvalidPortfolioLimit,
    InvalidTokenBudget,
    InvalidValidityWindow,
    Arithmetic,
    CanonicalOrder,
    NonCanonicalEncoding,
    ReceiptDigestMismatch,
}

impl fmt::Display for CanonicalPromptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalPromptError {}

impl From<PromptRegistryV2Error> for CanonicalPromptError {
    fn from(value: PromptRegistryV2Error) -> Self {
        Self::Registry(value)
    }
}

impl From<CausalV2Error> for CanonicalPromptError {
    fn from(value: CausalV2Error) -> Self {
        Self::Causal(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateEnumerationRequestV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub selection_grammar_digest: Digest32,
    pub generator_code_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub maximum_results: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    /// Exact V2 registry snapshot digest, stronger than the legacy content-only digest.
    pub registry_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub selection_grammar_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptCandidateSetReceiptV1 {
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        for (label, digest) in [
            ("candidate objective", self.objective_digest),
            ("candidate state", self.state_digest),
            ("candidate registry", self.registry_digest),
            ("selection grammar", self.selection_grammar_digest),
            ("candidate receipt", self.receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.candidate_factor_ids.is_empty()
            || self.candidate_factor_ids.len() > MAX_CANONICAL_FACTORS_V1
        {
            return Err(CanonicalPromptError::CandidateLimitExceeded);
        }
        require_sorted_unique(&self.candidate_factor_ids)?;
        if self.authority.grants_any() {
            return Err(CanonicalPromptError::InvalidPricingValue(
                "candidate receipt grants authority".to_string(),
            ));
        }
        if self.receipt_digest != Digest32::of_bytes(&self.semantic_json_bytes()?) {
            return Err(CanonicalPromptError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        self.validate()?;
        self.semantic_json_bytes()
    }

    pub fn from_canonical_json(bytes: &[u8]) -> Result<Self, CanonicalPromptError> {
        let wire: CandidateSetWire = decode_canonical(bytes)?;
        let mut value = Self {
            set_id: parse_id(&wire.set_id)?,
            objective_digest: parse_digest(&wire.objective_digest)?,
            state_digest: parse_digest(&wire.state_digest)?,
            registry_digest: parse_digest(&wire.registry_digest)?,
            candidate_factor_ids: parse_ids(&wire.candidate_factor_ids)?,
            selection_grammar_digest: parse_digest(&wire.selection_grammar_digest)?,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = Digest32::of_bytes(&value.semantic_json_bytes()?);
        value.validate()?;
        if value.semantic_json_bytes()? != bytes {
            return Err(CanonicalPromptError::NonCanonicalEncoding);
        }
        Ok(value)
    }

    fn semantic_json_bytes(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        encode(&CandidateSetWire {
            set_id: self.set_id.to_string(),
            objective_digest: self.objective_digest.to_string(),
            state_digest: self.state_digest.to_string(),
            registry_digest: self.registry_digest.to_string(),
            candidate_factor_ids: ids_to_strings(&self.candidate_factor_ids),
            selection_grammar_digest: self.selection_grammar_digest.to_string(),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnumeratedPromptCandidatesV1 {
    pub receipt: PromptCandidateSetReceiptV1,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub completeness_digest: Digest32,
    pub registry_snapshot: PromptRegistrySnapshotV2,
    pub compatible_realizations: CompatibleRealizationSetV2,
    pub model_tuple: PromptModelTupleV2,
}

pub fn enumerate_factors_v1(
    registry: &PromptRegistry,
    request: CandidateEnumerationRequestV1,
) -> Result<EnumeratedPromptCandidatesV1, CanonicalPromptError> {
    for (label, digest) in [
        ("enumeration objective", request.objective_digest),
        ("enumeration state", request.state_digest),
        ("generation vector", request.generation_vector_digest),
        ("selection grammar", request.selection_grammar_digest),
        ("generator code", request.generator_code_digest),
        ("hard filter", request.hard_filter_digest),
        ("truncation", request.truncation_digest),
    ] {
        require_digest(digest, label)?;
    }
    if request.now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    let maximum_results = usize::try_from(request.maximum_results)
        .map_err(|_| CanonicalPromptError::CandidateLimitExceeded)?;
    if maximum_results == 0 || maximum_results > MAX_CANONICAL_FACTORS_V1 {
        return Err(CanonicalPromptError::CandidateLimitExceeded);
    }
    request.model_tuple.validate()?;
    let registry_snapshot = registry.snapshot_v2(
        request.generation_vector_digest,
        &request.model_tuple,
    )?;
    let compatible_realizations = registry.read_compatible_v2(
        &registry_snapshot,
        request.generation_vector_digest,
        &request.model_tuple,
        request.now_unix_ms,
        Vec::new(),
        request.maximum_results,
    )?;
    let mut factor_ids = compatible_realizations
        .bindings
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    factor_ids.sort();
    factor_ids.dedup();
    if factor_ids.is_empty() {
        return Err(CanonicalPromptError::NoCandidates);
    }
    if factor_ids.len() > MAX_CANONICAL_FACTORS_V1 {
        return Err(CanonicalPromptError::CandidateLimitExceeded);
    }

    let candidate_digest = digest_ids(b"hepta.prompt-optimizer.candidate-factors.v1", &factor_ids);
    let canonical_order_digest =
        digest_ids(b"hepta.prompt-optimizer.candidate-order.v1", &factor_ids);
    let optimizer_id = parse_id(OPTIMIZER_ID)?;
    let candidate_count = u32::try_from(factor_ids.len())
        .map_err(|_| CanonicalPromptError::CandidateLimitExceeded)?;
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: request.set_id.clone(),
        state_digest: request.state_digest,
        generator_id: optimizer_id,
        generator_code_digest: request.generator_code_digest,
        grammar_digest: request.selection_grammar_digest,
        hard_filter_digest: request.hard_filter_digest,
        truncation_digest: request.truncation_digest,
        candidates_digest: candidate_digest,
        candidate_count,
        omitted_count_bound: compatible_realizations.omitted_count,
        canonical_order_digest,
        complete_for_generator: true,
    };
    let completeness_digest = validate_candidate_set_completeness(&completeness)?;
    let mut receipt = PromptCandidateSetReceiptV1 {
        set_id: request.set_id,
        objective_digest: request.objective_digest,
        state_digest: request.state_digest,
        registry_digest: registry_snapshot.snapshot_digest,
        candidate_factor_ids: factor_ids,
        selection_grammar_digest: request.selection_grammar_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = Digest32::of_bytes(&receipt.semantic_json_bytes()?);
    receipt.validate()?;
    Ok(EnumeratedPromptCandidatesV1 {
        receipt,
        completeness,
        completeness_digest,
        registry_snapshot,
        compatible_realizations,
        model_tuple: request.model_tuple,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingEvidenceV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub causal_estimate_digest: Digest32,
    pub ndu_utility_digest: Digest32,
    pub support_audit_digest: Digest32,
    pub gross_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_lower_q32: FixedQ32,
    pub confidence_upper_q32: FixedQ32,
    pub context_crowding_cost_q32: FixedQ32,
    pub privacy_cost_q32: FixedQ32,
    pub instability_cost_q32: FixedQ32,
    pub future_context_option_cost_q32: FixedQ32,
}

impl PromptPricingEvidenceV1 {
    pub fn payload_digest(&self) -> Result<Digest32, CanonicalPromptError> {
        self.validate()?;
        let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.v1".to_vec();
        push_id(&mut bytes, &self.factor_id);
        for digest in [
            self.state_digest,
            self.causal_estimate_digest,
            self.ndu_utility_digest,
            self.support_audit_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.gross_utility_q32,
            self.downside_q32,
            self.confidence_lower_q32,
            self.confidence_upper_q32,
            self.context_crowding_cost_q32,
            self.privacy_cost_q32,
            self.instability_cost_q32,
            self.future_context_option_cost_q32,
        ] {
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        bytes.extend_from_slice(&self.latency_cost_micros.to_be_bytes());
        bytes.extend_from_slice(&self.interference_ppm.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    fn validate(&self) -> Result<(), CanonicalPromptError> {
        for (label, digest) in [
            ("pricing state", self.state_digest),
            ("causal estimate", self.causal_estimate_digest),
            ("ndu utility", self.ndu_utility_digest),
            ("support audit", self.support_audit_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.interference_ppm > 1_000_000 {
            return Err(CanonicalPromptError::PpmOutOfRange(
                self.factor_id.to_string(),
            ));
        }
        if self.downside_q32 < FixedQ32::ZERO
            || self.context_crowding_cost_q32 < FixedQ32::ZERO
            || self.privacy_cost_q32 < FixedQ32::ZERO
            || self.instability_cost_q32 < FixedQ32::ZERO
            || self.future_context_option_cost_q32 < FixedQ32::ZERO
        {
            return Err(CanonicalPromptError::InvalidPricingValue(
                self.factor_id.to_string(),
            ));
        }
        if self.confidence_lower_q32 > self.gross_utility_q32
            || self.gross_utility_q32 > self.confidence_upper_q32
        {
            return Err(CanonicalPromptError::InvalidConfidenceInterval(
                self.factor_id.to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPromptPricingEvidenceV1 {
    pub evidence: PromptPricingEvidenceV1,
    pub verification: VerifiedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingPolicyV1 {
    pub token_shadow_price_q32_per_token: FixedQ32,
    pub latency_shadow_price_q32_per_microsecond: FixedQ32,
    pub interference_shadow_price_q32_at_full_scale: FixedQ32,
    pub downside_weight_q32: FixedQ32,
    pub policy_digest: Digest32,
}

impl PromptPricingPolicyV1 {
    pub fn new(
        token_shadow_price_q32_per_token: FixedQ32,
        latency_shadow_price_q32_per_microsecond: FixedQ32,
        interference_shadow_price_q32_at_full_scale: FixedQ32,
        downside_weight_q32: FixedQ32,
    ) -> Result<Self, CanonicalPromptError> {
        let mut policy = Self {
            token_shadow_price_q32_per_token,
            latency_shadow_price_q32_per_microsecond,
            interference_shadow_price_q32_at_full_scale,
            downside_weight_q32,
            policy_digest: Digest32::ZERO,
        };
        policy.validate_terms()?;
        policy.policy_digest = policy.compute_digest();
        Ok(policy)
    }

    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        self.validate_terms()?;
        if self.policy_digest.is_zero() || self.policy_digest != self.compute_digest() {
            return Err(CanonicalPromptError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    fn validate_terms(&self) -> Result<(), CanonicalPromptError> {
        if self.token_shadow_price_q32_per_token < FixedQ32::ZERO
            || self.latency_shadow_price_q32_per_microsecond < FixedQ32::ZERO
            || self.interference_shadow_price_q32_at_full_scale < FixedQ32::ZERO
            || self.downside_weight_q32 < FixedQ32::ZERO
        {
            return Err(CanonicalPromptError::InvalidPricingValue(
                "negative pricing policy term".to_string(),
            ));
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.pricing-policy.v1".to_vec();
        for value in [
            self.token_shadow_price_q32_per_token,
            self.latency_shadow_price_q32_per_microsecond,
            self.interference_shadow_price_q32_at_full_scale,
            self.downside_weight_q32,
        ] {
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptConfidenceIntervalV1 {
    pub lower_q32: FixedQ32,
    pub upper_q32: FixedQ32,
    pub causal_estimate_digest: Digest32,
    pub ndu_utility_digest: Digest32,
    pub support_audit_digest: Digest32,
    pub pricing_policy_digest: Digest32,
    pub realization_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptPricingReceiptV1 {
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        require_digest(self.state_digest, "pricing state")?;
        if self.token_cost == 0 || self.interference_ppm > 1_000_000 {
            return Err(CanonicalPromptError::InvalidPricingValue(
                self.factor_id.to_string(),
            ));
        }
        if self.downside_q32 < FixedQ32::ZERO
            || self.confidence_interval.lower_q32 > self.confidence_interval.upper_q32
        {
            return Err(CanonicalPromptError::InvalidPricingValue(
                self.factor_id.to_string(),
            ));
        }
        for (label, digest) in [
            ("causal estimate", self.confidence_interval.causal_estimate_digest),
            ("ndu utility", self.confidence_interval.ndu_utility_digest),
            ("support audit", self.confidence_interval.support_audit_digest),
            ("pricing policy", self.confidence_interval.pricing_policy_digest),
            ("realization", self.confidence_interval.realization_digest),
            ("pricing receipt", self.receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.authority.grants_any() {
            return Err(CanonicalPromptError::InvalidPricingValue(
                "pricing receipt grants authority".to_string(),
            ));
        }
        if self.receipt_digest != Digest32::of_bytes(&self.semantic_json_bytes()?) {
            return Err(CanonicalPromptError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        self.validate()?;
        self.semantic_json_bytes()
    }

    pub fn from_canonical_json(bytes: &[u8]) -> Result<Self, CanonicalPromptError> {
        let wire: PricingWire = decode_canonical(bytes)?;
        let mut value = Self {
            factor_id: parse_id(&wire.factor_id)?,
            state_digest: parse_digest(&wire.state_digest)?,
            expected_utility_q32: FixedQ32::from_raw(wire.expected_utility_q32),
            downside_q32: FixedQ32::from_raw(wire.downside_q32),
            token_cost: wire.token_cost,
            latency_cost_micros: wire.latency_cost_micros,
            interference_ppm: wire.interference_ppm,
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: FixedQ32::from_raw(wire.confidence_interval.lower_q32),
                upper_q32: FixedQ32::from_raw(wire.confidence_interval.upper_q32),
                causal_estimate_digest: parse_digest(
                    &wire.confidence_interval.causal_estimate_digest,
                )?,
                ndu_utility_digest: parse_digest(&wire.confidence_interval.ndu_utility_digest)?,
                support_audit_digest: parse_digest(
                    &wire.confidence_interval.support_audit_digest,
                )?,
                pricing_policy_digest: parse_digest(
                    &wire.confidence_interval.pricing_policy_digest,
                )?,
                realization_digest: parse_digest(
                    &wire.confidence_interval.realization_digest,
                )?,
            },
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = Digest32::of_bytes(&value.semantic_json_bytes()?);
        value.validate()?;
        if value.semantic_json_bytes()? != bytes {
            return Err(CanonicalPromptError::NonCanonicalEncoding);
        }
        Ok(value)
    }

    fn semantic_json_bytes(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        encode(&PricingWire {
            factor_id: self.factor_id.to_string(),
            state_digest: self.state_digest.to_string(),
            expected_utility_q32: self.expected_utility_q32.raw(),
            downside_q32: self.downside_q32.raw(),
            token_cost: self.token_cost,
            latency_cost_micros: self.latency_cost_micros,
            interference_ppm: self.interference_ppm,
            confidence_interval: ConfidenceWire {
                lower_q32: self.confidence_interval.lower_q32.raw(),
                upper_q32: self.confidence_interval.upper_q32.raw(),
                causal_estimate_digest: self
                    .confidence_interval
                    .causal_estimate_digest
                    .to_string(),
                ndu_utility_digest: self.confidence_interval.ndu_utility_digest.to_string(),
                support_audit_digest: self.confidence_interval.support_audit_digest.to_string(),
                pricing_policy_digest: self.confidence_interval.pricing_policy_digest.to_string(),
                realization_digest: self.confidence_interval.realization_digest.to_string(),
            },
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PricedPromptFactorV1 {
    pub receipt: PromptPricingReceiptV1,
    pub realization: PromptRealizationBindingV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingSetV1 {
    pub candidate_set_digest: Digest32,
    pub prices: Vec<PricedPromptFactorV1>,
    pub set_digest: Digest32,
}

impl PromptPricingSetV1 {
    pub fn price_for(&self, factor_id: &StableId) -> Option<&PricedPromptFactorV1> {
        self.prices
            .iter()
            .find(|priced| &priced.receipt.factor_id == factor_id)
    }
}

pub fn price_factors_v1(
    enumerated: &EnumeratedPromptCandidatesV1,
    evidence: Vec<VerifiedPromptPricingEvidenceV1>,
    policy: &PromptPricingPolicyV1,
) -> Result<PromptPricingSetV1, CanonicalPromptError> {
    enumerated.receipt.validate()?;
    policy.validate()?;
    let mut by_factor = BTreeMap::new();
    for bundle in evidence {
        bundle.evidence.validate()?;
        if bundle.verification.role() != LearningEvidenceRoleV1::Evaluator {
            return Err(CanonicalPromptError::EvidenceRoleMismatch(
                bundle.evidence.factor_id.to_string(),
            ));
        }
        if bundle.verification.payload_digest() != bundle.evidence.payload_digest()? {
            return Err(CanonicalPromptError::EvidencePayloadMismatch(
                bundle.evidence.factor_id.to_string(),
            ));
        }
        if bundle.evidence.state_digest != enumerated.receipt.state_digest {
            return Err(CanonicalPromptError::PricingStateMismatch(
                bundle.evidence.factor_id.to_string(),
            ));
        }
        let key = bundle.evidence.factor_id.clone();
        if by_factor.insert(key.clone(), bundle).is_some() {
            return Err(CanonicalPromptError::DuplicateFactor(key.to_string()));
        }
    }

    let mut prices = Vec::with_capacity(enumerated.receipt.candidate_factor_ids.len());
    for factor_id in &enumerated.receipt.candidate_factor_ids {
        let Some(bundle) = by_factor.remove(factor_id) else {
            return Err(CanonicalPromptError::MissingPricingEvidence(
                factor_id.to_string(),
            ));
        };
        let realization = choose_realization(&enumerated.compatible_realizations, factor_id)?;
        let token_penalty = scale_fixed_u64(
            policy.token_shadow_price_q32_per_token,
            u64::from(realization.token_cost),
        )?;
        let latency_penalty = scale_fixed_u64(
            policy.latency_shadow_price_q32_per_microsecond,
            bundle.evidence.latency_cost_micros,
        )?;
        let interference_penalty = scale_fixed_ppm(
            policy.interference_shadow_price_q32_at_full_scale,
            bundle.evidence.interference_ppm,
        )?;
        let downside_penalty = bundle
            .evidence
            .downside_q32
            .checked_mul(policy.downside_weight_q32)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        let mut penalty = token_penalty
            .checked_add(latency_penalty)
            .map_err(|_| CanonicalPromptError::Arithmetic)?
            .checked_add(interference_penalty)
            .map_err(|_| CanonicalPromptError::Arithmetic)?
            .checked_add(downside_penalty)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        for direct in [
            bundle.evidence.context_crowding_cost_q32,
            bundle.evidence.privacy_cost_q32,
            bundle.evidence.instability_cost_q32,
            bundle.evidence.future_context_option_cost_q32,
        ] {
            penalty = penalty
                .checked_add(direct)
                .map_err(|_| CanonicalPromptError::Arithmetic)?;
        }
        let expected_utility = bundle
            .evidence
            .gross_utility_q32
            .checked_sub(penalty)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        let lower = bundle
            .evidence
            .confidence_lower_q32
            .checked_sub(penalty)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        let upper = bundle
            .evidence
            .confidence_upper_q32
            .checked_sub(penalty)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        let realization_digest = realization.digest();
        let mut receipt = PromptPricingReceiptV1 {
            factor_id: factor_id.clone(),
            state_digest: bundle.evidence.state_digest,
            expected_utility_q32: expected_utility,
            downside_q32: bundle.evidence.downside_q32,
            token_cost: realization.token_cost,
            latency_cost_micros: bundle.evidence.latency_cost_micros,
            interference_ppm: bundle.evidence.interference_ppm,
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: lower,
                upper_q32: upper,
                causal_estimate_digest: bundle.evidence.causal_estimate_digest,
                ndu_utility_digest: bundle.evidence.ndu_utility_digest,
                support_audit_digest: bundle.evidence.support_audit_digest,
                pricing_policy_digest: policy.policy_digest,
                realization_digest,
            },
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = Digest32::of_bytes(&receipt.semantic_json_bytes()?);
        receipt.validate()?;
        prices.push(PricedPromptFactorV1 {
            receipt,
            realization,
        });
    }
    if let Some((extra, _)) = by_factor.into_iter().next() {
        return Err(CanonicalPromptError::UnexpectedPricingEvidence(
            extra.to_string(),
        ));
    }
    prices.sort_by(|left, right| left.receipt.factor_id.cmp(&right.receipt.factor_id));
    let candidate_set_digest = enumerated.receipt.receipt_digest;
    let mut bytes = b"hepta.prompt-optimizer.pricing-set.v1".to_vec();
    bytes.extend_from_slice(candidate_set_digest.as_array());
    for priced in &prices {
        bytes.extend_from_slice(priced.receipt.receipt_digest.as_array());
        bytes.extend_from_slice(priced.realization.digest().as_array());
    }
    Ok(PromptPricingSetV1 {
        candidate_set_digest,
        prices,
        set_digest: Digest32::of_bytes(&bytes),
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairInteractionV1 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub marginal_gain_q32: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HardConstraintV1 {
    Conflict {
        left_factor_id: StableId,
        right_factor_id: StableId,
        support_digest: Digest32,
    },
    Requires {
        factor_id: StableId,
        prerequisite_factor_id: StableId,
        support_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortfolioSelectionRequestV1 {
    pub portfolio_id: StableId,
    pub token_budget: u32,
    pub maximum_selected_factors: usize,
    pub valid_until_unix_ms: u64,
    pub interactions: Vec<PairInteractionV1>,
    pub hard_constraints: Vec<HardConstraintV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub portfolio_id: StableId,
    pub candidate_set_digest: Digest32,
    pub factor_ids: Vec<StableId>,
    pub interaction_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptPortfolioReceiptV1 {
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        for (label, digest) in [
            ("portfolio candidate set", self.candidate_set_digest),
            ("portfolio interactions", self.interaction_digest),
            ("portfolio receipt", self.receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.factor_ids.len() > MAX_CANONICAL_SELECTED_FACTORS_V1 {
            return Err(CanonicalPromptError::InvalidPortfolioLimit);
        }
        require_sorted_unique_allow_empty(&self.factor_ids)?;
        if self.total_token_upper_bound > MAX_CANONICAL_TOKEN_BUDGET_V1
            || self.valid_until_unix_ms == 0
        {
            return Err(CanonicalPromptError::InvalidTokenBudget);
        }
        if self.authority.grants_any() {
            return Err(CanonicalPromptError::InvalidPricingValue(
                "portfolio receipt grants authority".to_string(),
            ));
        }
        if self.receipt_digest != Digest32::of_bytes(&self.semantic_json_bytes()?) {
            return Err(CanonicalPromptError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        self.validate()?;
        self.semantic_json_bytes()
    }

    pub fn from_canonical_json(bytes: &[u8]) -> Result<Self, CanonicalPromptError> {
        let wire: PortfolioWire = decode_canonical(bytes)?;
        let mut value = Self {
            portfolio_id: parse_id(&wire.portfolio_id)?,
            candidate_set_digest: parse_digest(&wire.candidate_set_digest)?,
            factor_ids: parse_ids(&wire.factor_ids)?,
            interaction_digest: parse_digest(&wire.interaction_digest)?,
            expected_utility_q32: FixedQ32::from_raw(wire.expected_utility_q32),
            total_token_upper_bound: wire.total_token_upper_bound,
            valid_until_unix_ms: wire.valid_until_unix_ms,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = Digest32::of_bytes(&value.semantic_json_bytes()?);
        value.validate()?;
        if value.semantic_json_bytes()? != bytes {
            return Err(CanonicalPromptError::NonCanonicalEncoding);
        }
        Ok(value)
    }

    fn semantic_json_bytes(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        encode(&PortfolioWire {
            portfolio_id: self.portfolio_id.to_string(),
            candidate_set_digest: self.candidate_set_digest.to_string(),
            factor_ids: ids_to_strings(&self.factor_ids),
            interaction_digest: self.interaction_digest.to_string(),
            expected_utility_q32: self.expected_utility_q32.raw(),
            total_token_upper_bound: self.total_token_upper_bound,
            valid_until_unix_ms: self.valid_until_unix_ms,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioSelectionMethodV1 {
    GreedyPrerequisiteBundleMarginalV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioOptimalityDisclosureV1 {
    HeuristicNoCertificate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortfolioSelectionTraceV1 {
    pub selected_realization_ids: Vec<StableId>,
    pub pricing_receipt_digests: Vec<Digest32>,
    pub selection_method: PortfolioSelectionMethodV1,
    pub optimality: PortfolioOptimalityDisclosureV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioBundleV1 {
    pub receipt: PromptPortfolioReceiptV1,
    pub trace: PortfolioSelectionTraceV1,
}

pub fn select_portfolio_v1(
    pricing: &PromptPricingSetV1,
    request: PortfolioSelectionRequestV1,
) -> Result<PromptPortfolioBundleV1, CanonicalPromptError> {
    if request.maximum_selected_factors == 0
        || request.maximum_selected_factors > MAX_CANONICAL_SELECTED_FACTORS_V1
    {
        return Err(CanonicalPromptError::InvalidPortfolioLimit);
    }
    if request.token_budget == 0 || request.token_budget > MAX_CANONICAL_TOKEN_BUDGET_V1 {
        return Err(CanonicalPromptError::InvalidTokenBudget);
    }
    if request.valid_until_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidValidityWindow);
    }
    if request.interactions.len() > MAX_CANONICAL_INTERACTIONS_V1 {
        return Err(CanonicalPromptError::InteractionLimitExceeded);
    }
    if request.hard_constraints.len() > MAX_CANONICAL_CONSTRAINTS_V1 {
        return Err(CanonicalPromptError::ConstraintLimitExceeded);
    }

    let factor_ids = pricing
        .prices
        .iter()
        .map(|priced| priced.receipt.factor_id.clone())
        .collect::<BTreeSet<_>>();
    if factor_ids.is_empty() || factor_ids.len() > MAX_CANONICAL_FACTORS_V1 {
        return Err(CanonicalPromptError::CandidateLimitExceeded);
    }
    let interactions = build_interaction_map(&request.interactions, &factor_ids)?;
    let constraints = ConstraintIndex::build(&request.hard_constraints, &factor_ids)?;
    let interaction_digest = digest_graph(&request.interactions, &request.hard_constraints);

    let mut selected = BTreeSet::new();
    let mut used_tokens = 0_u32;
    let mut total_utility = FixedQ32::ZERO;
    loop {
        let mut best: Option<BundleChoice> = None;
        for anchor in &factor_ids {
            if selected.contains(anchor) {
                continue;
            }
            let closure = prerequisite_closure(anchor, &constraints.requires)?;
            let additions = closure
                .difference(&selected)
                .cloned()
                .collect::<BTreeSet<_>>();
            if additions.is_empty()
                || selected.len().saturating_add(additions.len())
                    > request.maximum_selected_factors
                || conflicts_with(&selected, &additions, &constraints.conflicts)
            {
                continue;
            }
            let added_tokens = additions.iter().try_fold(0_u32, |total, factor_id| {
                let priced = pricing
                    .price_for(factor_id)
                    .ok_or_else(|| CanonicalPromptError::UnknownFactor(factor_id.to_string()))?;
                total
                    .checked_add(priced.receipt.token_cost)
                    .ok_or(CanonicalPromptError::Arithmetic)
            })?;
            if used_tokens
                .checked_add(added_tokens)
                .is_none_or(|value| value > request.token_budget)
            {
                continue;
            }
            let Some(marginal) = bundle_marginal(pricing, &selected, &additions, &interactions)? else {
                continue;
            };
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let choice = BundleChoice {
                anchor: anchor.clone(),
                additions,
                marginal,
                added_tokens,
            };
            let replace = best.as_ref().is_none_or(|current| {
                choice.marginal > current.marginal
                    || (choice.marginal == current.marginal
                        && (choice.added_tokens < current.added_tokens
                            || (choice.added_tokens == current.added_tokens
                                && choice.anchor < current.anchor)))
            });
            if replace {
                best = Some(choice);
            }
        }
        let Some(choice) = best else {
            break;
        };
        used_tokens = used_tokens
            .checked_add(choice.added_tokens)
            .ok_or(CanonicalPromptError::Arithmetic)?;
        total_utility = total_utility
            .checked_add(choice.marginal)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
        selected.extend(choice.additions);
    }

    let selected_ids = selected.iter().cloned().collect::<Vec<_>>();
    let mut valid_until = request.valid_until_unix_ms;
    let mut selected_realization_ids = Vec::with_capacity(selected_ids.len());
    let mut pricing_receipt_digests = Vec::with_capacity(selected_ids.len());
    for factor_id in &selected_ids {
        let priced = pricing
            .price_for(factor_id)
            .ok_or_else(|| CanonicalPromptError::UnknownFactor(factor_id.to_string()))?;
        if let Some(expires) = priced.realization.expires_unix_ms {
            valid_until = valid_until.min(expires);
        }
        selected_realization_ids.push(priced.realization.realization_id.clone());
        pricing_receipt_digests.push(priced.receipt.receipt_digest);
    }
    if valid_until == 0 {
        return Err(CanonicalPromptError::InvalidValidityWindow);
    }
    let mut receipt = PromptPortfolioReceiptV1 {
        portfolio_id: request.portfolio_id,
        candidate_set_digest: pricing.candidate_set_digest,
        factor_ids: selected_ids,
        interaction_digest,
        expected_utility_q32: total_utility,
        total_token_upper_bound: used_tokens,
        valid_until_unix_ms: valid_until,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = Digest32::of_bytes(&receipt.semantic_json_bytes()?);
    receipt.validate()?;
    Ok(PromptPortfolioBundleV1 {
        receipt,
        trace: PortfolioSelectionTraceV1 {
            selected_realization_ids,
            pricing_receipt_digests,
            selection_method: PortfolioSelectionMethodV1::GreedyPrerequisiteBundleMarginalV1,
            optimality: PortfolioOptimalityDisclosureV1::HeuristicNoCertificate,
        },
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DecisionBoundaryV1 {
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

impl DecisionBoundaryV1 {
    const fn as_str(self) -> &'static str {
        match self {
            Self::RequestAccepted => "request_accepted",
            Self::ObjectiveCompiled => "objective_compiled",
            Self::BeforePlanning => "before_planning",
            Self::BeforeCandidateGeneration => "before_candidate_generation",
            Self::BeforeModelOrToolDispatch => "before_model_or_tool_dispatch",
            Self::AfterObservation => "after_observation",
            Self::AfterFailureOrUncertaintySpike => "after_failure_or_uncertainty_spike",
            Self::BeforeIrreversibleMutation => "before_irreversible_mutation",
            Self::BeforeVerification => "before_verification",
            Self::BeforeFinalResponse => "before_final_response",
            Self::BeforeCompactOrHandoff => "before_compact_or_handoff",
        }
    }

    fn parse(value: &str) -> Result<Self, CanonicalPromptError> {
        match value {
            "request_accepted" => Ok(Self::RequestAccepted),
            "objective_compiled" => Ok(Self::ObjectiveCompiled),
            "before_planning" => Ok(Self::BeforePlanning),
            "before_candidate_generation" => Ok(Self::BeforeCandidateGeneration),
            "before_model_or_tool_dispatch" => Ok(Self::BeforeModelOrToolDispatch),
            "after_observation" => Ok(Self::AfterObservation),
            "after_failure_or_uncertainty_spike" => Ok(Self::AfterFailureOrUncertaintySpike),
            "before_irreversible_mutation" => Ok(Self::BeforeIrreversibleMutation),
            "before_verification" => Ok(Self::BeforeVerification),
            "before_final_response" => Ok(Self::BeforeFinalResponse),
            "before_compact_or_handoff" => Ok(Self::BeforeCompactOrHandoff),
            _ => Err(CanonicalPromptError::InvalidPricingValue(format!(
                "unknown decision boundary {value}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExerciseDispositionV1 {
    Exercise,
    Wait,
    Reject,
}

impl ExerciseDispositionV1 {
    const fn as_str(self) -> &'static str {
        match self {
            Self::Exercise => "exercise",
            Self::Wait => "wait",
            Self::Reject => "reject",
        }
    }

    fn parse(value: &str) -> Result<Self, CanonicalPromptError> {
        match value {
            "exercise" => Ok(Self::Exercise),
            "wait" => Ok(Self::Wait),
            "reject" => Ok(Self::Reject),
            _ => Err(CanonicalPromptError::InvalidPricingValue(format!(
                "unknown exercise decision {value}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub factor_or_portfolio_id: StableId,
    pub decision_boundary: DecisionBoundaryV1,
    pub exercise_now_value_q32: FixedQ32,
    pub wait_value_q32: FixedQ32,
    pub decision: ExerciseDispositionV1,
    pub policy_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptExerciseDecisionV1 {
    pub fn validate(&self) -> Result<(), CanonicalPromptError> {
        require_digest(self.policy_digest, "exercise policy")?;
        require_digest(self.receipt_digest, "exercise receipt")?;
        if self.authority.grants_any() {
            return Err(CanonicalPromptError::InvalidPricingValue(
                "exercise receipt grants authority".to_string(),
            ));
        }
        if self.receipt_digest != Digest32::of_bytes(&self.semantic_json_bytes()?) {
            return Err(CanonicalPromptError::ReceiptDigestMismatch);
        }
        Ok(())
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        self.validate()?;
        self.semantic_json_bytes()
    }

    pub fn from_canonical_json(bytes: &[u8]) -> Result<Self, CanonicalPromptError> {
        let wire: ExerciseWire = decode_canonical(bytes)?;
        let mut value = Self {
            factor_or_portfolio_id: parse_id(&wire.factor_or_portfolio_id)?,
            decision_boundary: DecisionBoundaryV1::parse(&wire.decision_boundary)?,
            exercise_now_value_q32: FixedQ32::from_raw(wire.exercise_now_value_q32),
            wait_value_q32: FixedQ32::from_raw(wire.wait_value_q32),
            decision: ExerciseDispositionV1::parse(&wire.decision)?,
            policy_digest: parse_digest(&wire.policy_digest)?,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.receipt_digest = Digest32::of_bytes(&value.semantic_json_bytes()?);
        value.validate()?;
        if value.semantic_json_bytes()? != bytes {
            return Err(CanonicalPromptError::NonCanonicalEncoding);
        }
        Ok(value)
    }

    fn semantic_json_bytes(&self) -> Result<Vec<u8>, CanonicalPromptError> {
        encode(&ExerciseWire {
            factor_or_portfolio_id: self.factor_or_portfolio_id.to_string(),
            decision_boundary: self.decision_boundary.as_str().to_string(),
            exercise_now_value_q32: self.exercise_now_value_q32.raw(),
            wait_value_q32: self.wait_value_q32.raw(),
            decision: self.decision.as_str().to_string(),
            policy_digest: self.policy_digest.to_string(),
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExerciseReasonV1 {
    CurrentAndPreferred,
    NoPositiveIntervention,
    WaitDominates,
    PortfolioExpired,
    ObjectiveDrift,
    StateDrift,
    GenerationDrift,
    ModelTupleDrift,
    RegistryDrift,
    RealizationDrift,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExerciseRequestV1 {
    pub decision_boundary: DecisionBoundaryV1,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub wait_value_q32: FixedQ32,
    pub policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseResultV1 {
    pub receipt: PromptExerciseDecisionV1,
    pub reason: ExerciseReasonV1,
}

pub fn exercise_v1(
    registry: &PromptRegistry,
    enumerated: &EnumeratedPromptCandidatesV1,
    pricing: &PromptPricingSetV1,
    portfolio: &PromptPortfolioBundleV1,
    request: ExerciseRequestV1,
) -> Result<PromptExerciseResultV1, CanonicalPromptError> {
    require_digest(request.objective_digest, "exercise objective")?;
    require_digest(request.state_digest, "exercise state")?;
    require_digest(request.generation_vector_digest, "exercise generation")?;
    require_digest(request.policy_digest, "exercise policy")?;
    if request.now_unix_ms == 0 {
        return Err(CanonicalPromptError::InvalidTime);
    }
    request.model_tuple.validate()?;
    let reason = if request.now_unix_ms >= portfolio.receipt.valid_until_unix_ms {
        ExerciseReasonV1::PortfolioExpired
    } else if request.objective_digest != enumerated.receipt.objective_digest {
        ExerciseReasonV1::ObjectiveDrift
    } else if request.state_digest != enumerated.receipt.state_digest {
        ExerciseReasonV1::StateDrift
    } else if request.generation_vector_digest
        != enumerated.registry_snapshot.generation_vector_digest
    {
        ExerciseReasonV1::GenerationDrift
    } else if request.model_tuple != enumerated.model_tuple {
        ExerciseReasonV1::ModelTupleDrift
    } else if registry
        .snapshot_v2(request.generation_vector_digest, &request.model_tuple)
        .map(|snapshot| snapshot != enumerated.registry_snapshot)
        .unwrap_or(true)
    {
        ExerciseReasonV1::RegistryDrift
    } else if !selected_realizations_still_live(
        registry,
        enumerated,
        pricing,
        portfolio,
        &request,
    ) {
        ExerciseReasonV1::RealizationDrift
    } else if portfolio.receipt.factor_ids.is_empty() {
        ExerciseReasonV1::NoPositiveIntervention
    } else if portfolio.receipt.expected_utility_q32 <= request.wait_value_q32 {
        ExerciseReasonV1::WaitDominates
    } else {
        ExerciseReasonV1::CurrentAndPreferred
    };
    let decision = match reason {
        ExerciseReasonV1::CurrentAndPreferred => ExerciseDispositionV1::Exercise,
        ExerciseReasonV1::NoPositiveIntervention | ExerciseReasonV1::WaitDominates => {
            ExerciseDispositionV1::Wait
        }
        ExerciseReasonV1::PortfolioExpired
        | ExerciseReasonV1::ObjectiveDrift
        | ExerciseReasonV1::StateDrift
        | ExerciseReasonV1::GenerationDrift
        | ExerciseReasonV1::ModelTupleDrift
        | ExerciseReasonV1::RegistryDrift
        | ExerciseReasonV1::RealizationDrift => ExerciseDispositionV1::Reject,
    };
    let mut receipt = PromptExerciseDecisionV1 {
        factor_or_portfolio_id: portfolio.receipt.portfolio_id.clone(),
        decision_boundary: request.decision_boundary,
        exercise_now_value_q32: portfolio.receipt.expected_utility_q32,
        wait_value_q32: request.wait_value_q32,
        decision,
        policy_digest: request.policy_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = Digest32::of_bytes(&receipt.semantic_json_bytes()?);
    receipt.validate()?;
    Ok(PromptExerciseResultV1 { receipt, reason })
}

fn selected_realizations_still_live(
    registry: &PromptRegistry,
    enumerated: &EnumeratedPromptCandidatesV1,
    pricing: &PromptPricingSetV1,
    portfolio: &PromptPortfolioBundleV1,
    request: &ExerciseRequestV1,
) -> bool {
    for factor_id in &portfolio.receipt.factor_ids {
        let Some(priced) = pricing.price_for(factor_id) else {
            return false;
        };
        let Ok(current) = registry.read_compatible_v2(
            &enumerated.registry_snapshot,
            request.generation_vector_digest,
            &request.model_tuple,
            request.now_unix_ms,
            vec![factor_id.clone()],
            u32::try_from(MAX_COMPATIBLE_REALIZATIONS_V2).unwrap_or(u32::MAX),
        ) else {
            return false;
        };
        if !current
            .bindings
            .iter()
            .any(|binding| binding.realization_id == priced.realization.realization_id)
        {
            return false;
        }
    }
    true
}

fn choose_realization(
    set: &CompatibleRealizationSetV2,
    factor_id: &StableId,
) -> Result<PromptRealizationBindingV2, CanonicalPromptError> {
    set.bindings
        .iter()
        .filter(|binding| &binding.factor_id == factor_id)
        .min_by(|left, right| {
            left.token_cost
                .cmp(&right.token_cost)
                .then_with(|| left.realization_id.cmp(&right.realization_id))
        })
        .cloned()
        .ok_or_else(|| CanonicalPromptError::UnknownFactor(factor_id.to_string()))
}

#[derive(Clone, Debug)]
struct ConstraintIndex {
    requires: BTreeMap<StableId, Vec<StableId>>,
    conflicts: BTreeSet<(StableId, StableId)>,
}

impl ConstraintIndex {
    fn build(
        constraints: &[HardConstraintV1],
        factors: &BTreeSet<StableId>,
    ) -> Result<Self, CanonicalPromptError> {
        let mut requires = BTreeMap::<StableId, Vec<StableId>>::new();
        let mut conflicts = BTreeSet::new();
        let mut keys = BTreeSet::new();
        for constraint in constraints {
            let (kind, left, right, support) = match constraint {
                HardConstraintV1::Conflict {
                    left_factor_id,
                    right_factor_id,
                    support_digest,
                } => (0_u8, left_factor_id, right_factor_id, *support_digest),
                HardConstraintV1::Requires {
                    factor_id,
                    prerequisite_factor_id,
                    support_digest,
                } => (1_u8, factor_id, prerequisite_factor_id, *support_digest),
            };
            require_digest(support, "constraint support")?;
            for endpoint in [left, right] {
                if !factors.contains(endpoint) {
                    return Err(CanonicalPromptError::UnknownFactor(endpoint.to_string()));
                }
            }
            if left == right {
                return Err(CanonicalPromptError::InvalidRelation(left.to_string()));
            }
            let key = (kind, left.clone(), right.clone());
            if !keys.insert(key) {
                return Err(CanonicalPromptError::DuplicateConstraint(
                    if kind == 0 { "conflict" } else { "requires" }.to_string(),
                    left.to_string(),
                    right.to_string(),
                ));
            }
            match constraint {
                HardConstraintV1::Conflict {
                    left_factor_id,
                    right_factor_id,
                    ..
                } => {
                    let pair = ordered_pair(left_factor_id, right_factor_id);
                    conflicts.insert(pair);
                }
                HardConstraintV1::Requires {
                    factor_id,
                    prerequisite_factor_id,
                    ..
                } => {
                    requires
                        .entry(factor_id.clone())
                        .or_default()
                        .push(prerequisite_factor_id.clone());
                }
            }
        }
        for values in requires.values_mut() {
            values.sort();
        }
        Ok(Self {
            requires,
            conflicts,
        })
    }
}

fn build_interaction_map(
    interactions: &[PairInteractionV1],
    factors: &BTreeSet<StableId>,
) -> Result<BTreeMap<(StableId, StableId), FixedQ32>, CanonicalPromptError> {
    let mut map = BTreeMap::new();
    for interaction in interactions {
        require_digest(interaction.support_digest, "interaction support")?;
        if interaction.left_factor_id >= interaction.right_factor_id {
            return Err(CanonicalPromptError::InvalidRelation(format!(
                "{}:{}",
                interaction.left_factor_id, interaction.right_factor_id
            )));
        }
        if !factors.contains(&interaction.left_factor_id) {
            return Err(CanonicalPromptError::UnknownFactor(
                interaction.left_factor_id.to_string(),
            ));
        }
        if !factors.contains(&interaction.right_factor_id) {
            return Err(CanonicalPromptError::UnknownFactor(
                interaction.right_factor_id.to_string(),
            ));
        }
        let key = (
            interaction.left_factor_id.clone(),
            interaction.right_factor_id.clone(),
        );
        if map.insert(key.clone(), interaction.marginal_gain_q32).is_some() {
            return Err(CanonicalPromptError::DuplicateInteraction(
                key.0.to_string(),
                key.1.to_string(),
            ));
        }
    }
    Ok(map)
}

fn prerequisite_closure(
    anchor: &StableId,
    requires: &BTreeMap<StableId, Vec<StableId>>,
) -> Result<BTreeSet<StableId>, CanonicalPromptError> {
    fn visit(
        value: &StableId,
        requires: &BTreeMap<StableId, Vec<StableId>>,
        visiting: &mut BTreeSet<StableId>,
        closed: &mut BTreeSet<StableId>,
    ) -> Result<(), CanonicalPromptError> {
        if closed.contains(value) {
            return Ok(());
        }
        if !visiting.insert(value.clone()) {
            return Err(CanonicalPromptError::PrerequisiteCycle(value.to_string()));
        }
        if let Some(prerequisites) = requires.get(value) {
            for prerequisite in prerequisites {
                visit(prerequisite, requires, visiting, closed)?;
            }
        }
        visiting.remove(value);
        closed.insert(value.clone());
        Ok(())
    }
    let mut visiting = BTreeSet::new();
    let mut closed = BTreeSet::new();
    visit(anchor, requires, &mut visiting, &mut closed)?;
    Ok(closed)
}

fn conflicts_with(
    selected: &BTreeSet<StableId>,
    additions: &BTreeSet<StableId>,
    conflicts: &BTreeSet<(StableId, StableId)>,
) -> bool {
    let mut combined = selected.clone();
    combined.extend(additions.iter().cloned());
    conflicts
        .iter()
        .any(|(left, right)| combined.contains(left) && combined.contains(right))
}

fn bundle_marginal(
    pricing: &PromptPricingSetV1,
    selected: &BTreeSet<StableId>,
    additions: &BTreeSet<StableId>,
    interactions: &BTreeMap<(StableId, StableId), FixedQ32>,
) -> Result<Option<FixedQ32>, CanonicalPromptError> {
    let mut marginal = FixedQ32::ZERO;
    for factor_id in additions {
        let priced = pricing
            .price_for(factor_id)
            .ok_or_else(|| CanonicalPromptError::UnknownFactor(factor_id.to_string()))?;
        marginal = marginal
            .checked_add(priced.receipt.expected_utility_q32)
            .map_err(|_| CanonicalPromptError::Arithmetic)?;
    }
    let mut combined = selected.clone();
    combined.extend(additions.iter().cloned());
    let values = combined.iter().collect::<Vec<_>>();
    for (index, left) in values.iter().enumerate() {
        for right in values.iter().skip(index + 1) {
            if !additions.contains(*left) && !additions.contains(*right) {
                continue;
            }
            let key = ((*left).clone(), (*right).clone());
            let Some(interaction) = interactions.get(&key) else {
                // Missing pair evidence makes this combination unavailable; it is
                // never silently interpreted as zero interaction.
                return Ok(None);
            };
            marginal = marginal
                .checked_add(*interaction)
                .map_err(|_| CanonicalPromptError::Arithmetic)?;
        }
    }
    Ok(Some(marginal))
}

#[derive(Clone, Debug)]
struct BundleChoice {
    anchor: StableId,
    additions: BTreeSet<StableId>,
    marginal: FixedQ32,
    added_tokens: u32,
}

fn digest_graph(interactions: &[PairInteractionV1], constraints: &[HardConstraintV1]) -> Digest32 {
    let mut interactions = interactions.to_vec();
    interactions.sort_by(|left, right| {
        (&left.left_factor_id, &left.right_factor_id)
            .cmp(&(&right.left_factor_id, &right.right_factor_id))
    });
    let mut constraints = constraints.to_vec();
    constraints.sort_by(|left, right| constraint_key(left).cmp(&constraint_key(right)));
    let mut bytes = b"hepta.prompt-optimizer.portfolio-graph.v1".to_vec();
    for interaction in interactions {
        bytes.push(0);
        push_id(&mut bytes, &interaction.left_factor_id);
        push_id(&mut bytes, &interaction.right_factor_id);
        bytes.extend_from_slice(&interaction.marginal_gain_q32.raw().to_be_bytes());
        bytes.extend_from_slice(interaction.support_digest.as_array());
    }
    for constraint in constraints {
        match constraint {
            HardConstraintV1::Conflict {
                left_factor_id,
                right_factor_id,
                support_digest,
            } => {
                bytes.push(1);
                let (left, right) = ordered_pair(&left_factor_id, &right_factor_id);
                push_id(&mut bytes, &left);
                push_id(&mut bytes, &right);
                bytes.extend_from_slice(support_digest.as_array());
            }
            HardConstraintV1::Requires {
                factor_id,
                prerequisite_factor_id,
                support_digest,
            } => {
                bytes.push(2);
                push_id(&mut bytes, &factor_id);
                push_id(&mut bytes, &prerequisite_factor_id);
                bytes.extend_from_slice(support_digest.as_array());
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

fn constraint_key(value: &HardConstraintV1) -> (u8, StableId, StableId) {
    match value {
        HardConstraintV1::Conflict {
            left_factor_id,
            right_factor_id,
            ..
        } => {
            let (left, right) = ordered_pair(left_factor_id, right_factor_id);
            (0, left, right)
        }
        HardConstraintV1::Requires {
            factor_id,
            prerequisite_factor_id,
            ..
        } => (1, factor_id.clone(), prerequisite_factor_id.clone()),
    }
}

fn ordered_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left < right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

fn scale_fixed_u64(value: FixedQ32, multiplier: u64) -> Result<FixedQ32, CanonicalPromptError> {
    let product = i128::from(value.raw())
        .checked_mul(i128::from(multiplier))
        .ok_or(CanonicalPromptError::Arithmetic)?;
    let raw = i64::try_from(product).map_err(|_| CanonicalPromptError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

fn scale_fixed_ppm(value: FixedQ32, ppm: u32) -> Result<FixedQ32, CanonicalPromptError> {
    let product = i128::from(value.raw())
        .checked_mul(i128::from(ppm))
        .ok_or(CanonicalPromptError::Arithmetic)?;
    let raw = i64::try_from(product / PPM_SCALE).map_err(|_| CanonicalPromptError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

fn require_digest(value: Digest32, label: &'static str) -> Result<(), CanonicalPromptError> {
    if value.is_zero() {
        return Err(CanonicalPromptError::EmptyDigest(label));
    }
    Ok(())
}

fn require_sorted_unique(values: &[StableId]) -> Result<(), CanonicalPromptError> {
    if values.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(CanonicalPromptError::CanonicalOrder);
    }
    Ok(())
}

fn require_sorted_unique_allow_empty(values: &[StableId]) -> Result<(), CanonicalPromptError> {
    require_sorted_unique(values)
}

fn digest_ids(domain: &[u8], values: &[StableId]) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&u64::try_from(values.len()).unwrap_or(u64::MAX).to_be_bytes());
    for value in values {
        push_id(&mut bytes, value);
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn ids_to_strings(values: &[StableId]) -> Vec<String> {
    values.iter().map(ToString::to_string).collect()
}

fn parse_ids(values: &[String]) -> Result<Vec<StableId>, CanonicalPromptError> {
    values.iter().map(|value| parse_id(value)).collect()
}

fn parse_id(value: &str) -> Result<StableId, CanonicalPromptError> {
    StableId::new(value.to_string())
        .map_err(|_| CanonicalPromptError::InvalidIdentifier(value.to_string()))
}

fn parse_digest(value: &str) -> Result<Digest32, CanonicalPromptError> {
    Digest32::from_str(value).map_err(|_| CanonicalPromptError::Json("invalid digest".to_string()))
}

fn encode<T: Serialize>(value: &T) -> Result<Vec<u8>, CanonicalPromptError> {
    serde_json::to_vec(value).map_err(|error| CanonicalPromptError::Json(error.to_string()))
}

fn decode_canonical<'a, T: Deserialize<'a>>(bytes: &'a [u8]) -> Result<T, CanonicalPromptError> {
    serde_json::from_slice(bytes).map_err(|error| CanonicalPromptError::Json(error.to_string()))
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CandidateSetWire {
    set_id: String,
    objective_digest: String,
    state_digest: String,
    registry_digest: String,
    candidate_factor_ids: Vec<String>,
    selection_grammar_digest: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ConfidenceWire {
    lower_q32: i64,
    upper_q32: i64,
    causal_estimate_digest: String,
    ndu_utility_digest: String,
    support_audit_digest: String,
    pricing_policy_digest: String,
    realization_digest: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PricingWire {
    factor_id: String,
    state_digest: String,
    expected_utility_q32: i64,
    downside_q32: i64,
    token_cost: u32,
    latency_cost_micros: u64,
    interference_ppm: u32,
    confidence_interval: ConfidenceWire,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PortfolioWire {
    portfolio_id: String,
    candidate_set_digest: String,
    factor_ids: Vec<String>,
    interaction_digest: String,
    expected_utility_q32: i64,
    total_token_upper_bound: u32,
    valid_until_unix_ms: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ExerciseWire {
    factor_or_portfolio_id: String,
    decision_boundary: String,
    exercise_now_value_q32: i64,
    wait_value_q32: i64,
    decision: String,
    policy_digest: String,
}

#[cfg(test)]
#[path = "canonical_v1_tests.rs"]
mod tests;
