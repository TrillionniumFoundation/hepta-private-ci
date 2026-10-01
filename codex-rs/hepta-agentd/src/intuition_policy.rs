//! Agentd-owned intuition.policy product boundary.
//!
//! The host authenticates generator/evaluator/observer evidence, pins the full
//! selected policy profile, and prepares the exact durable Decision. A separate
//! generator signature is verified by the sole `LedgerWriter` during commit.
//! Neither a prepared value nor a committed receipt grants effect authority.

#[path = "intuition_policy_binding.rs"]
mod binding;
#[path = "intuition_policy_final_use.rs"]
mod final_use;

pub use binding::intuition_policy_record_id_v1;
pub use binding::intuition_risk_rule_digest_v1;
use binding::*;
pub use final_use::IntuitionPolicyClock;
pub use final_use::IntuitionPolicyLearningSink;
pub use final_use::SystemIntuitionPolicyClock;
use final_use::validate_prepared_time;

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence::AuthenticatedIntuitionDecisionV2;
use codex_hepta_intelligence::AuthenticatedIntuitionDecisionV3;
use codex_hepta_intelligence::IntuitionQualificationError;
use codex_hepta_intelligence::IntuitionQualificationErrorV3;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intelligence::decide_authenticated_intuition_v2;
use codex_hepta_intelligence::decide_authenticated_intuition_v3;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::PolicyGeneration;
use codex_hepta_intuition::ProductionDispositionV1;
use codex_hepta_intuition::ScoringCommitmentV1;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// The pure kernel accepts 128 actions. Product learning reserves one of the
/// ledger's 128 candidate slots for its explicit abstain option.
pub const MAX_PRODUCT_INTUITION_CANDIDATES: usize = 127;

/// Immutable owner identities admitted by the historical Agentd composition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionPolicyPinsV1 {
    pub model_artifact_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub rng_owner_digest: Option<Digest32>,
}

/// Complete product pins. A valid evaluator signature does not grant authority
/// to silently replace any host-selected policy semantics.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionPolicyPinsV2 {
    pub policy_profile_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: PolicyGeneration,
    pub objective_class_digest: Digest32,
    pub model_artifact_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub risk_rule_digest: Digest32,
    pub rng_owner_digest: Option<Digest32>,
}

struct AgentdIntuitionProductRuntimeV1 {
    pins: AgentdIntuitionPolicyPinsV2,
    learning: Arc<IntuitionPolicyLearningSink>,
}

pub struct AgentdIntuitionPolicyHostV1 {
    agent_id: AgentId,
    spawn_generation: u64,
    verifier: Arc<LearningEvidenceVerifierV1>,
    legacy_pins: AgentdIntuitionPolicyPinsV1,
    product: Option<AgentdIntuitionProductRuntimeV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionDecisionReceiptV1 {
    pub decision: AuthenticatedIntuitionDecisionV2,
    pub host_binding_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct OwnedIntuitionQualificationEvidenceV2 {
    completeness: SignedLearningEvidenceV1,
    profile_qualification: SignedLearningEvidenceV1,
    runtime: SignedLearningEvidenceV1,
}

impl OwnedIntuitionQualificationEvidenceV2 {
    fn from_borrowed(value: IntuitionQualificationEvidenceV2<'_>) -> Self {
        Self {
            completeness: value.completeness.clone(),
            profile_qualification: value.profile_qualification.clone(),
            runtime: value.runtime.clone(),
        }
    }

    fn as_borrowed(&self) -> IntuitionQualificationEvidenceV2<'_> {
        IntuitionQualificationEvidenceV2 {
            completeness: &self.completeness,
            profile_qualification: &self.profile_qualification,
            runtime: &self.runtime,
        }
    }

    fn earliest_expiry(&self) -> u64 {
        self.completeness
            .expires_at
            .min(self.profile_qualification.expires_at)
            .min(self.runtime.expires_at)
    }
}

/// Non-dispatchable result of authenticated policy preparation. It owns the
/// original request and all three signed qualification records so final use can
/// revalidate exact bytes against the current writer-owned trust distribution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedAgentdIntuitionDecisionV3 {
    decision: AuthenticatedIntuitionDecisionV3,
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV2,
    assignment: AssignmentCommitmentV2,
    qualification: OwnedIntuitionQualificationEvidenceV2,
    host_binding_digest: Digest32,
    production: Option<ProductionDecisionV2>,
    owner_agent_id: AgentId,
    owner_spawn_generation: u64,
    owner_trust_digest: Digest32,
    owner_trust_generation: u64,
    owner_trust_distribution_digest: Digest32,
    prepared_at: u64,
    qualification_expires_at: u64,
    prepared_digest: Digest32,
}

impl PreparedAgentdIntuitionDecisionV3 {
    #[must_use]
    pub fn decision(&self) -> &AuthenticatedIntuitionDecisionV3 {
        &self.decision
    }

    #[must_use]
    pub fn host_binding_digest(&self) -> Digest32 {
        self.host_binding_digest
    }

    #[must_use]
    pub fn production_decision(&self) -> Option<&ProductionDecisionV2> {
        self.production.as_ref()
    }

    #[must_use]
    pub fn prepared_digest(&self) -> Digest32 {
        self.prepared_digest
    }

    pub fn decision_signing_payload(&self) -> Result<Option<Vec<u8>>, AgentdIntuitionPolicyError> {
        self.production
            .as_ref()
            .map(decision_signing_payload_v2)
            .transpose()
            .map_err(AgentdIntuitionPolicyError::Learning)
    }
}

/// Final product receipt. A selected result always contains a durable append.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionDecisionReceiptV2 {
    pub decision: AuthenticatedIntuitionDecisionV3,
    pub host_binding_digest: Digest32,
    pub production_record_id: Option<StableId>,
    pub learning: Option<AppendReceipt>,
    pub service_receipt_digest: Digest32,
}

#[derive(Debug)]
pub enum AgentdIntuitionPolicyError {
    InvalidHost(&'static str),
    GenerationFence,
    ModelPinMismatch,
    ScorerPinMismatch,
    RngOwnerPinMismatch,
    ProfilePinMismatch,
    PolicyPinMismatch,
    ObjectiveClassPinMismatch,
    CalibrationPinMismatch,
    OodPinMismatch,
    RiskRulePinMismatch,
    ProductHostRequired,
    ProductCandidateLimit,
    EmptyRunSnapshot,
    InvalidEpisode,
    SelectedPropensityMissing,
    PreparedOwnerMismatch,
    PreparedProfileMismatch,
    PreparedQualificationMismatch,
    PreparedEvidenceExpired,
    PreparedClockReversed,
    TrustedClockUnavailable,
    TrustedClockReversed,
    TrustRotation(codex_hepta_learning_ledger::LearningTrustDistributionError),
    MissingDecisionEvidence,
    UnexpectedDecisionEvidence,
    Qualification(IntuitionQualificationError),
    QualificationV3(IntuitionQualificationErrorV3),
    LearningLockPoisoned,
    Learning(ProductionLedgerError),
    IndeterminateAfterLedgerCommit { receipt: AppendReceipt },
}

impl AgentdIntuitionPolicyError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidHost(_) => "agentd.intuition.invalid_host",
            Self::GenerationFence => "agentd.intuition.generation_fenced",
            Self::ModelPinMismatch => "agentd.intuition.pin.model_mismatch",
            Self::ScorerPinMismatch => "agentd.intuition.pin.scorer_mismatch",
            Self::RngOwnerPinMismatch => "agentd.intuition.pin.rng_owner_mismatch",
            Self::ProfilePinMismatch => "agentd.intuition.pin.profile_mismatch",
            Self::PolicyPinMismatch => "agentd.intuition.pin.policy_mismatch",
            Self::ObjectiveClassPinMismatch => "agentd.intuition.pin.objective_class_mismatch",
            Self::CalibrationPinMismatch => "agentd.intuition.pin.calibration_mismatch",
            Self::OodPinMismatch => "agentd.intuition.pin.ood_mismatch",
            Self::RiskRulePinMismatch => "agentd.intuition.pin.risk_rule_mismatch",
            Self::ProductHostRequired => "agentd.intuition.product_host_required",
            Self::ProductCandidateLimit => "agentd.intuition.product_candidate_limit",
            Self::EmptyRunSnapshot => "agentd.intuition.empty_run_snapshot",
            Self::InvalidEpisode => "agentd.intuition.invalid_episode",
            Self::SelectedPropensityMissing => "agentd.intuition.selected_propensity_missing",
            Self::PreparedOwnerMismatch => "agentd.intuition.prepared_owner_mismatch",
            Self::PreparedProfileMismatch => "agentd.intuition.prepared_profile_mismatch",
            Self::PreparedQualificationMismatch => {
                "agentd.intuition.prepared_qualification_mismatch"
            }
            Self::PreparedEvidenceExpired => "agentd.intuition.prepared_evidence_expired",
            Self::PreparedClockReversed => "agentd.intuition.prepared_clock_reversed",
            Self::TrustedClockUnavailable => "agentd.intuition.trusted_clock_unavailable",
            Self::TrustedClockReversed => "agentd.intuition.trusted_clock_reversed",
            Self::TrustRotation(_) => "agentd.intuition.trust_rotation_rejected",
            Self::MissingDecisionEvidence => "agentd.intuition.missing_decision_evidence",
            Self::UnexpectedDecisionEvidence => "agentd.intuition.unexpected_decision_evidence",
            Self::Qualification(_) => "agentd.intuition.legacy_qualification_rejected",
            Self::QualificationV3(source) => source.code(),
            Self::LearningLockPoisoned => "agentd.intuition.learning_lock_poisoned",
            Self::Learning(_) => "agentd.intuition.learning_append_rejected",
            Self::IndeterminateAfterLedgerCommit { .. } => {
                "agentd.intuition.learning_indeterminate_after_commit"
            }
        }
    }
}

impl fmt::Display for AgentdIntuitionPolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl StdError for AgentdIntuitionPolicyError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Qualification(source) => Some(source),
            Self::QualificationV3(source) => Some(source),
            Self::Learning(source) => Some(source),
            Self::TrustRotation(source) => Some(source),
            _ => None,
        }
    }
}

impl From<IntuitionQualificationError> for AgentdIntuitionPolicyError {
    fn from(value: IntuitionQualificationError) -> Self {
        Self::Qualification(value)
    }
}

impl From<IntuitionQualificationErrorV3> for AgentdIntuitionPolicyError {
    fn from(value: IntuitionQualificationErrorV3) -> Self {
        Self::QualificationV3(value)
    }
}

impl AgentdIntuitionPolicyHostV1 {
    /// Historical constructor retained for replay/migration only.
    pub fn new(
        agent_id: AgentId,
        spawn_generation: u64,
        verifier: Arc<LearningEvidenceVerifierV1>,
        pins: AgentdIntuitionPolicyPinsV1,
    ) -> Result<Self, AgentdIntuitionPolicyError> {
        validate_legacy_pins(spawn_generation, &pins)?;
        Ok(Self {
            agent_id,
            spawn_generation,
            verifier,
            legacy_pins: pins,
            product: None,
        })
    }

    /// Current product constructor. Policy and ledger verification must use the
    /// same immutable trust snapshot.
    pub fn new_product(
        agent_id: AgentId,
        spawn_generation: u64,
        verifier: Arc<LearningEvidenceVerifierV1>,
        pins: AgentdIntuitionPolicyPinsV2,
        learning: Arc<IntuitionPolicyLearningSink>,
    ) -> Result<Self, AgentdIntuitionPolicyError> {
        validate_product_pins(spawn_generation, &pins)?;
        if learning.trust_identity()?.0 != verifier.trust_digest() {
            return Err(AgentdIntuitionPolicyError::InvalidHost(
                "policy and ledger trust snapshots differ",
            ));
        }
        let legacy_pins = AgentdIntuitionPolicyPinsV1 {
            model_artifact_digest: pins.model_artifact_digest,
            scorer_contract_digest: pins.scorer_contract_digest,
            rng_owner_digest: pins.rng_owner_digest,
        };
        Ok(Self {
            agent_id,
            spawn_generation,
            verifier,
            legacy_pins,
            product: Some(AgentdIntuitionProductRuntimeV1 { pins, learning }),
        })
    }

    pub fn require_identity(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
    ) -> Result<(), AgentdIntuitionPolicyError> {
        if agent_id != &self.agent_id || spawn_generation != self.spawn_generation {
            return Err(AgentdIntuitionPolicyError::GenerationFence);
        }
        Ok(())
    }

    #[must_use]
    pub fn is_product_ready(&self) -> bool {
        self.product.is_some()
    }

    /// Historical authenticated V2 path. Product serving uses prepare/commit V3.
    #[allow(clippy::too_many_arguments)]
    pub fn decide(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scoring: ScoringCommitmentV1,
        assignment: AssignmentCommitmentV1,
        evidence: IntuitionQualificationEvidenceV2<'_>,
        now: u64,
    ) -> Result<AgentdIntuitionDecisionReceiptV1, AgentdIntuitionPolicyError> {
        self.require_identity(agent_id, spawn_generation)?;
        if profile.scorer.model_digest != self.legacy_pins.model_artifact_digest
            || scoring.model_artifact_digest != self.legacy_pins.model_artifact_digest
        {
            return Err(AgentdIntuitionPolicyError::ModelPinMismatch);
        }
        if profile.scorer.scorer_contract_digest != self.legacy_pins.scorer_contract_digest
            || scoring.scorer_contract_digest != self.legacy_pins.scorer_contract_digest
        {
            return Err(AgentdIntuitionPolicyError::ScorerPinMismatch);
        }
        match (&assignment, self.legacy_pins.rng_owner_digest) {
            (AssignmentCommitmentV1::Deterministic, _) => {}
            (
                AssignmentCommitmentV1::CounterBased {
                    rng_owner_digest, ..
                },
                Some(expected),
            ) if *rng_owner_digest == expected => {}
            (AssignmentCommitmentV1::CounterBased { .. }, _) => {
                return Err(AgentdIntuitionPolicyError::RngOwnerPinMismatch);
            }
        }
        let decision = decide_authenticated_intuition_v2(
            request,
            profile,
            scoring,
            assignment,
            evidence,
            &self.verifier,
            now,
        )?;
        let host_binding_digest = legacy_host_binding_digest(
            &self.agent_id,
            self.spawn_generation,
            self.verifier.trust_digest(),
            &self.legacy_pins,
            decision.authentication_digest,
        );
        Ok(AgentdIntuitionDecisionReceiptV1 {
            decision,
            host_binding_digest,
        })
    }

    /// Authenticate and prepare the exact durable Decision. No ledger mutation
    /// or effect authority is issued by this phase.
    #[allow(clippy::too_many_arguments)]
    pub fn prepare_v3(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        request: CalibratedDecisionRequestV1,
        profile: CanonicalPolicyProfileV1,
        scoring: ScoringCommitmentV2,
        assignment: AssignmentCommitmentV2,
        qualification: IntuitionQualificationEvidenceV2<'_>,
        episode_id: StableId,
        run_snapshot_digest: Digest32,
        now: u64,
    ) -> Result<PreparedAgentdIntuitionDecisionV3, AgentdIntuitionPolicyError> {
        self.require_identity(agent_id, spawn_generation)?;
        if request.candidates.len() > MAX_PRODUCT_INTUITION_CANDIDATES {
            return Err(AgentdIntuitionPolicyError::ProductCandidateLimit);
        }
        if run_snapshot_digest.is_zero() {
            return Err(AgentdIntuitionPolicyError::EmptyRunSnapshot);
        }
        if episode_id.as_str().is_empty() {
            return Err(AgentdIntuitionPolicyError::InvalidEpisode);
        }
        let product = self
            .product
            .as_ref()
            .ok_or(AgentdIntuitionPolicyError::ProductHostRequired)?;
        validate_current_pins(&product.pins, &request, &profile, &scoring, &assignment)?;
        let qualification = OwnedIntuitionQualificationEvidenceV2::from_borrowed(qualification);
        let generator_id = qualification.completeness.principal_id.clone();
        let qualification_expires_at = qualification.earliest_expiry();
        validate_prepared_time(now, qualification_expires_at, now)?;
        let (owner_trust_digest, owner_trust_generation, owner_trust_distribution_digest) =
            product.learning.trust_identity()?;
        if owner_trust_digest != self.verifier.trust_digest() {
            return Err(AgentdIntuitionPolicyError::PreparedOwnerMismatch);
        }
        let decision = decide_authenticated_intuition_v3(
            request.clone(),
            profile.clone(),
            scoring.clone(),
            assignment.clone(),
            qualification.as_borrowed(),
            &self.verifier,
            now,
        )?;
        let host_binding_digest = product_host_binding_digest(
            &self.agent_id,
            self.spawn_generation,
            owner_trust_digest,
            &product.pins,
            decision.authentication_digest,
        );
        let production = production_decision_from_authenticated(
            &self.agent_id,
            self.spawn_generation,
            &request,
            &decision,
            generator_id,
            episode_id,
            run_snapshot_digest,
            host_binding_digest,
        )?;
        let mut bytes = b"hepta.agentd.prepared-intuition.v3\0".to_vec();
        bytes.extend_from_slice(host_binding_digest.as_array());
        bytes.extend_from_slice(decision.authentication_digest.as_array());
        bytes.extend_from_slice(&now.to_be_bytes());
        bytes.extend_from_slice(&qualification_expires_at.to_be_bytes());
        bytes.extend_from_slice(&owner_trust_generation.to_be_bytes());
        bytes.extend_from_slice(owner_trust_distribution_digest.as_array());
        match &production {
            Some(value) => {
                bytes.push(1);
                let payload = decision_signing_payload_v2(value)
                    .map_err(AgentdIntuitionPolicyError::Learning)?;
                bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
            }
            None => bytes.push(0),
        }
        Ok(PreparedAgentdIntuitionDecisionV3 {
            decision,
            request,
            profile,
            scoring,
            assignment,
            qualification,
            host_binding_digest,
            production,
            owner_agent_id: self.agent_id.clone(),
            owner_spawn_generation: self.spawn_generation,
            owner_trust_digest,
            owner_trust_generation,
            owner_trust_distribution_digest,
            prepared_at: now,
            qualification_expires_at,
            prepared_digest: Digest32::of_bytes(&bytes),
        })
    }

    /// Final-use commit. The caller supplies no time or trust snapshot: the
    /// sole writer lock owns both immediately before signature revalidation and
    /// the durable append.
    pub fn commit_v4(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionPolicyError> {
        self.require_identity(agent_id, spawn_generation)?;
        let product = self
            .product
            .as_ref()
            .ok_or(AgentdIntuitionPolicyError::ProductHostRequired)?;
        product.learning.commit_prepared(
            agent_id,
            spawn_generation,
            &product.pins,
            prepared,
            expected_ledger_head,
            decision_evidence,
        )
    }

    /// Canonical serving adds its current owner and ingress fences while the
    /// sole learning writer is locked. Historical public host calls retain
    /// their existing signature and error type.
    #[allow(
        clippy::result_large_err,
        reason = "The checked seam preserves the public service error payload and complete acknowledged receipts"
    )]
    pub(crate) fn commit_v4_checked<F>(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        final_use: F,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, crate::AgentdIntuitionServiceErrorV1>
    where
        F: FnOnce(
            &dyn crate::IntuitionPolicyClock,
        ) -> Result<(), crate::AgentdIntuitionServiceErrorV1>,
    {
        self.require_identity(agent_id, spawn_generation)?;
        let product = self
            .product
            .as_ref()
            .ok_or(AgentdIntuitionPolicyError::ProductHostRequired)?;
        product.learning.commit_prepared_checked(
            agent_id,
            spawn_generation,
            &product.pins,
            prepared,
            expected_ledger_head,
            decision_evidence,
            final_use,
        )
    }

    /// Historical call signature retained; final-use time is always writer-owned.
    #[deprecated(note = "use commit_v4; final-use time is writer-owned")]
    pub fn commit_v3(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        _now: u64,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionPolicyError> {
        self.commit_v4(
            agent_id,
            spawn_generation,
            prepared,
            expected_ledger_head,
            decision_evidence,
        )
    }
}

#[cfg(test)]
#[path = "intuition_policy_tests.rs"]
mod tests;
