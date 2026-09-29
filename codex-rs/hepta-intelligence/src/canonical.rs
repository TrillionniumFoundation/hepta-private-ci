//! Canonical intelligence-control composition facade.
//!
//! This module is the single product-facing composition contract. Historical
//! read-only vertical and evaluated-shadow APIs remain compatibility/reference
//! surfaces; they are not parallel product control planes.
//!
//! The facade owns no objective, utility, neural, prompt, intuition, context,
//! evaluation, execution, or learning facts. It binds real owner receipts to one
//! frozen snapshot and revalidates current owner/key/authority/revocation state
//! before and after every owner call. It emits no effect authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

const MAX_CANDIDATES: usize = 128;
const MAX_SUPPORT_FLOOR_PPM: u32 = 1_000_000;
const REQUIRED_OWNERS: [&str; 7] = [
    "objective.compiler",
    "utility.ndu",
    "neuron.runtime",
    "prompt.optimizer",
    "intuition.policy",
    "context.compiler",
    "learning.eval",
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateV1 {
    pub candidate_id: StableId,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetRequestV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
    pub candidate_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerBindingV1 {
    pub owner_id: StableId,
    pub generation: Generation,
    pub implementation_digest: Digest32,
    pub key_digest: Digest32,
    pub key_epoch: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalSnapshotRequestV1 {
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
    pub body_generation: Generation,
    pub configuration_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub owner_bindings: Vec<OwnerBindingV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalIntelligenceSnapshotV1 {
    objective_digest: Digest32,
    authority_epoch: u64,
    body_generation: Generation,
    configuration_digest: Digest32,
    revocation_frontier_digest: Digest32,
    owners: BTreeMap<StableId, OwnerBindingV1>,
    snapshot_digest: Digest32,
}

impl CanonicalIntelligenceSnapshotV1 {
    pub fn admit(
        mut request: CanonicalSnapshotRequestV1,
    ) -> Result<Self, CanonicalIntelligenceError> {
        if request.objective_digest.is_zero()
            || request.configuration_digest.is_zero()
            || request.revocation_frontier_digest.is_zero()
            || request.authority_epoch == 0
        {
            return Err(CanonicalIntelligenceError::InvalidSnapshot("core identity"));
        }
        request
            .owner_bindings
            .sort_by(|left, right| left.owner_id.cmp(&right.owner_id));
        if request.owner_bindings.len() != REQUIRED_OWNERS.len() {
            return Err(CanonicalIntelligenceError::InvalidSnapshot(
                "owner binding count",
            ));
        }
        let mut owners = BTreeMap::new();
        for binding in &request.owner_bindings {
            if binding.implementation_digest.is_zero()
                || binding.key_digest.is_zero()
                || binding.key_epoch == 0
            {
                return Err(CanonicalIntelligenceError::InvalidSnapshot("owner binding"));
            }
            if owners
                .insert(binding.owner_id.clone(), binding.clone())
                .is_some()
            {
                return Err(CanonicalIntelligenceError::DuplicateOwner(
                    binding.owner_id.clone(),
                ));
            }
        }
        for owner in REQUIRED_OWNERS {
            let owner_id =
                StableId::new(owner).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
            if !owners.contains_key(&owner_id) {
                return Err(CanonicalIntelligenceError::MissingOwner(owner.to_owned()));
            }
        }

        let mut bytes = b"hepta.intelligence.canonical-snapshot.v1\0".to_vec();
        bytes.extend_from_slice(request.objective_digest.as_array());
        bytes.extend_from_slice(&request.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&request.body_generation.get().to_be_bytes());
        bytes.extend_from_slice(request.configuration_digest.as_array());
        bytes.extend_from_slice(request.revocation_frontier_digest.as_array());
        for binding in &request.owner_bindings {
            push_id(&mut bytes, &binding.owner_id)?;
            bytes.extend_from_slice(&binding.generation.get().to_be_bytes());
            bytes.extend_from_slice(binding.implementation_digest.as_array());
            bytes.extend_from_slice(binding.key_digest.as_array());
            bytes.extend_from_slice(&binding.key_epoch.to_be_bytes());
        }

        Ok(Self {
            objective_digest: request.objective_digest,
            authority_epoch: request.authority_epoch,
            body_generation: request.body_generation,
            configuration_digest: request.configuration_digest,
            revocation_frontier_digest: request.revocation_frontier_digest,
            owners,
            snapshot_digest: Digest32::of_bytes(&bytes),
        })
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn body_generation(&self) -> Generation {
        self.body_generation
    }

    #[must_use]
    pub const fn configuration_digest(&self) -> Digest32 {
        self.configuration_digest
    }

    #[must_use]
    pub const fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    fn binding(&self, owner: &str) -> Result<&OwnerBindingV1, CanonicalIntelligenceError> {
        let id = StableId::new(owner).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
        self.owners
            .get(&id)
            .ok_or(CanonicalIntelligenceError::MissingOwner(owner.to_owned()))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CurrentOwnerStateV1 {
    pub owner_id: StableId,
    pub generation: Generation,
    pub implementation_digest: Digest32,
    pub key_digest: Digest32,
    pub key_epoch: u64,
    pub authority_epoch: u64,
    pub revocation_frontier_digest: Digest32,
}

pub trait CanonicalFreshnessOracleV1 {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalBudgetV1 {
    pub total_micros: u64,
    pub objective_micros: u64,
    pub utility_micros: u64,
    pub neural_micros: u64,
    pub prompt_micros: u64,
    pub intuition_micros: u64,
    pub context_micros: u64,
    pub evaluation_micros: u64,
}

impl CanonicalBudgetV1 {
    fn validate(self) -> Result<(), CanonicalIntelligenceError> {
        let stages = [
            self.objective_micros,
            self.utility_micros,
            self.neural_micros,
            self.prompt_micros,
            self.intuition_micros,
            self.context_micros,
            self.evaluation_micros,
        ];
        if self.total_micros == 0 || stages.contains(&0) {
            return Err(CanonicalIntelligenceError::InvalidBudget);
        }
        let sum = stages
            .into_iter()
            .try_fold(0_u64, u64::checked_add)
            .ok_or(CanonicalIntelligenceError::InvalidBudget)?;
        if sum > self.total_micros {
            return Err(CanonicalIntelligenceError::InvalidBudget);
        }
        Ok(())
    }

    const fn for_stage(self, stage: CanonicalStageV1) -> u64 {
        match stage {
            CanonicalStageV1::ObjectiveValidated => self.objective_micros,
            CanonicalStageV1::UtilityEvaluated => self.utility_micros,
            CanonicalStageV1::NeuralSignalCollected => self.neural_micros,
            CanonicalStageV1::PromptPortfolioBuilt => self.prompt_micros,
            CanonicalStageV1::IntuitionDecided => self.intuition_micros,
            CanonicalStageV1::ContextCompiled => self.context_micros,
            CanonicalStageV1::EvaluationAdmitted => self.evaluation_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalIntelligenceRunRequestV1 {
    pub run_id: StableId,
    pub snapshot: CanonicalIntelligenceSnapshotV1,
    pub legal_candidates: LegalActionCandidateSetRequestV1,
    pub budget: CanonicalBudgetV1,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CanonicalStageV1 {
    ObjectiveValidated,
    UtilityEvaluated,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
    EvaluationAdmitted,
}

impl CanonicalStageV1 {
    const fn owner(self) -> &'static str {
        match self {
            Self::ObjectiveValidated => "objective.compiler",
            Self::UtilityEvaluated => "utility.ndu",
            Self::NeuralSignalCollected => "neuron.runtime",
            Self::PromptPortfolioBuilt => "prompt.optimizer",
            Self::IntuitionDecided => "intuition.policy",
            Self::ContextCompiled => "context.compiler",
            Self::EvaluationAdmitted => "learning.eval",
        }
    }

    const fn code(self) -> u8 {
        match self {
            Self::ObjectiveValidated => 0,
            Self::UtilityEvaluated => 1,
            Self::NeuralSignalCollected => 2,
            Self::PromptPortfolioBuilt => 3,
            Self::IntuitionDecided => 4,
            Self::ContextCompiled => 5,
            Self::EvaluationAdmitted => 6,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalPortDecisionV1 {
    Continue,
    Selected {
        candidate_id: StableId,
        propensity: ProbabilityQ32,
    },
    Abstained,
    SlowPath,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPortInputV1 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub budget_micros: u64,
    pub stage: CanonicalStageV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPortReceiptV1 {
    pub stage: CanonicalStageV1,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub decision: CanonicalPortDecisionV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalPortFailureClassV1 {
    Rejected,
    Unavailable,
    TimedOut,
    Quarantined,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPortFailureV1 {
    pub class: CanonicalPortFailureClassV1,
    pub evidence_digest: Digest32,
}

pub trait CanonicalOwnerPortsV1 {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>;

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>;

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>;

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>;

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>;

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>;

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AdvisoryDecisionV1 {
    Selected {
        candidate_id: StableId,
        propensity: ProbabilityQ32,
    },
    Abstained,
    SlowPath,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdvisoryDecisionReceiptV1 {
    pub run_id: StableId,
    pub candidate_set_digest: Digest32,
    pub intuition_receipt_digest: Digest32,
    pub decision: AdvisoryDecisionV1,
    pub decision_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextAssemblyReceiptV1 {
    pub run_id: StableId,
    pub decision_digest: Digest32,
    pub context_receipt_digest: Digest32,
    pub assembly_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalStageTraceV1 {
    pub stage: CanonicalStageV1,
    pub producer: StableId,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub utility_receipt_digest: Digest32,
    pub neural_receipt_digest: Digest32,
    pub prompt_receipt_digest: Digest32,
    pub decision: AdvisoryDecisionReceiptV1,
    pub context_receipt_digest: Digest32,
    pub context_binding_digest: Digest32,
    pub evaluation_receipt_digest: Digest32,
    pub trace_digest: Digest32,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalTerminalReceiptV1 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub decision: AdvisoryDecisionReceiptV1,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalRunOutcomeV1 {
    Ready(IntelligenceHostEnvelopeV1),
    Abstained(CanonicalTerminalReceiptV1),
    SlowPath(CanonicalTerminalReceiptV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalIntelligenceError {
    InvalidCandidateSet(&'static str),
    DuplicateCandidate(StableId),
    InvalidSnapshot(&'static str),
    DuplicateOwner(StableId),
    MissingOwner(String),
    InvalidBudget,
    FreshnessUnavailable(StableId),
    StaleOwner(StableId),
    KeyDrift(StableId),
    AuthorityEpochDrift(StableId),
    RevocationFrontierDrift(StableId),
    PortFailure {
        stage: CanonicalStageV1,
        class: CanonicalPortFailureClassV1,
        evidence_digest: Digest32,
    },
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    PredecessorMismatch,
    EmptyDigest(&'static str),
    AuthorityWidening,
    UnexpectedDecision,
    Arithmetic,
}

impl fmt::Display for CanonicalIntelligenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CanonicalIntelligenceError {}

pub fn build_legal_candidates(
    mut request: LegalActionCandidateSetRequestV1,
) -> Result<LegalActionCandidateSetV1, CanonicalIntelligenceError> {
    if request.generator_id.as_str() != "intelligence.control" {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet("generator"));
    }
    if request.state_digest.is_zero() || request.grammar_digest.is_zero() {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet("digest"));
    }
    if request.candidates.is_empty() || request.candidates.len() > MAX_CANDIDATES {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "candidate count",
        ));
    }
    if request.support_floor_ppm > MAX_SUPPORT_FLOOR_PPM {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "support floor",
        ));
    }
    request
        .candidates
        .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    for candidate in &request.candidates {
        if candidate.support_digest.is_zero() {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "candidate support",
            ));
        }
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(CanonicalIntelligenceError::DuplicateCandidate(
                candidate.candidate_id.clone(),
            ));
        }
    }
    let mut bytes = b"hepta.intelligence.legal-action-candidate-set.v1\0".to_vec();
    push_id(&mut bytes, &request.candidate_set_id)?;
    bytes.extend_from_slice(request.state_digest.as_array());
    push_id(&mut bytes, &request.generator_id)?;
    bytes.extend_from_slice(request.grammar_digest.as_array());
    bytes.extend_from_slice(&request.support_floor_ppm.to_be_bytes());
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(LegalActionCandidateSetV1 {
        candidate_set_id: request.candidate_set_id,
        state_digest: request.state_digest,
        generator_id: request.generator_id,
        grammar_digest: request.grammar_digest,
        candidates: request.candidates,
        support_floor_ppm: request.support_floor_ppm,
        candidate_set_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn decide_boundary(
    run_id: &StableId,
    legal: &LegalActionCandidateSetV1,
    intuition: &CanonicalPortReceiptV1,
) -> Result<AdvisoryDecisionReceiptV1, CanonicalIntelligenceError> {
    // The DTO is public and mutable. Recompute its canonical digest before use;
    // possession of a digest alone is not proof of candidate membership.
    let rebuilt = build_legal_candidates(LegalActionCandidateSetRequestV1 {
        candidate_set_id: legal.candidate_set_id.clone(),
        state_digest: legal.state_digest,
        generator_id: legal.generator_id.clone(),
        grammar_digest: legal.grammar_digest,
        candidates: legal.candidates.clone(),
        support_floor_ppm: legal.support_floor_ppm,
    })?;
    if legal.authority.grants_any() {
        return Err(CanonicalIntelligenceError::AuthorityWidening);
    }
    if rebuilt.candidate_set_digest != legal.candidate_set_digest {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "digest mismatch",
        ));
    }
    let candidate_set_digest = rebuilt.candidate_set_digest;
    if intuition.stage != CanonicalStageV1::IntuitionDecided {
        return Err(CanonicalIntelligenceError::StageMismatch);
    }
    if intuition.producer.as_str() != "intuition.policy" {
        return Err(CanonicalIntelligenceError::ProducerMismatch);
    }
    if intuition.output_digest.is_zero() || candidate_set_digest.is_zero() {
        return Err(CanonicalIntelligenceError::EmptyDigest("decision"));
    }
    if intuition.authority.grants_any() {
        return Err(CanonicalIntelligenceError::AuthorityWidening);
    }
    let decision = match &intuition.decision {
        CanonicalPortDecisionV1::Selected {
            candidate_id,
            propensity,
        } => {
            if !rebuilt
                .candidates
                .iter()
                .any(|candidate| &candidate.candidate_id == candidate_id)
            {
                return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                    "selected candidate absent",
                ));
            }
            if propensity.raw() == 0 {
                return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                    "selected propensity is zero",
                ));
            }
            AdvisoryDecisionV1::Selected {
                candidate_id: candidate_id.clone(),
                propensity: *propensity,
            }
        }
        CanonicalPortDecisionV1::Abstained => AdvisoryDecisionV1::Abstained,
        CanonicalPortDecisionV1::SlowPath => AdvisoryDecisionV1::SlowPath,
        CanonicalPortDecisionV1::Continue => {
            return Err(CanonicalIntelligenceError::UnexpectedDecision);
        }
    };
    let mut bytes = b"hepta.intelligence.advisory-decision.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    bytes.extend_from_slice(candidate_set_digest.as_array());
    bytes.extend_from_slice(intuition.output_digest.as_array());
    match &decision {
        AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } => {
            bytes.push(0);
            push_id(&mut bytes, candidate_id)?;
            bytes.extend_from_slice(&propensity.raw().to_be_bytes());
        }
        AdvisoryDecisionV1::Abstained => bytes.push(1),
        AdvisoryDecisionV1::SlowPath => bytes.push(2),
    }
    Ok(AdvisoryDecisionReceiptV1 {
        run_id: run_id.clone(),
        candidate_set_digest,
        intuition_receipt_digest: intuition.output_digest,
        decision,
        decision_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn assemble_context(
    decision: &AdvisoryDecisionReceiptV1,
    context: &CanonicalPortReceiptV1,
) -> Result<ContextAssemblyReceiptV1, CanonicalIntelligenceError> {
    if context.stage != CanonicalStageV1::ContextCompiled {
        return Err(CanonicalIntelligenceError::StageMismatch);
    }
    if context.producer.as_str() != "context.compiler" {
        return Err(CanonicalIntelligenceError::ProducerMismatch);
    }
    if context.output_digest.is_zero() || decision.decision_digest.is_zero() {
        return Err(CanonicalIntelligenceError::EmptyDigest("context"));
    }
    if context.predecessor_digest != decision.intuition_receipt_digest {
        return Err(CanonicalIntelligenceError::PredecessorMismatch);
    }
    if context.authority.grants_any() || decision.authority.grants_any() {
        return Err(CanonicalIntelligenceError::AuthorityWidening);
    }
    if !matches!(decision.decision, AdvisoryDecisionV1::Selected { .. }) {
        return Err(CanonicalIntelligenceError::UnexpectedDecision);
    }
    let mut bytes = b"hepta.intelligence.context-boundary.v1\0".to_vec();
    push_id(&mut bytes, &decision.run_id)?;
    bytes.extend_from_slice(decision.decision_digest.as_array());
    bytes.extend_from_slice(context.output_digest.as_array());
    Ok(ContextAssemblyReceiptV1 {
        run_id: decision.run_id.clone(),
        decision_digest: decision.decision_digest,
        context_receipt_digest: context.output_digest,
        assembly_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn validate_current_snapshot<O: CanonicalFreshnessOracleV1>(
    snapshot: &CanonicalIntelligenceSnapshotV1,
    oracle: &mut O,
) -> Result<(), CanonicalIntelligenceError> {
    for owner in REQUIRED_OWNERS {
        require_current(snapshot, oracle, owner)?;
    }
    Ok(())
}

pub fn prepare_intelligence_run<P: CanonicalOwnerPortsV1, O: CanonicalFreshnessOracleV1>(
    request: CanonicalIntelligenceRunRequestV1,
    ports: &mut P,
    oracle: &mut O,
) -> Result<CanonicalRunOutcomeV1, CanonicalIntelligenceError> {
    request.budget.validate()?;
    if request.snapshot.objective_digest() != request.legal_candidates.state_digest {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "objective/state binding",
        ));
    }
    let legal = build_legal_candidates(request.legal_candidates.clone())?;
    let snapshot_digest = request.snapshot.digest();
    let mut predecessor = legal.candidate_set_digest;
    let mut traces = Vec::with_capacity(7);
    let mut output = BTreeMap::<CanonicalStageV1, Digest32>::new();

    macro_rules! stage {
        ($stage:expr, $call:expr) => {{
            let receipt = run_stage(&request, &legal, predecessor, $stage, ports, oracle, $call)?;
            predecessor = receipt.output_digest;
            output.insert($stage, receipt.output_digest);
            traces.push(CanonicalStageTraceV1 {
                stage: $stage,
                producer: receipt.producer.clone(),
                predecessor_digest: receipt.predecessor_digest,
                output_digest: receipt.output_digest,
            });
            receipt
        }};
    }

    let _objective = stage!(
        CanonicalStageV1::ObjectiveValidated,
        |ports: &mut P, input| ports.validate_objective(input)
    );
    let _utility = stage!(
        CanonicalStageV1::UtilityEvaluated,
        |ports: &mut P, input| ports.evaluate_utility(input)
    );
    let _neural = stage!(
        CanonicalStageV1::NeuralSignalCollected,
        |ports: &mut P, input| ports.collect_neural_signal(input)
    );
    let _prompt = stage!(
        CanonicalStageV1::PromptPortfolioBuilt,
        |ports: &mut P, input| ports.build_prompt_portfolio(input)
    );
    let intuition = stage!(
        CanonicalStageV1::IntuitionDecided,
        |ports: &mut P, input| ports.decide_intuition(input)
    );
    let decision = decide_boundary(&request.run_id, &legal, &intuition)?;

    match decision.decision {
        AdvisoryDecisionV1::Abstained | AdvisoryDecisionV1::SlowPath => {
            validate_current_snapshot(&request.snapshot, oracle)?;
            let trace_digest = digest_trace(
                &request.run_id,
                snapshot_digest,
                legal.candidate_set_digest,
                &traces,
            )?;
            let terminal = CanonicalTerminalReceiptV1 {
                run_id: request.run_id,
                snapshot_digest,
                candidate_set_digest: legal.candidate_set_digest,
                decision: decision.clone(),
                trace_digest,
                authority: AuthorityPosture::DENY_ALL,
            };
            return Ok(match decision.decision {
                AdvisoryDecisionV1::Abstained => CanonicalRunOutcomeV1::Abstained(terminal),
                AdvisoryDecisionV1::SlowPath => CanonicalRunOutcomeV1::SlowPath(terminal),
                AdvisoryDecisionV1::Selected { .. } => unreachable!(),
            });
        }
        AdvisoryDecisionV1::Selected { .. } => {}
    }

    let context = stage!(CanonicalStageV1::ContextCompiled, |ports: &mut P, input| {
        ports.compile_context(input)
    });
    let context_binding = assemble_context(&decision, &context)?;
    let _evaluation = stage!(
        CanonicalStageV1::EvaluationAdmitted,
        |ports: &mut P, input| ports.evaluate_candidate(input)
    );

    // Revalidate every owner once more at the product handoff boundary. A
    // revocation, key rotation or owner generation change after its own stage
    // but before Agentd use must fail closed.
    for owner in REQUIRED_OWNERS {
        require_current(&request.snapshot, oracle, owner)?;
    }

    let trace_digest = digest_trace(
        &request.run_id,
        snapshot_digest,
        legal.candidate_set_digest,
        &traces,
    )?;
    let utility_receipt_digest = stage_output(&output, CanonicalStageV1::UtilityEvaluated)?;
    let neural_receipt_digest = stage_output(&output, CanonicalStageV1::NeuralSignalCollected)?;
    let prompt_receipt_digest = stage_output(&output, CanonicalStageV1::PromptPortfolioBuilt)?;
    let context_receipt_digest = stage_output(&output, CanonicalStageV1::ContextCompiled)?;
    // The final chain predecessor is the admitted evaluation output, not an earlier stage.
    let evaluation_receipt_digest = predecessor;

    let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
    push_id(&mut bytes, &request.run_id)?;
    for digest in [
        snapshot_digest,
        request.snapshot.objective_digest(),
        legal.candidate_set_digest,
        utility_receipt_digest,
        neural_receipt_digest,
        prompt_receipt_digest,
        decision.decision_digest,
        context_receipt_digest,
        context_binding.assembly_digest,
        evaluation_receipt_digest,
        trace_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }

    Ok(CanonicalRunOutcomeV1::Ready(IntelligenceHostEnvelopeV1 {
        run_id: request.run_id,
        snapshot_digest,
        objective_digest: request.snapshot.objective_digest(),
        candidate_set_digest: legal.candidate_set_digest,
        utility_receipt_digest,
        neural_receipt_digest,
        prompt_receipt_digest,
        decision,
        context_receipt_digest,
        context_binding_digest: context_binding.assembly_digest,
        evaluation_receipt_digest,
        trace_digest,
        envelope_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    }))
}

fn run_stage<P, O, F>(
    request: &CanonicalIntelligenceRunRequestV1,
    legal: &LegalActionCandidateSetV1,
    predecessor: Digest32,
    stage: CanonicalStageV1,
    ports: &mut P,
    oracle: &mut O,
    call: F,
) -> Result<CanonicalPortReceiptV1, CanonicalIntelligenceError>
where
    P: CanonicalOwnerPortsV1,
    O: CanonicalFreshnessOracleV1,
    F: FnOnce(
        &mut P,
        &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1>,
{
    let owner = stage.owner();
    require_current(&request.snapshot, oracle, owner)?;
    let input = CanonicalPortInputV1 {
        run_id: request.run_id.clone(),
        snapshot_digest: request.snapshot.digest(),
        objective_digest: request.snapshot.objective_digest(),
        candidate_set_digest: legal.candidate_set_digest,
        predecessor_digest: predecessor,
        budget_micros: request.budget.for_stage(stage),
        stage,
    };
    let receipt =
        call(ports, &input).map_err(|failure| CanonicalIntelligenceError::PortFailure {
            stage,
            class: failure.class,
            evidence_digest: failure.evidence_digest,
        })?;
    validate_port_receipt(&input, owner, &receipt)?;
    match stage {
        CanonicalStageV1::IntuitionDecided => {
            if matches!(receipt.decision, CanonicalPortDecisionV1::Continue) {
                return Err(CanonicalIntelligenceError::UnexpectedDecision);
            }
        }
        _ => {
            if !matches!(receipt.decision, CanonicalPortDecisionV1::Continue) {
                return Err(CanonicalIntelligenceError::UnexpectedDecision);
            }
        }
    }
    require_current(&request.snapshot, oracle, owner)?;
    Ok(receipt)
}

fn validate_port_receipt(
    input: &CanonicalPortInputV1,
    expected_owner: &str,
    receipt: &CanonicalPortReceiptV1,
) -> Result<(), CanonicalIntelligenceError> {
    if receipt.stage != input.stage {
        return Err(CanonicalIntelligenceError::StageMismatch);
    }
    if receipt.producer.as_str() != expected_owner {
        return Err(CanonicalIntelligenceError::ProducerMismatch);
    }
    if receipt.snapshot_digest != input.snapshot_digest {
        return Err(CanonicalIntelligenceError::SnapshotMismatch);
    }
    if receipt.predecessor_digest != input.predecessor_digest {
        return Err(CanonicalIntelligenceError::PredecessorMismatch);
    }
    if receipt.output_digest.is_zero() {
        return Err(CanonicalIntelligenceError::EmptyDigest("owner output"));
    }
    if receipt.authority.grants_any() {
        return Err(CanonicalIntelligenceError::AuthorityWidening);
    }
    Ok(())
}

fn require_current<O: CanonicalFreshnessOracleV1>(
    snapshot: &CanonicalIntelligenceSnapshotV1,
    oracle: &mut O,
    owner: &'static str,
) -> Result<(), CanonicalIntelligenceError> {
    let expected = snapshot.binding(owner)?;
    let current = oracle
        .current(&expected.owner_id)
        .map_err(|_| CanonicalIntelligenceError::FreshnessUnavailable(expected.owner_id.clone()))?;
    if current.owner_id != expected.owner_id
        || current.generation != expected.generation
        || current.implementation_digest != expected.implementation_digest
    {
        return Err(CanonicalIntelligenceError::StaleOwner(
            expected.owner_id.clone(),
        ));
    }
    if current.key_digest != expected.key_digest || current.key_epoch != expected.key_epoch {
        return Err(CanonicalIntelligenceError::KeyDrift(
            expected.owner_id.clone(),
        ));
    }
    if current.authority_epoch != snapshot.authority_epoch() {
        return Err(CanonicalIntelligenceError::AuthorityEpochDrift(
            expected.owner_id.clone(),
        ));
    }
    if current.revocation_frontier_digest != snapshot.revocation_frontier_digest() {
        return Err(CanonicalIntelligenceError::RevocationFrontierDrift(
            expected.owner_id.clone(),
        ));
    }
    Ok(())
}

fn stage_output(
    output: &BTreeMap<CanonicalStageV1, Digest32>,
    stage: CanonicalStageV1,
) -> Result<Digest32, CanonicalIntelligenceError> {
    output
        .get(&stage)
        .copied()
        .filter(|digest| !digest.is_zero())
        .ok_or(CanonicalIntelligenceError::EmptyDigest("stage output"))
}

fn digest_trace(
    run_id: &StableId,
    snapshot_digest: Digest32,
    candidate_set_digest: Digest32,
    traces: &[CanonicalStageTraceV1],
) -> Result<Digest32, CanonicalIntelligenceError> {
    let mut bytes = b"hepta.intelligence.canonical-trace.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(candidate_set_digest.as_array());
    let count = u32::try_from(traces.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for trace in traces {
        bytes.push(trace.stage.code());
        push_id(&mut bytes, &trace.producer)?;
        bytes.extend_from_slice(trace.predecessor_digest.as_array());
        bytes.extend_from_slice(trace.output_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), CanonicalIntelligenceError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
#[path = "canonical_tests.rs"]
mod tests;
