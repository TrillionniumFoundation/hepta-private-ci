//! Agentd-owned intuition.policy product boundary.
//!
//! The host authenticates generator/evaluator/observer evidence, pins the full
//! selected policy profile, and prepares the exact durable Decision.  A separate
//! generator signature is then verified by the sole `LedgerWriter` during
//! commit.  Prepared values are advisory and cannot be dispatched; only a
//! committed receipt may cross the physical execution boundary.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

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
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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

/// Sole Agentd-owned durable Decision sink for this module.
pub struct IntuitionPolicyLearningSink {
    writer: Mutex<LedgerWriter>,
}

impl IntuitionPolicyLearningSink {
    #[must_use]
    pub fn new(writer: LedgerWriter) -> Self {
        Self {
            writer: Mutex::new(writer),
        }
    }

    pub fn trust_digest(&self) -> Result<Digest32, AgentdIntuitionPolicyError> {
        let writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        Ok(writer.verifier().trust_digest())
    }

    fn append_decision(
        &self,
        expected_predecessor: Digest32,
        request: ProductionDecisionV2,
        evidence: SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<AppendReceipt, AgentdIntuitionPolicyError> {
        let mut writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        match writer.append_decision(expected_predecessor, request, evidence, now) {
            Ok(receipt) => Ok(receipt),
            Err(ProductionLedgerError::IndeterminateAfterLedgerCommit {
                receipt,
                witness_error: _,
            }) => Err(AgentdIntuitionPolicyError::IndeterminateAfterLedgerCommit { receipt }),
            Err(error) => Err(AgentdIntuitionPolicyError::Learning(error)),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionDecisionReceiptV1 {
    pub decision: AuthenticatedIntuitionDecisionV2,
    pub host_binding_digest: Digest32,
}

/// Non-dispatchable result of authenticated policy preparation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedAgentdIntuitionDecisionV3 {
    decision: AuthenticatedIntuitionDecisionV3,
    host_binding_digest: Digest32,
    production: Option<ProductionDecisionV2>,
    owner_agent_id: AgentId,
    owner_spawn_generation: u64,
    owner_trust_digest: Digest32,
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
    EmptyRunSnapshot,
    InvalidEpisode,
    SelectedPropensityMissing,
    PreparedOwnerMismatch,
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
            Self::EmptyRunSnapshot => "agentd.intuition.empty_run_snapshot",
            Self::InvalidEpisode => "agentd.intuition.invalid_episode",
            Self::SelectedPropensityMissing => "agentd.intuition.selected_propensity_missing",
            Self::PreparedOwnerMismatch => "agentd.intuition.prepared_owner_mismatch",
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
        if learning.trust_digest()? != verifier.trust_digest() {
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
        let generator_id = qualification.completeness.principal_id.clone();
        let decision = decide_authenticated_intuition_v3(
            request.clone(),
            profile,
            scoring,
            assignment,
            qualification,
            &self.verifier,
            now,
        )?;
        let host_binding_digest = product_host_binding_digest(
            &self.agent_id,
            self.spawn_generation,
            self.verifier.trust_digest(),
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
        let mut bytes = b"hepta.agentd.prepared-intuition.v1\0".to_vec();
        bytes.extend_from_slice(host_binding_digest.as_array());
        bytes.extend_from_slice(decision.authentication_digest.as_array());
        match &production {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(
                    Digest32::of_bytes(&decision_signing_payload_v2(value)?).as_array(),
                );
            }
            None => bytes.push(0),
        }
        Ok(PreparedAgentdIntuitionDecisionV3 {
            decision,
            host_binding_digest,
            production,
            owner_agent_id: self.agent_id.clone(),
            owner_spawn_generation: self.spawn_generation,
            owner_trust_digest: self.verifier.trust_digest(),
            prepared_digest: Digest32::of_bytes(&bytes),
        })
    }

    /// Verify the exact generator signature and durably append the prepared
    /// Decision. A selected decision without an append never returns success.
    pub fn commit_v3(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
        now: u64,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionPolicyError> {
        self.require_identity(agent_id, spawn_generation)?;
        let product = self
            .product
            .as_ref()
            .ok_or(AgentdIntuitionPolicyError::ProductHostRequired)?;
        if prepared.owner_agent_id != self.agent_id
            || prepared.owner_spawn_generation != self.spawn_generation
            || prepared.owner_trust_digest != self.verifier.trust_digest()
        {
            return Err(AgentdIntuitionPolicyError::PreparedOwnerMismatch);
        }

        let (production_record_id, learning) = match (prepared.production, decision_evidence) {
            (Some(production), Some(evidence)) => {
                let record_id = production.record_id.clone();
                let receipt = product.learning.append_decision(
                    expected_ledger_head,
                    production,
                    evidence,
                    now,
                )?;
                (Some(record_id), Some(receipt))
            }
            (Some(_), None) => return Err(AgentdIntuitionPolicyError::MissingDecisionEvidence),
            (None, Some(_)) => {
                return Err(AgentdIntuitionPolicyError::UnexpectedDecisionEvidence);
            }
            (None, None) => (None, None),
        };

        let mut bytes = b"hepta.agentd.committed-intuition.v1\0".to_vec();
        bytes.extend_from_slice(prepared.prepared_digest.as_array());
        match &learning {
            Some(receipt) => {
                bytes.push(1);
                bytes.extend_from_slice(receipt.event_digest.as_array());
                bytes.extend_from_slice(receipt.chain_digest.as_array());
                bytes.extend_from_slice(&receipt.sequence.get().to_be_bytes());
            }
            None => bytes.push(0),
        }
        Ok(AgentdIntuitionDecisionReceiptV2 {
            decision: prepared.decision,
            host_binding_digest: prepared.host_binding_digest,
            production_record_id,
            learning,
            service_receipt_digest: Digest32::of_bytes(&bytes),
        })
    }
}

#[allow(clippy::too_many_arguments)]
fn production_decision_from_authenticated(
    agent_id: &AgentId,
    spawn_generation: u64,
    request: &CalibratedDecisionRequestV1,
    decision: &AuthenticatedIntuitionDecisionV3,
    generator_id: StableId,
    episode_id: StableId,
    run_snapshot_digest: Digest32,
    host_binding_digest: Digest32,
) -> Result<Option<ProductionDecisionV2>, AgentdIntuitionPolicyError> {
    let ProductionDispositionV1::Selected(selected_candidate_id) = &decision.decision.disposition
    else {
        return Ok(None);
    };
    let selected_propensity = decision
        .decision
        .propensities
        .iter()
        .find(|row| row.candidate_id == *selected_candidate_id)
        .map(|row| row.probability)
        .filter(|value| value.raw() > 0)
        .ok_or(AgentdIntuitionPolicyError::SelectedPropensityMissing)?;
    let record_id = intuition_policy_record_id_v1(
        agent_id,
        spawn_generation,
        &request.decision_id,
        request.policy_digest,
        request.sequence,
    )?;
    let candidate_ids = request
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: request.decision_id.clone(),
        state_digest: request.state_digest,
        generator_id,
        generator_code_digest: request.completeness.generator_digest,
        grammar_digest: request.completeness.grammar_digest,
        hard_filter_digest: request.completeness.hard_filter_digest,
        truncation_digest: request.completeness.truncation_digest,
        candidates_digest: candidate_ids_digest_v2(&candidate_ids),
        candidate_count: u32::try_from(candidate_ids.len())
            .map_err(|_| AgentdIntuitionPolicyError::InvalidHost("candidate count overflow"))?,
        omitted_count_bound: request.completeness.omitted_count_bound,
        canonical_order_digest: candidate_order_digest_v2(&candidate_ids),
        complete_for_generator: request.completeness.omitted_count_bound == 0,
    };
    let mut support = b"hepta.agentd.intuition-production-decision.v1\0".to_vec();
    for digest in [
        host_binding_digest,
        decision.authentication_digest,
        decision.decision.receipt_digest,
        request.completeness.receipt_digest,
    ] {
        support.extend_from_slice(digest.as_array());
    }
    Ok(Some(ProductionDecisionV2 {
        record_id,
        episode_id,
        run_snapshot_digest,
        objective_digest: request.objective_digest,
        policy_digest: request.policy_digest,
        candidate_ids,
        selected_candidate_id: selected_candidate_id.clone(),
        selected_propensity,
        completeness,
        support_digest: Digest32::of_bytes(&support),
    }))
}

pub fn intuition_policy_record_id_v1(
    agent_id: &AgentId,
    spawn_generation: u64,
    decision_id: &StableId,
    policy_digest: Digest32,
    sequence: u64,
) -> Result<StableId, AgentdIntuitionPolicyError> {
    if spawn_generation == 0 || policy_digest.is_zero() {
        return Err(AgentdIntuitionPolicyError::GenerationFence);
    }
    let mut bytes = b"hepta.agentd.intuition-record-id.v1\0".to_vec();
    let agent = agent_id.to_string();
    bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
    bytes.extend_from_slice(agent.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    let decision = decision_id.as_str().as_bytes();
    bytes.extend_from_slice(&(decision.len() as u64).to_be_bytes());
    bytes.extend_from_slice(decision);
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    StableId::new(format!("intuition-decision:{}", Digest32::of_bytes(&bytes)))
        .map_err(|_| AgentdIntuitionPolicyError::InvalidHost("record id"))
}

#[must_use]
pub fn intuition_risk_rule_digest_v1(rule: CanonicalRiskRuleV1) -> Digest32 {
    let code = match rule {
        CanonicalRiskRuleV1::HighOnlySlowPath => 0,
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath => 1,
        CanonicalRiskRuleV1::AlwaysSlowPath => 2,
    };
    let mut bytes = b"hepta.agentd.intuition-risk-rule.v1\0".to_vec();
    bytes.push(code);
    Digest32::of_bytes(&bytes)
}

fn validate_legacy_pins(
    spawn_generation: u64,
    pins: &AgentdIntuitionPolicyPinsV1,
) -> Result<(), AgentdIntuitionPolicyError> {
    if spawn_generation == 0 {
        return Err(AgentdIntuitionPolicyError::GenerationFence);
    }
    if pins.model_artifact_digest.is_zero() {
        return Err(AgentdIntuitionPolicyError::InvalidHost(
            "model artifact pin",
        ));
    }
    if pins.scorer_contract_digest.is_zero() {
        return Err(AgentdIntuitionPolicyError::InvalidHost(
            "scorer contract pin",
        ));
    }
    if pins.rng_owner_digest.is_some_and(Digest32::is_zero) {
        return Err(AgentdIntuitionPolicyError::InvalidHost("rng owner pin"));
    }
    Ok(())
}

fn validate_product_pins(
    spawn_generation: u64,
    pins: &AgentdIntuitionPolicyPinsV2,
) -> Result<(), AgentdIntuitionPolicyError> {
    validate_legacy_pins(
        spawn_generation,
        &AgentdIntuitionPolicyPinsV1 {
            model_artifact_digest: pins.model_artifact_digest,
            scorer_contract_digest: pins.scorer_contract_digest,
            rng_owner_digest: pins.rng_owner_digest,
        },
    )?;
    for (name, digest) in [
        ("policy profile pin", pins.policy_profile_digest),
        ("policy pin", pins.policy_digest),
        ("objective class pin", pins.objective_class_digest),
        ("calibration artifact pin", pins.calibration_artifact_digest),
        ("ood artifact pin", pins.ood_artifact_digest),
        ("risk rule pin", pins.risk_rule_digest),
    ] {
        if digest.is_zero() {
            return Err(AgentdIntuitionPolicyError::InvalidHost(name));
        }
    }
    Ok(())
}

fn validate_current_pins(
    pins: &AgentdIntuitionPolicyPinsV2,
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV2,
    assignment: &AssignmentCommitmentV2,
) -> Result<(), AgentdIntuitionPolicyError> {
    let profile_digest = canonical_policy_profile_digest_v1(profile)
        .map_err(|_| AgentdIntuitionPolicyError::ProfilePinMismatch)?;
    if profile_digest != pins.policy_profile_digest {
        return Err(AgentdIntuitionPolicyError::ProfilePinMismatch);
    }
    if profile.policy_digest != pins.policy_digest
        || request.policy_digest != pins.policy_digest
        || scoring.policy_digest != pins.policy_digest
        || profile.generation != pins.policy_generation.get()
        || request.policy_generation != pins.policy_generation.get()
        || scoring.policy_generation != pins.policy_generation
    {
        return Err(AgentdIntuitionPolicyError::PolicyPinMismatch);
    }
    if profile.objective_class_digest != pins.objective_class_digest
        || request.objective_class_digest != pins.objective_class_digest
    {
        return Err(AgentdIntuitionPolicyError::ObjectiveClassPinMismatch);
    }
    if profile.scorer.model_digest != pins.model_artifact_digest
        || scoring.model_artifact_digest != pins.model_artifact_digest
    {
        return Err(AgentdIntuitionPolicyError::ModelPinMismatch);
    }
    if profile.scorer.scorer_contract_digest != pins.scorer_contract_digest
        || scoring.scorer_contract_digest != pins.scorer_contract_digest
    {
        return Err(AgentdIntuitionPolicyError::ScorerPinMismatch);
    }
    if profile.calibration_artifact_digest != pins.calibration_artifact_digest
        || request.calibration.artifact_digest != pins.calibration_artifact_digest
    {
        return Err(AgentdIntuitionPolicyError::CalibrationPinMismatch);
    }
    if profile.ood_artifact_digest != pins.ood_artifact_digest
        || request.ood.artifact_digest != pins.ood_artifact_digest
    {
        return Err(AgentdIntuitionPolicyError::OodPinMismatch);
    }
    if intuition_risk_rule_digest_v1(profile.risk_rule) != pins.risk_rule_digest {
        return Err(AgentdIntuitionPolicyError::RiskRulePinMismatch);
    }
    match (assignment, pins.rng_owner_digest) {
        (AssignmentCommitmentV2::Deterministic { .. }, _) => Ok(()),
        (
            AssignmentCommitmentV2::CounterBased {
                rng_owner_digest, ..
            },
            Some(expected),
        ) if *rng_owner_digest == expected => Ok(()),
        (AssignmentCommitmentV2::CounterBased { .. }, _) => {
            Err(AgentdIntuitionPolicyError::RngOwnerPinMismatch)
        }
    }
}

fn legacy_host_binding_digest(
    agent_id: &AgentId,
    spawn_generation: u64,
    trust_digest: Digest32,
    pins: &AgentdIntuitionPolicyPinsV1,
    authentication_digest: Digest32,
) -> Digest32 {
    let agent = agent_id.to_string();
    let mut bytes = b"hepta.agentd.authenticated-intuition.v1\0".to_vec();
    bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
    bytes.extend_from_slice(agent.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(pins.model_artifact_digest.as_array());
    bytes.extend_from_slice(pins.scorer_contract_digest.as_array());
    match pins.rng_owner_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(authentication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn product_host_binding_digest(
    agent_id: &AgentId,
    spawn_generation: u64,
    trust_digest: Digest32,
    pins: &AgentdIntuitionPolicyPinsV2,
    authentication_digest: Digest32,
) -> Digest32 {
    let agent = agent_id.to_string();
    let mut bytes = b"hepta.agentd.authenticated-intuition.v2\0".to_vec();
    bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
    bytes.extend_from_slice(agent.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    for digest in [
        trust_digest,
        pins.policy_profile_digest,
        pins.policy_digest,
        pins.objective_class_digest,
        pins.model_artifact_digest,
        pins.scorer_contract_digest,
        pins.calibration_artifact_digest,
        pins.ood_artifact_digest,
        pins.risk_rule_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&pins.policy_generation.get().to_be_bytes());
    match pins.rng_owner_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(authentication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use ed25519_dalek::SigningKey;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    #[test]
    fn host_identity_and_owner_pins_fail_closed_before_policy_admission() {
        let agent_id = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent id");
        let key = SigningKey::from_bytes(&[7; 32]);
        let scope = digest("scope");
        let principal = AuthenticatedPrincipalV1 {
            principal_id: id("intuition-generator"),
            credential_chain_digest: digest("credentials"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: scope,
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 100,
        };
        let verifier = Arc::new(
            LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: digest("objective"),
                authority_epoch: 1,
                signers: vec![TrustedLearningSignerV1 {
                    principal,
                    controller_id: id("intuition-generator-controller"),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                }],
            })
            .expect("host trust"),
        );
        let host = AgentdIntuitionPolicyHostV1::new(
            agent_id.clone(),
            7,
            verifier,
            AgentdIntuitionPolicyPinsV1 {
                model_artifact_digest: digest("model"),
                scorer_contract_digest: digest("scorer"),
                rng_owner_digest: Some(digest("rng-owner")),
            },
        )
        .expect("host");
        assert!(host.require_identity(&agent_id, 7).is_ok());
        assert!(matches!(
            host.require_identity(&agent_id, 8),
            Err(AgentdIntuitionPolicyError::GenerationFence)
        ));
        assert!(!host.is_product_ready());
        assert_eq!(
            AgentdIntuitionPolicyError::GenerationFence.code(),
            "agentd.intuition.generation_fenced"
        );
    }
}
