use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CapabilitySnapshotV2;
use crate::IntelligenceContractErrorV1;
use crate::IntelligenceHostEnvelopeV1;
use crate::LegalActionCandidateSetV1;
use crate::PortDecisionV1;
use crate::PortFailureClassV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LaneFStageV3 {
    ObjectiveValidated,
    LegalSetBuilt,
    UtilityEvaluated,
    EvaluationAdmitted,
    NeuralSignalCollected,
    PromptPortfolioBuilt,
    IntuitionDecided,
    ContextCompiled,
    HostEnvelopePrepared,
    DispatchProposed,
    LearningRecorded,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LaneFCompositionBudgetV3 {
    pub total_micros: u64,
    pub objective_micros: u64,
    pub legal_set_micros: u64,
    pub utility_micros: u64,
    pub evaluation_micros: u64,
    pub neural_micros: u64,
    pub prompt_micros: u64,
    pub intuition_micros: u64,
    pub context_micros: u64,
    pub envelope_micros: u64,
    pub dispatch_micros: u64,
    pub ledger_micros: u64,
}

impl LaneFCompositionBudgetV3 {
    pub(super) fn validate(self) -> Result<(), CompositionErrorV3> {
        let stages = [
            self.objective_micros,
            self.legal_set_micros,
            self.utility_micros,
            self.evaluation_micros,
            self.neural_micros,
            self.prompt_micros,
            self.intuition_micros,
            self.context_micros,
            self.envelope_micros,
            self.dispatch_micros,
            self.ledger_micros,
        ];
        if self.total_micros == 0 || stages.contains(&0) {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        let sum = stages
            .into_iter()
            .try_fold(0u64, u64::checked_add)
            .ok_or(CompositionErrorV3::InvalidBudget)?;
        if sum > self.total_micros {
            return Err(CompositionErrorV3::InvalidBudget);
        }
        Ok(())
    }

    pub(super) const fn for_stage(self, stage: LaneFStageV3) -> u64 {
        match stage {
            LaneFStageV3::ObjectiveValidated => self.objective_micros,
            LaneFStageV3::LegalSetBuilt => self.legal_set_micros,
            LaneFStageV3::UtilityEvaluated => self.utility_micros,
            LaneFStageV3::EvaluationAdmitted => self.evaluation_micros,
            LaneFStageV3::NeuralSignalCollected => self.neural_micros,
            LaneFStageV3::PromptPortfolioBuilt => self.prompt_micros,
            LaneFStageV3::IntuitionDecided => self.intuition_micros,
            LaneFStageV3::ContextCompiled => self.context_micros,
            LaneFStageV3::HostEnvelopePrepared => self.envelope_micros,
            LaneFStageV3::DispatchProposed => self.dispatch_micros,
            LaneFStageV3::LearningRecorded => self.ledger_micros,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFCompositionRequestV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot: CapabilitySnapshotV2,
    pub legal_candidates: LegalActionCandidateSetV1,
    pub budget: LaneFCompositionBudgetV3,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortInputV3 {
    pub run_id: StableId,
    pub snapshot_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub stage: LaneFStageV3,
    pub budget_micros: u64,
    pub deadline_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortReceiptV3 {
    pub stage: LaneFStageV3,
    pub producer: StableId,
    pub snapshot_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub decision: PortDecisionV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortFailureV3 {
    pub class: PortFailureClassV1,
    pub evidence_digest: Digest32,
}

/// Owner adapters for the canonical V3 composition graph. Implementations must
/// return owner-native receipt digests, remain effect-free, honor the supplied
/// deadline and preserve snapshot/candidate-set bindings.
pub trait LaneFCompositionPortsV3 {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn evaluate_utility(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3>;
    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3>;
    fn decide_intuition(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
    fn propose_dispatch(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3>;
    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StageOutcomeV3 {
    Completed,
    FallbackUsed(PortFailureClassV1),
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StageTraceV3 {
    pub stage: LaneFStageV3,
    pub producer: StableId,
    pub predecessor_digest: Digest32,
    pub output_digest: Digest32,
    pub outcome: StageOutcomeV3,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompositionDispositionV3 {
    DispatchProposed,
    Abstained,
    SlowPath,
    Failed(PortFailureClassV1),
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFCompositionReceiptV3 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub disposition: CompositionDispositionV3,
    pub host_envelope: Option<IntelligenceHostEnvelopeV1>,
    pub stages: Vec<StageTraceV3>,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompositionErrorV3 {
    InvalidBudget,
    EmptyDigest(&'static str),
    MissingCapability(&'static str),
    OwnerMismatch(&'static str),
    CandidateSnapshotMismatch,
    Contract(IntelligenceContractErrorV1),
    InvalidFailure,
    StageMismatch,
    ProducerMismatch,
    SnapshotMismatch,
    CandidateSetMismatch,
    PredecessorMismatch,
    AuthorityWidening,
    UnexpectedDecision,
    InvalidReceipt(&'static str),
    TraceDigestMismatch,
    Arithmetic,
}

impl fmt::Display for CompositionErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompositionErrorV3 {}
