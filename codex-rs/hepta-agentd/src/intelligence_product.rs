//! Agentd-owned canonical intelligence composition.
//!
//! The facade owns no domain facts or effect authority. Concrete owner adapters
//! retain their actual utility/neuron results; the runner bounds cognition and
//! final currentness reads. Product learning uses the separate sealed writer
//! host. A signed manifest authenticates bytes, not an external rollback floor.

#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_intelligence::AdvisoryDecisionV1;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::AppendReceipt;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::CandidateSetCompleteness;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::EpisodeDecision;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::OutcomeFinality;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::OutcomeObservation;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_types::FixedQ32;

#[path = "intelligence_evaluation.rs"]
mod evaluation;
pub use evaluation::AgentdEvaluationBindingV1;
use evaluation::AgentdEvaluationSessionV1;
pub use evaluation::AgentdIntelligenceEvaluationError;
pub use evaluation::AgentdSignedEvaluationV1;
pub use evaluation::intelligence_evaluation_binding_payload_v1;

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::compile;
use codex_hepta_intelligence::CanonicalFreshnessOracleV1;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_intelligence::CanonicalIntelligenceSnapshotV1;
use codex_hepta_intelligence::CanonicalOwnerPortsV1;
use codex_hepta_intelligence::CanonicalPortDecisionV1;
use codex_hepta_intelligence::CanonicalPortFailureClassV1;
use codex_hepta_intelligence::CanonicalPortFailureV1;
use codex_hepta_intelligence::CanonicalPortInputV1;
use codex_hepta_intelligence::CanonicalPortReceiptV1;
use codex_hepta_intelligence::CanonicalRunOutcomeV1;
use codex_hepta_intelligence::CanonicalStageV1;
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_intelligence::PreparedPromptDeliveryV1;
use codex_hepta_intelligence::canonical_candidate_ids_v1;
use codex_hepta_intelligence::prepare_intelligence_run;
use codex_hepta_intelligence::validate_canonical_outcome_v1;
use codex_hepta_intelligence::validate_current_snapshot;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::decide_calibrated_v2;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::DurableLearningJournal;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_prompt_optimizer::OptimizationRequest;
use codex_hepta_prompt_optimizer::optimize;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use tokio::time::timeout;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntelligenceAuthorityOwnerFileV1 {
    pub owner_id: String,
    pub generation: u64,
    pub implementation_digest: String,
    pub key_digest: String,
    pub key_epoch: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntelligenceAuthorityFileV1 {
    pub schema_version: u32,
    pub authority_epoch: u64,
    pub revocation_frontier_digest: String,
    pub owners: Vec<IntelligenceAuthorityOwnerFileV1>,
    pub signer_id: String,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceAuthorityVerifierV1 {
    pub signer_id: String,
    pub verifying_key: [u8; 32],
}

const MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES: u64 = 64 * 1024;

struct FileBackedFreshnessOracleV1 {
    path: PathBuf,
    verifier: IntelligenceAuthorityVerifierV1,
    rollback: Option<Arc<crate::IntelligenceAuthorityRollbackGuardV1>>,
    telemetry: Option<Arc<crate::AgentdIntelligenceTelemetryV1>>,
    snapshot: Option<BTreeMap<StableId, CurrentOwnerStateV1>>,
}

impl FileBackedFreshnessOracleV1 {
    #[cfg(feature = "qualification-legacy-learning-write")]
    fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {
        Self {
            path,
            verifier,
            rollback: None,
            telemetry: None,
            snapshot: None,
        }
    }

    fn new_observed(
        path: PathBuf,
        verifier: IntelligenceAuthorityVerifierV1,
        telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    ) -> Self {
        Self {
            path,
            verifier,
            rollback: None,
            telemetry: Some(telemetry),
            snapshot: None,
        }
    }

    fn with_rollback(
        mut self,
        rollback: Option<Arc<crate::IntelligenceAuthorityRollbackGuardV1>>,
    ) -> Self {
        self.rollback = rollback;
        self.snapshot = None;
        self
    }

    fn load_snapshot(
        &self,
        requested: &StableId,
    ) -> Result<BTreeMap<StableId, CurrentOwnerStateV1>, CanonicalIntelligenceError> {
        let verification_started = Instant::now();
        let unavailable = || CanonicalIntelligenceError::FreshnessUnavailable(requested.clone());
        let bytes = crate::intelligence_files::read_bounded(
            &self.path,
            MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES as usize,
        )
        .map_err(|_| unavailable())?;
        let file: IntelligenceAuthorityFileV1 =
            serde_json::from_slice(&bytes).map_err(|_| unavailable())?;
        verify_authority_file(&file, &self.verifier, requested)?;
        if file.schema_version != 1 || file.authority_epoch == 0 || file.owners.len() != 7 {
            return Err(unavailable());
        }
        let frontier =
            Digest32::from_str(&file.revocation_frontier_digest).map_err(|_| unavailable())?;
        if frontier.is_zero() {
            return Err(unavailable());
        }
        // Validate the entire signed owner universe before advancing the floor.
        // A malformed but signed future epoch must not poison healthy owners.
        let expected: std::collections::BTreeSet<&str> = [
            "objective.compiler",
            "utility.ndu",
            "neuron.runtime",
            "prompt.optimizer",
            "intuition.policy",
            "context.compiler",
            "learning.eval",
        ]
        .into_iter()
        .collect();
        let actual: std::collections::BTreeSet<&str> = file
            .owners
            .iter()
            .map(|owner| owner.owner_id.as_str())
            .collect();
        if actual != expected {
            return Err(unavailable());
        }
        for owner in &file.owners {
            Generation::new(owner.generation).map_err(|_| unavailable())?;
            let implementation =
                Digest32::from_str(&owner.implementation_digest).map_err(|_| unavailable())?;
            let key = Digest32::from_str(&owner.key_digest).map_err(|_| unavailable())?;
            if implementation.is_zero() || key.is_zero() || owner.key_epoch == 0 {
                return Err(unavailable());
            }
        }
        if let Some(rollback) = self.rollback.as_ref() {
            let manifest_digest =
                intelligence_authority_manifest_digest_v1(&file).map_err(|_| unavailable())?;
            rollback
                .admit(file.authority_epoch, manifest_digest)
                .map_err(|_| unavailable())?;
        }

        let authority_epoch = file.authority_epoch;
        let mut states = BTreeMap::new();
        for owner in file.owners {
            let owner_id = StableId::new(owner.owner_id).map_err(|_| unavailable())?;
            let generation = Generation::new(owner.generation).map_err(|_| unavailable())?;
            let implementation_digest =
                Digest32::from_str(&owner.implementation_digest).map_err(|_| unavailable())?;
            let key_digest = Digest32::from_str(&owner.key_digest).map_err(|_| unavailable())?;
            let state = CurrentOwnerStateV1 {
                owner_id: owner_id.clone(),
                generation,
                implementation_digest,
                key_digest,
                key_epoch: owner.key_epoch,
                authority_epoch,
                revocation_frontier_digest: frontier,
            };
            if states.insert(owner_id, state).is_some() {
                return Err(unavailable());
            }
        }
        if !states.contains_key(requested) {
            return Err(unavailable());
        }
        if let Some(telemetry) = self.telemetry.as_ref() {
            telemetry.record_authority_manifest(
                authority_epoch,
                best_effort_wall_clock_ms(),
                duration_micros(verification_started.elapsed()),
            );
        }
        Ok(states)
    }
}

impl CanonicalFreshnessOracleV1 for FileBackedFreshnessOracleV1 {
    fn refresh_snapshot(&mut self, owner_id: &StableId) -> Result<(), CanonicalIntelligenceError> {
        self.snapshot = Some(self.load_snapshot(owner_id)?);
        Ok(())
    }

    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        if self.snapshot.is_none() {
            self.refresh_snapshot(owner_id)?;
        }
        self.snapshot
            .as_ref()
            .and_then(|snapshot| snapshot.get(owner_id))
            .cloned()
            .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(owner_id.clone()))
    }
}

pub struct AgentdIntelligenceOwnerInputsV1 {
    pub run_identity: Option<crate::AgentdIntelligenceRunIdentityV1>,
    pub objective_envelope: ObjectiveSourceEnvelopeV1,
    pub objective_profile: ObjectiveAdmissionProfileV1,
    pub objective_context: ObjectiveAdmissionContextV1,
    pub utility_contributions: ContributionSet,
    pub utility_profile: UtilityProfile,
    pub utility_scalarization: Option<ScalarizationProfile>,
    pub utility_policy: EvaluationPolicyV1,
    pub neural_config: SparseConfig,
    pub neural_tick: SparseTick,
    pub neural_previous: Option<SparseCheckpoint>,
    pub prompt_request: OptimizationRequest,
    /// Exact owner-backed prompt/context delivery. Compatibility fixtures may
    /// leave this absent, but physical product execution is fail-closed without it.
    pub prompt_delivery: Option<PreparedPromptDeliveryV1>,
    pub intuition_request: CalibratedDecisionRequestV1,
    pub context_request: CompilationRequest,
    pub evaluation_request: EvaluationRequest,
    pub signed_evaluation: Option<AgentdSignedEvaluationV1>,
}

#[path = "intelligence_product_ports.rs"]
mod owner_ports;
#[path = "intelligence_prompt_binding.rs"]
mod prompt_binding;
use owner_ports::AgentdOwnerPortsV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedAgentdIntelligenceRunV1 {
    pub envelope: IntelligenceHostEnvelopeV1,
    pub dispatch_proposal_digest: Digest32,
    snapshot: CanonicalIntelligenceSnapshotV1,
    candidate_ids: Vec<StableId>,
    run_snapshot: crate::AgentRunSnapshot,
    context_attachment: crate::AgentContextAttachment,
    prompt_delivery: Option<PreparedPromptDeliveryV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligencePhysicalPromptV1 {
    pub payload: Vec<u8>,
    pub payload_digest: Digest32,
    pub attachment_digest: Digest32,
    pub prompt_stage_digest: Digest32,
}

impl PreparedAgentdIntelligenceRunV1 {
    #[must_use]
    pub fn run_snapshot(&self) -> crate::AgentRunSnapshot {
        self.run_snapshot.clone()
    }
    #[must_use]
    pub fn context_attachment(&self) -> crate::AgentContextAttachment {
        self.context_attachment.clone()
    }
    #[must_use]
    pub fn canonical_snapshot(&self) -> CanonicalIntelligenceSnapshotV1 {
        self.snapshot.clone()
    }
    #[must_use]
    pub fn candidate_ids(&self) -> &[StableId] {
        &self.candidate_ids
    }
    #[must_use]
    pub fn prompt_delivery(&self) -> Option<&PreparedPromptDeliveryV1> {
        self.prompt_delivery.as_ref()
    }
    pub fn selected_candidate_membership(
        &self,
    ) -> Result<crate::AgentdLegalCandidateMembershipProofV1, CanonicalIntelligenceError> {
        self.validate_integrity()?;
        let codex_hepta_intelligence::AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } = &self.envelope.decision.decision
        else {
            return Err(CanonicalIntelligenceError::UnexpectedDecision);
        };
        crate::AgentdLegalCandidateMembershipProofV1::admit(
            self.envelope.candidate_set_digest,
            &self.candidate_ids,
            candidate_id,
            *propensity,
        )
    }
    pub fn physical_prompt(
        &self,
    ) -> Result<AgentdIntelligencePhysicalPromptV1, CanonicalIntelligenceError> {
        self.validate_integrity()?;
        let delivery =
            self.prompt_delivery
                .as_ref()
                .ok_or(CanonicalIntelligenceError::InvalidSnapshot(
                    "owner-backed prompt delivery",
                ))?;
        let binding = prompt_binding::validate_prompt_delivery_v1(delivery)?;
        Ok(AgentdIntelligencePhysicalPromptV1 {
            payload: delivery.serialized_payload.clone(),
            payload_digest: binding.payload_digest,
            attachment_digest: binding.context_attachment_digest,
            prompt_stage_digest: binding.prompt_stage_digest,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
// Preserve the public v1 by-value outcome and its bounded prepared-object API.
#[allow(clippy::large_enum_variant)]
pub enum AgentdIntelligenceProductOutcomeV1 {
    Ready(PreparedAgentdIntelligenceRunV1),
    Abstained,
    SlowPath,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceAdmittedOutcomeV1 {
    Ready {
        prepared: PreparedAgentdIntelligenceRunV1,
        run_receipt: crate::RunReceipt,
    },
    /// A historical attachment identity; only an existing durable native
    /// dispatch may be reconciled. No fresh physical execution is permitted.
    ReconciliationRequired {
        prepared: PreparedAgentdIntelligenceRunV1,
        run_receipt: crate::RunReceipt,
    },
    Abstained,
    SlowPath,
}

#[derive(Debug)]
pub enum AgentdIntelligenceProductError {
    Canonical(CanonicalIntelligenceError),
    WorkerCrashed,
    Busy,
    TimedOut,
    CandidateSetMismatch,
    MissingRunIdentity,
    RunIdentityMismatch,
    Clock,
    InvalidAuthorityVerifier,
    InvalidAuthorityRollback,
    InvalidWorkerPolicy,
    Run(crate::AgentRunError),
}

impl fmt::Display for AgentdIntelligenceProductError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdIntelligenceProductError {}

const MAX_CANONICAL_OWNER_WORKERS: usize = 4;

pub struct AgentdIntelligenceProductRunnerV1 {
    worker_slots: Arc<tokio::sync::Semaphore>,
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
    authority_rollback: Option<Arc<crate::IntelligenceAuthorityRollbackGuardV1>>,
    evaluation_trust: Option<Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,
    telemetry: Arc<crate::AgentdIntelligenceTelemetryV1>,
    hard_timeout_process_exit_grace: Option<Duration>,
}

#[path = "intelligence_product_runner.rs"]
mod runner;

fn authority_signing_payload(
    file: &IntelligenceAuthorityFileV1,
) -> Result<Vec<u8>, serde_json::Error> {
    serde_json::to_vec(&(
        "hepta.agentd.intelligence-authority.v1",
        file.schema_version,
        file.authority_epoch,
        &file.revocation_frontier_digest,
        &file.owners,
        &file.signer_id,
    ))
}

/// Exact identity of one already signed authority manifest, including its
/// signature bytes. The monotonic guard consumes this only after signature
/// verification; the digest itself grants no authority.
pub fn intelligence_authority_manifest_digest_v1(
    file: &IntelligenceAuthorityFileV1,
) -> Result<Digest32, serde_json::Error> {
    let mut bytes = b"hepta.agentd.intelligence-authority-manifest.v1\0".to_vec();
    bytes.extend_from_slice(&authority_signing_payload(file)?);
    bytes.extend_from_slice(&file.signature);
    Ok(Digest32::of_bytes(&bytes))
}

fn verify_authority_file(
    file: &IntelligenceAuthorityFileV1,
    verifier: &IntelligenceAuthorityVerifierV1,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    let unavailable = || CanonicalIntelligenceError::FreshnessUnavailable(requested.clone());
    if file.signer_id != verifier.signer_id || file.signature.len() != 64 {
        return Err(unavailable());
    }
    let key = VerifyingKey::from_bytes(&verifier.verifying_key).map_err(|_| unavailable())?;
    if key.is_weak() {
        return Err(unavailable());
    }
    let signature_bytes: [u8; 64] = file
        .signature
        .as_slice()
        .try_into()
        .map_err(|_| unavailable())?;
    let signature = Signature::from_bytes(&signature_bytes);
    let payload = authority_signing_payload(file).map_err(|_| unavailable())?;
    key.verify_strict(&payload, &signature)
        .map_err(|_| unavailable())
}

fn wall_clock_ms() -> Result<u64, AgentdIntelligenceProductError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdIntelligenceProductError::Clock)?
        .as_millis();
    u64::try_from(millis).map_err(|_| AgentdIntelligenceProductError::Clock)
}

fn best_effort_wall_clock_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .unwrap_or(0)
}

fn duration_micros(value: Duration) -> u64 {
    u64::try_from(value.as_micros()).unwrap_or(u64::MAX)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PendingIntelligenceLedgerAppendV1 {
    pub expected_predecessor: Digest32,
    snapshot: CanonicalIntelligenceSnapshotV1,
    pub event: LedgerEvent,
}

#[derive(Debug)]
// Pending append evidence is bounded and intentionally retained by the v1 API.
#[allow(clippy::large_enum_variant)]
pub enum AgentdIntelligenceLedgerError {
    Currentness(CanonicalIntelligenceError),
    Ledger(DurableLedgerError),
    Indeterminate(PendingIntelligenceLedgerAppendV1),
    NotSelected,
    InvalidOutcome,
}
impl fmt::Display for AgentdIntelligenceLedgerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AgentdIntelligenceLedgerError {}

#[cfg(test)]
#[path = "intelligence_evaluation_tests.rs"]
mod evaluation_tests;
#[cfg(test)]
#[path = "intelligence_product_tests.rs"]
mod tests;
