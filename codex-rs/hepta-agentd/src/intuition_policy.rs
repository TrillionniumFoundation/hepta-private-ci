//! Agentd-owned intuition.policy product boundary.
//!
//! The host authenticates generator/evaluator/observer evidence, pins the full
//! selected policy profile, and prepares the exact durable Decision. A separate
//! generator signature is verified by the sole `LedgerWriter` during commit.
//! Neither a prepared value nor a committed receipt grants effect authority.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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

/// Agentd-owned clock sampled only after the sole LedgerWriter lock is held.
///
/// Implementations must be nondecreasing for one process generation. A clock
/// failure is a hard admission failure; callers cannot supply or cache `now`.
pub trait IntuitionPolicyClock: Send + Sync {
    fn now(&self) -> Result<u64, AgentdIntuitionPolicyError>;
}

/// Wall-clock milliseconds with a process-local monotonic fence. Evidence validity
/// uses wall-clock timestamps, while a backward host adjustment fails closed.
#[derive(Debug, Default)]
pub struct SystemIntuitionPolicyClock {
    last_seen: AtomicU64,
}

impl IntuitionPolicyClock for SystemIntuitionPolicyClock {
    fn now(&self) -> Result<u64, AgentdIntuitionPolicyError> {
        let current = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|_| AgentdIntuitionPolicyError::TrustedClockUnavailable)?
                .as_millis(),
        )
        .map_err(|_| AgentdIntuitionPolicyError::TrustedClockUnavailable)?;
        let mut observed = self.last_seen.load(Ordering::Acquire);
        loop {
            if current < observed {
                return Err(AgentdIntuitionPolicyError::TrustedClockReversed);
            }
            match self.last_seen.compare_exchange_weak(
                observed,
                current,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return Ok(current),
                Err(next) => observed = next,
            }
        }
    }
}

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
    clock: Arc<dyn IntuitionPolicyClock>,
}

impl IntuitionPolicyLearningSink {
    #[must_use]
    pub fn new(writer: LedgerWriter) -> Self {
        Self::new_with_clock(writer, Arc::new(SystemIntuitionPolicyClock::default()))
    }

    #[must_use]
    pub fn new_with_clock(
        writer: LedgerWriter,
        clock: Arc<dyn IntuitionPolicyClock>,
    ) -> Self {
        Self {
            writer: Mutex::new(writer),
            clock,
        }
    }

    pub fn trust_identity(
        &self,
    ) -> Result<(Digest32, u64, Digest32), AgentdIntuitionPolicyError> {
        let writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        Ok((
            writer.verifier().trust_digest(),
            writer.trust_generation(),
            writer.trust_distribution_digest(),
        ))
    }

    pub fn trust_digest(&self) -> Result<Digest32, AgentdIntuitionPolicyError> {
        Ok(self.trust_identity()?.0)
    }

    /// Rotate the sole writer-owned trust distribution under the same lock used
    /// by final-use admission. A commit either observes the predecessor or the
    /// successor generation; rotation cannot interleave with revalidation.
    pub fn rotate_trust(
        &self,
        root: &codex_hepta_learning_ledger::LearningTrustRootV1,
        signed: codex_hepta_learning_ledger::SignedLearningTrustDistributionV1,
        now: u64,
    ) -> Result<Digest32, AgentdIntuitionPolicyError> {
        let mut writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        writer
            .rotate_trust(root, signed, now)
            .map_err(AgentdIntuitionPolicyError::TrustRotation)
    }

    #[allow(clippy::too_many_arguments)]
    fn commit_prepared(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        pins: &AgentdIntuitionPolicyPinsV2,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_predecessor: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
    ) -> Result<AgentdIntuitionDecisionReceiptV2, AgentdIntuitionPolicyError> {
        // This is the sole final-use serialization boundary. The product clock,
        // current trust distribution, all three qualification signatures, host
        // pins and the durable Decision append are evaluated under one lock.
        let mut writer = self
            .writer
            .lock()
            .map_err(|_| AgentdIntuitionPolicyError::LearningLockPoisoned)?;
        let now = self.clock.now()?;
        let current_trust_digest = writer.verifier().trust_digest();
        let current_trust_generation = writer.trust_generation();
        let current_distribution_digest = writer.trust_distribution_digest();

        if prepared.owner_agent_id != *agent_id
            || prepared.owner_spawn_generation != spawn_generation
            || prepared.owner_trust_digest != current_trust_digest
            || prepared.owner_trust_generation != current_trust_generation
            || prepared.owner_trust_distribution_digest != current_distribution_digest
        {
            return Err(AgentdIntuitionPolicyError::PreparedOwnerMismatch);
        }
        validate_prepared_time(prepared.prepared_at, prepared.qualification_expires_at, now)?;
        validate_current_pins(
            pins,
            &prepared.request,
            &prepared.profile,
            &prepared.scoring,
            &prepared.assignment,
        )?;

        let revalidated = decide_authenticated_intuition_v3(
            prepared.request.clone(),
            prepared.profile.clone(),
            prepared.scoring.clone(),
            prepared.assignment.clone(),
            prepared.qualification.as_borrowed(),
            writer.verifier(),
            now,
        )?;
        if revalidated != prepared.decision {
            return Err(AgentdIntuitionPolicyError::PreparedQualificationMismatch);
        }
        let current_binding = product_host_binding_digest(
            agent_id,
            spawn_generation,
            current_trust_digest,
            pins,
            revalidated.authentication_digest,
        );
        if current_binding != prepared.host_binding_digest {
            return Err(AgentdIntuitionPolicyError::PreparedProfileMismatch);
        }

        let (production_record_id, learning) =
            match (prepared.production.clone(), decision_evidence) {
                (Some(production), Some(evidence)) => {
                    let record_id = production.record_id.clone();
                    let retry_production = production.clone();
                    let retry_evidence = evidence.clone();
                    let receipt = match writer.append_decision(
                        expected_predecessor,
                        production,
                        &evidence,
                        now,
                    ) {
                        Ok(receipt) => receipt,
                        Err(ProductionLedgerError::IndeterminateAfterLedgerCommit {
                            receipt,
                            witness_error: _,
                        }) => preserve_known_commit(
                            receipt,
                            writer.append_decision(
                                expected_predecessor,
                                retry_production,
                                &retry_evidence,
                                now,
                            ),
                        )
                        .map_err(|receipt| {
                            AgentdIntuitionPolicyError::IndeterminateAfterLedgerCommit { receipt }
                        })?,
                        Err(error) => return Err(AgentdIntuitionPolicyError::Learning(error)),
                    };
                    (Some(record_id), Some(receipt))
                }
                (Some(_), None) => {
                    return Err(AgentdIntuitionPolicyError::MissingDecisionEvidence);
                }
                (None, Some(_)) => {
                    return Err(AgentdIntuitionPolicyError::UnexpectedDecisionEvidence);
                }
                (None, None) => (None, None),
            };

        let mut bytes = b"hepta.agentd.committed-intuition.v2\0".to_vec();
        bytes.extend_from_slice(prepared.prepared_digest.as_array());
        bytes.extend_from_slice(&now.to_be_bytes());
        bytes.extend_from_slice(&current_trust_generation.to_be_bytes());
        bytes.extend_from_slice(current_distribution_digest.as_array());
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
            decision: revalidated,
            host_binding_digest: prepared.host_binding_digest,
            production_record_id,
            learning,
            service_receipt_digest: Digest32::of_bytes(&bytes),
        })
    }
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

    /// Compatibility name retained without the unsafe caller-supplied time.
    #[deprecated(note = "use commit_v4; final-use time is writer-owned")]
    pub fn commit_v3(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
        prepared: PreparedAgentdIntuitionDecisionV3,
        expected_ledger_head: Digest32,
        decision_evidence: Option<SignedLearningEvidenceV1>,
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

/// Reconciliation cannot turn a known commit into a not-committed failure.
fn preserve_known_commit<T, E>(committed: T, replay: Result<T, E>) -> Result<T, T> {
    replay.map_err(|_| committed)
}

fn validate_prepared_time(
    prepared_at: u64,
    qualification_expires_at: u64,
    now: u64,
) -> Result<(), AgentdIntuitionPolicyError> {
    if now < prepared_at {
        return Err(AgentdIntuitionPolicyError::PreparedClockReversed);
    }
    // A freshly signed Decision cannot extend the original qualification lease.
    if now >= qualification_expires_at {
        return Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired);
    }
    Ok(())
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
    let mut candidate_ids = request
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    let abstain_id = StableId::new("abstain")
        .map_err(|_| AgentdIntuitionPolicyError::InvalidHost("abstain candidate id"))?;
    if candidate_ids
        .iter()
        .any(|candidate| candidate == &abstain_id)
    {
        return Err(AgentdIntuitionPolicyError::InvalidHost(
            "reserved abstain candidate in policy request",
        ));
    }
    // The intuition kernel represents abstention as a disposition rather than
    // an action candidate. The learning ledger deliberately requires an
    // explicit abstain option in every complete candidate set. Add that
    // reserved option only at the authenticated policy-to-ledger boundary so
    // both contracts remain exact and the signed Decision binds the expansion.
    candidate_ids.push(abstain_id);
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

    #[test]
    fn prepared_time_rejects_expiry_and_clock_rollback() {
        assert!(validate_prepared_time(150, 200, 150).is_ok());
        assert!(validate_prepared_time(150, 200, 199).is_ok());
        assert!(matches!(
            validate_prepared_time(150, 200, 149),
            Err(AgentdIntuitionPolicyError::PreparedClockReversed)
        ));
        for now in [200, 201, u64::MAX] {
            assert!(matches!(
                validate_prepared_time(150, 200, now),
                Err(AgentdIntuitionPolicyError::PreparedEvidenceExpired)
            ));
        }
    }

    #[test]
    fn failed_reconciliation_preserves_the_first_durable_commit() {
        let receipt = String::from("committed:event:7:chain:verified");
        for failure in [
            "witness unavailable",
            "trust changed",
            "writer lock poisoned",
        ] {
            assert_eq!(
                preserve_known_commit(receipt.clone(), Err(failure)),
                Err(receipt.clone()),
            );
        }
    }

    #[test]
    fn successful_reconciliation_returns_the_verified_replay_receipt() {
        let original = String::from("committed:unwitnessed");
        let reconciled = String::from("committed:witnessed");
        assert_eq!(
            preserve_known_commit::<_, ()>(original, Ok(reconciled.clone())),
            Ok(reconciled),
        );
    }

    #[test]
    fn product_host_binding_mutation_covers_every_profile_pin() {
        let agent = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("agent");
        let pins = AgentdIntuitionPolicyPinsV2 {
            policy_profile_digest: digest("profile"),
            policy_digest: digest("policy"),
            policy_generation: PolicyGeneration::new(4).expect("generation"),
            objective_class_digest: digest("class"),
            model_artifact_digest: digest("model"),
            scorer_contract_digest: digest("scorer"),
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
            risk_rule_digest: digest("risk"),
            rng_owner_digest: Some(digest("rng")),
        };
        let binding = |value: &AgentdIntuitionPolicyPinsV2| {
            product_host_binding_digest(&agent, 7, digest("trust"), value, digest("authentication"))
        };
        let original = binding(&pins);
        for field in 0..11 {
            let mut changed = pins.clone();
            match field {
                0 => changed.policy_profile_digest = digest("changed-profile"),
                1 => changed.policy_digest = digest("changed-policy"),
                2 => changed.policy_generation = PolicyGeneration::new(5).expect("generation"),
                3 => changed.objective_class_digest = digest("changed-class"),
                4 => changed.model_artifact_digest = digest("changed-model"),
                5 => changed.scorer_contract_digest = digest("changed-scorer"),
                6 => changed.calibration_artifact_digest = digest("changed-calibration"),
                7 => changed.ood_artifact_digest = digest("changed-ood"),
                8 => changed.risk_rule_digest = digest("changed-risk"),
                9 => changed.rng_owner_digest = Some(digest("changed-rng")),
                10 => changed.rng_owner_digest = None,
                _ => unreachable!(),
            }
            assert_ne!(
                binding(&changed),
                original,
                "pin field {field} was not bound"
            );
        }
    }
}
