//! Product-owned intelligence composition for Agentd.
//!
//! The runner is the named product caller for `intelligence.control`. Owner
//! algorithms remain in their authoritative crates. Cognition runs in an
//! isolated blocking worker and cannot publish a dispatch proposal or learning
//! fact. Only the Agentd caller, after a final currentness fence, may publish the
//! proposal digest. Product learning mutation remains behind the authenticated
//! `LedgerWriter`; historical raw-V1 append compatibility is test-only.
//!
//! A timed-out worker may finish pure computation later, but its result is
//! dropped and it has no effect/ledger capability. Durable ledger uncertainty is
//! represented explicitly and reconciled only by replaying the exact event with
//! its original predecessor through a freshly recovered journal.

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
use codex_hepta_intelligence::prepare_intelligence_run;
use codex_hepta_intelligence::validate_current_snapshot;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::decide_calibrated_v2;
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
use ed25519_dalek::Verifier;
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
}

impl FileBackedFreshnessOracleV1 {
    fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {
        Self { path, verifier }
    }

    fn read(
        &self,
        requested: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        validate_authority_file_path(&self.path, requested)?;
        let metadata = std::fs::metadata(&self.path)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        if metadata.len() == 0 || metadata.len() > MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        let bytes = std::fs::read(&self.path)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let file: IntelligenceAuthorityFileV1 = serde_json::from_slice(&bytes)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        verify_authority_file(&file, &self.verifier, requested)?;
        if file.schema_version != 1 || file.authority_epoch == 0 {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        let frontier = Digest32::from_str(&file.revocation_frontier_digest)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        if frontier.is_zero() {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        let mut seen = BTreeMap::new();
        for owner in file.owners {
            let owner_id = StableId::new(owner.owner_id.clone())
                .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
            if seen.insert(owner_id.clone(), owner).is_some() {
                return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                    requested.clone(),
                ));
            }
        }
        let owner = seen
            .remove(requested)
            .ok_or_else(|| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let generation = Generation::new(owner.generation)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let implementation_digest = Digest32::from_str(&owner.implementation_digest)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        let key_digest = Digest32::from_str(&owner.key_digest)
            .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
        if implementation_digest.is_zero() || key_digest.is_zero() || owner.key_epoch == 0 {
            return Err(CanonicalIntelligenceError::FreshnessUnavailable(
                requested.clone(),
            ));
        }
        Ok(CurrentOwnerStateV1 {
            owner_id: requested.clone(),
            generation,
            implementation_digest,
            key_digest,
            key_epoch: owner.key_epoch,
            authority_epoch: file.authority_epoch,
            revocation_frontier_digest: frontier,
        })
    }
}

impl CanonicalFreshnessOracleV1 for FileBackedFreshnessOracleV1 {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        self.read(owner_id)
    }
}

pub struct AgentdIntelligenceOwnerInputsV1 {
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
    pub intuition_request: CalibratedDecisionRequestV1,
    pub context_request: CompilationRequest,
    pub evaluation_request: EvaluationRequest,
    pub signed_evaluation: Option<AgentdSignedEvaluationV1>,
}

struct AgentdOwnerPortsV1 {
    objective_envelope: Option<ObjectiveSourceEnvelopeV1>,
    objective_profile: Option<ObjectiveAdmissionProfileV1>,
    objective_context: Option<ObjectiveAdmissionContextV1>,
    utility_contributions: Option<ContributionSet>,
    utility_profile: Option<UtilityProfile>,
    utility_scalarization: Option<Option<ScalarizationProfile>>,
    utility_policy: Option<EvaluationPolicyV1>,
    neural_config: Option<SparseConfig>,
    neural_tick: Option<SparseTick>,
    neural_previous: Option<Option<SparseCheckpoint>>,
    prompt_request: Option<OptimizationRequest>,
    intuition_request: Option<CalibratedDecisionRequestV1>,
    context_request: Option<CompilationRequest>,
    evaluation_request: Option<EvaluationRequest>,
    evaluation_session: Option<AgentdEvaluationSessionV1>,
    selected_candidate: Option<StableId>,
}

impl AgentdOwnerPortsV1 {
    fn new(
        value: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
    ) -> Self {
        Self {
            objective_envelope: Some(value.objective_envelope),
            objective_profile: Some(value.objective_profile),
            objective_context: Some(value.objective_context),
            utility_contributions: Some(value.utility_contributions),
            utility_profile: Some(value.utility_profile),
            utility_scalarization: Some(value.utility_scalarization),
            utility_policy: Some(value.utility_policy),
            neural_config: Some(value.neural_config),
            neural_tick: Some(value.neural_tick),
            neural_previous: Some(value.neural_previous),
            prompt_request: Some(value.prompt_request),
            intuition_request: Some(value.intuition_request),
            context_request: Some(value.context_request),
            evaluation_request: Some(value.evaluation_request),
            evaluation_session,
            selected_candidate: None,
        }
    }

    fn reject(stage: CanonicalStageV1, label: &'static str) -> CanonicalPortFailureV1 {
        let evidence = format!("hepta.agentd.intelligence.owner-failure.v1:{stage:?}:{label}");
        CanonicalPortFailureV1 {
            class: CanonicalPortFailureClassV1::Rejected,
            evidence_digest: Digest32::of_bytes(evidence.as_bytes()),
        }
    }

    fn receipt(
        input: &CanonicalPortInputV1,
        owner: &str,
        output_digest: Digest32,
        decision: CanonicalPortDecisionV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        if output_digest.is_zero() {
            return Err(Self::reject(input.stage, "zero output"));
        }
        let producer =
            StableId::new(owner).map_err(|_| Self::reject(input.stage, "producer identity"))?;
        Ok(CanonicalPortReceiptV1 {
            stage: input.stage,
            producer,
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn within_budget(
        input: &CanonicalPortInputV1,
        started: Instant,
    ) -> Result<(), CanonicalPortFailureV1> {
        let elapsed = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        if elapsed > input.budget_micros {
            return Err(CanonicalPortFailureV1 {
                class: CanonicalPortFailureClassV1::TimedOut,
                evidence_digest: Digest32::of_bytes(
                    format!(
                        "hepta.agentd.intelligence.stage-timeout.v1:{:?}:{elapsed}:{}",
                        input.stage, input.budget_micros
                    )
                    .as_bytes(),
                ),
            });
        }
        Ok(())
    }

    fn take<T>(
        slot: &mut Option<T>,
        stage: CanonicalStageV1,
        label: &'static str,
    ) -> Result<T, CanonicalPortFailureV1> {
        slot.take().ok_or_else(|| Self::reject(stage, label))
    }
}

impl CanonicalOwnerPortsV1 for AgentdOwnerPortsV1 {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let envelope = Self::take(
            &mut self.objective_envelope,
            input.stage,
            "objective envelope",
        )?;
        let profile = Self::take(
            &mut self.objective_profile,
            input.stage,
            "objective profile",
        )?;
        let context = Self::take(
            &mut self.objective_context,
            input.stage,
            "objective context",
        )?;
        let started = Instant::now();
        let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)
            .map_err(|_| Self::reject(input.stage, "objective admission"))?;
        Self::within_budget(input, started)?;
        if outcome.receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "objective authority"));
        }
        let receipt = outcome
            .compile_result
            .map_err(|_| Self::reject(input.stage, "objective conflict"))?;
        if receipt.disposition != CompileDisposition::Compiled
            || receipt.objective.semantic_digest != input.objective_digest
        {
            return Err(Self::reject(input.stage, "objective binding"));
        }
        Self::receipt(
            input,
            "objective.compiler",
            receipt.objective.semantic_digest,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let set = Self::take(
            &mut self.utility_contributions,
            input.stage,
            "utility contributions",
        )?;
        if set.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "utility objective"));
        }
        let profile = Self::take(&mut self.utility_profile, input.stage, "utility profile")?;
        let scalarization = Self::take(
            &mut self.utility_scalarization,
            input.stage,
            "utility scalarization",
        )?;
        let policy = Self::take(&mut self.utility_policy, input.stage, "utility policy")?;
        let started = Instant::now();
        let receipt = evaluate_candidates_with_policy(set, profile, scalarization, policy)
            .map_err(|_| Self::reject(input.stage, "utility evaluation"))?;
        Self::within_budget(input, started)?;
        if receipt.base.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "utility receipt objective"));
        }
        Self::receipt(
            input,
            "utility.ndu",
            receipt.evaluation_digest_v2,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let config = Self::take(&mut self.neural_config, input.stage, "neural config")?;
        let tick = Self::take(&mut self.neural_tick, input.stage, "neural tick")?;
        let previous = Self::take(&mut self.neural_previous, input.stage, "neural previous")?;
        if tick.objective_digest != input.objective_digest
            || tick.ndu_digest != input.predecessor_digest
        {
            return Err(Self::reject(input.stage, "neural binding"));
        }
        let started = Instant::now();
        let (_, receipt) = sparse_tick(&config, &tick, previous.as_ref())
            .map_err(|_| Self::reject(input.stage, "neural tick"))?;
        Self::within_budget(input, started)?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "neural authority"));
        }
        Self::receipt(
            input,
            "neuron.runtime",
            receipt.checkpoint_after,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.prompt_request, input.stage, "prompt request")?;
        if request.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "prompt objective"));
        }
        let started = Instant::now();
        let receipt =
            optimize(request).map_err(|_| Self::reject(input.stage, "prompt optimization"))?;
        Self::within_budget(input, started)?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "prompt authority"));
        }
        Self::receipt(
            input,
            "prompt.optimizer",
            receipt.receipt_digest,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(
            &mut self.intuition_request,
            input.stage,
            "intuition request",
        )?;
        if request.objective_digest != input.objective_digest {
            return Err(Self::reject(input.stage, "intuition objective"));
        }
        let started = Instant::now();
        let receipt = decide_calibrated_v2(request)
            .map_err(|_| Self::reject(input.stage, "intuition decision"))?;
        Self::within_budget(input, started)?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "intuition authority"));
        }
        let decision = match &receipt.disposition {
            CalibratedDispositionV1::Selected(candidate_id) => {
                let probability = receipt
                    .propensities
                    .iter()
                    .find(|row| &row.candidate_id == candidate_id)
                    .map(|row| row.probability)
                    .filter(|value| value.raw() > 0)
                    .ok_or_else(|| Self::reject(input.stage, "selected propensity"))?;
                self.selected_candidate = Some(candidate_id.clone());
                CanonicalPortDecisionV1::Selected {
                    candidate_id: candidate_id.clone(),
                    propensity: probability,
                }
            }
            CalibratedDispositionV1::Abstained(_) => CanonicalPortDecisionV1::Abstained,
            CalibratedDispositionV1::SlowPath(_) => CanonicalPortDecisionV1::SlowPath,
        };
        Self::receipt(input, "intuition.policy", receipt.receipt_digest, decision)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(&mut self.context_request, input.stage, "context request")?;
        if request.objective_digest != input.objective_digest
            || request.run_snapshot_digest != input.snapshot_digest
        {
            return Err(Self::reject(input.stage, "context binding"));
        }
        let started = Instant::now();
        let receipt = compile(request).map_err(|_| Self::reject(input.stage, "context compile"))?;
        Self::within_budget(input, started)?;
        if receipt.authority.grants_any() {
            return Err(Self::reject(input.stage, "context authority"));
        }
        Self::receipt(
            input,
            "context.compiler",
            receipt.context_digest,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let request = Self::take(
            &mut self.evaluation_request,
            input.stage,
            "evaluation request",
        )?;
        if request.objective_digest != input.objective_digest
            || self.selected_candidate.as_ref() != Some(&request.candidate_id)
        {
            return Err(Self::reject(input.stage, "evaluation binding"));
        }
        let session = Self::take(
            &mut self.evaluation_session,
            input.stage,
            "signed evaluation",
        )?;
        let started = Instant::now();
        let now = wall_clock_ms().map_err(|_| Self::reject(input.stage, "evaluation clock"))?;
        let receipt = session
            .evaluate(input, &request.candidate_id, now)
            .map_err(|_| Self::reject(input.stage, "signed evaluation binding or evidence"))?;
        Self::within_budget(input, started)?;
        Self::receipt(
            input,
            "learning.eval",
            receipt,
            CanonicalPortDecisionV1::Continue,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedAgentdIntelligenceRunV1 {
    pub envelope: IntelligenceHostEnvelopeV1,
    pub dispatch_proposal_digest: Digest32,
    snapshot: CanonicalIntelligenceSnapshotV1,
    candidate_ids: Vec<StableId>,
    run_snapshot: crate::AgentRunSnapshot,
    context_attachment: crate::AgentContextAttachment,
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceProductOutcomeV1 {
    Ready(PreparedAgentdIntelligenceRunV1),
    Abstained,
    SlowPath,
}

/// Result of the canonical runner after the exact prepared envelope has also
/// crossed the Agentd-owned run-admission and context-attachment boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceAdmittedOutcomeV1 {
    Ready {
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
    Clock,
    InvalidAuthorityVerifier,
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
    worker_slots: std::sync::Arc<tokio::sync::Semaphore>,
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
    evaluation_trust: Option<std::sync::Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,
}

#[path = "intelligence_product_runner.rs"]
mod runner;

#[cfg(all(feature = "qualification-legacy-learning-write", test))]
#[path = "intelligence_product_legacy_write_test_support.rs"]
mod legacy_write_test_support;
#[cfg(all(feature = "qualification-legacy-learning-write", test))]
use legacy_write_test_support::AgentdIntelligenceLedgerError;

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

fn verify_authority_file(
    file: &IntelligenceAuthorityFileV1,
    verifier: &IntelligenceAuthorityVerifierV1,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    if file.signer_id != verifier.signer_id || file.signature.len() != 64 {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    let verifying_key = VerifyingKey::from_bytes(&verifier.verifying_key)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let signature_bytes: [u8; 64] = file
        .signature
        .as_slice()
        .try_into()
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    let signature = Signature::from_bytes(&signature_bytes);
    let payload = authority_signing_payload(file)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    verifying_key
        .verify(&payload, &signature)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))
}

#[cfg(unix)]
fn validate_authority_file_path(
    path: &std::path::Path,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    use std::os::unix::fs::PermissionsExt;

    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.permissions().mode() & 0o022 != 0
    {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_authority_file_path(
    path: &std::path::Path,
    requested: &StableId,
) -> Result<(), CanonicalIntelligenceError> {
    let metadata = std::fs::metadata(path)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(requested.clone()))?;
    if !metadata.is_file() {
        return Err(CanonicalIntelligenceError::FreshnessUnavailable(
            requested.clone(),
        ));
    }
    Ok(())
}

fn wall_clock_ms() -> Result<u64, AgentdIntelligenceProductError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdIntelligenceProductError::Clock)?
        .as_millis();
    u64::try_from(millis).map_err(|_| AgentdIntelligenceProductError::Clock)
}

#[cfg(test)]
#[path = "intelligence_product_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "intelligence_evaluation_tests.rs"]
mod evaluation_tests;
